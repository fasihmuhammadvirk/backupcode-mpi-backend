import sys
import argparse
from typing import Dict, Tuple
import os

# Add the parent directory to the path so we can import mpi_backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from mpi_backend.database import SessionLocal  # noqa: E402
from mpi_backend.database.models import (  # noqa: E402
    InvoiceItem,
    ItemClassification,
)


# Canonical letter account per category used for DB defaulting only
# (QuickBooks export translates letters to full account paths)
CATEGORY_TO_LETTER: Dict[str, str] = {
    'M': 'M',
    'E': 'E',
    # NOTE: 'L' intentionally omitted per requirement to not auto-set
    # NOTE: 'A' is user-chosen; do not auto-set to A
}


def build_classification_lookup(db_session) -> Dict[str, str]:
    """
    Return a dict mapping exact `item` (sheet_name) -> category (uppercase).
    """
    lookup: Dict[str, str] = {}
    rows = db_session.query(ItemClassification).all()
    for row in rows:
        if not row.item:
            continue
        item_key = row.item.strip()
        if not item_key:
            continue
        category = (row.category or '').strip().upper()
        if not category:
            continue
        lookup[item_key] = category
    return lookup


def determine_new_account(sheet_name: str,
                          lookup: Dict[str, str]) -> Tuple[bool, str]:
    """
    Determine if and what the new account should be.

    - Only update if `sheet_name` exists in classification lookup
      (exact match)
    - Category M/E → set default letter ('M' or 'E')
    - Category L → do not change
    - If current account is already 'A' (user choice), do not change
    - Any other category → no change

    Returns (should_update, new_account_value)
    """
    if not sheet_name:
        return False, ''

    sheet_key = sheet_name.strip()
    if sheet_key not in lookup:
        return False, ''

    category = lookup[sheet_key]

    # Preserve user override to 'A'
    # (Check requires current account, handled at caller)

    # Per requirement to avoid L, skip changing records with category L.
    if category == 'L':
        return False, ''

    if category in CATEGORY_TO_LETTER:
        return True, CATEGORY_TO_LETTER[category]

    # Unknown category -> no change
    return False, ''


def update_accounts(dry_run: bool = True) -> int:
    """
    Update invoice_items.account values based on item_classification.

    Returns number of rows that would be/are updated.
    """
    db = SessionLocal()
    updated_count = 0
    try:
        lookup = build_classification_lookup(db)

        # Iterate in chunks to avoid loading everything at once
        query = db.query(InvoiceItem)
        offset = 0
        limit = 5000
        while True:
            batch = query.offset(offset).limit(limit).all()
            if not batch:
                break

            for item in batch:
                should_update, new_account = determine_new_account(
                    item.sheet_name, lookup
                )
                if not should_update:
                    continue

                current_account = (item.account or '')
                if current_account.upper() == 'A':
                    # Preserve user's explicit A
                    continue
                if current_account == new_account:
                    continue

                updated_count += 1
                if not dry_run:
                    item.account = new_account

            if not dry_run:
                db.commit()

            offset += limit

        return updated_count
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            'Update invoice_items.account from item_classification using '
            'exact sheet_name matches. Maps M/E/A to QB accounts and '
            'clears L.'
        )
    )
    parser.add_argument(
        '--commit',
        action='store_true',
        help=(
            'Apply changes. Without this flag, runs in dry-run mode.'
        )
    )
    args = parser.parse_args(argv)

    dry_run = not args.commit
    updated = update_accounts(dry_run=dry_run)

    if dry_run:
        print(
            f"Dry-run: {updated} invoice item(s) would be updated."
        )
    else:
        print(
            f"Success: {updated} invoice item(s) updated."
        )


if __name__ == '__main__':
    sys.exit(main())
