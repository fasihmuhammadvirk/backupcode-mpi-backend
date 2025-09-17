import sys
import argparse
from typing import Dict, Tuple, Optional
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
        item_key = row.item.strip().upper()
        if not item_key:
            continue
        category = (row.category or '').strip().upper()
        if not category:
            continue
        lookup[item_key] = category
    return lookup


def _map_qb_account_to_letter(account_str: str) -> str:
    """Map a QuickBooks account string to letter code (M/E/A)."""
    if not account_str:
        return ''
    s = account_str.lower()
    if 'job materials purchased' in s:
        return 'M'
    if 'job equipment' in s:
        return 'E'
    if 'additional material' in s or 'subcontractors expense' in s:
        return 'A'
    return ''


def determine_new_account(
    sheet_name: str,
    lookup: Dict[str, str],
    mpi_item: Optional[str] = None,
    current_account: Optional[str] = None,
    icc=None,
) -> Tuple[bool, str]:
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
    # Preserve user override 'A'
    if (current_account or '').strip().upper() == 'A':
        return False, ''

    # UIDI-specific mapping from mpi_item → letter account (case-insensitive)
    if mpi_item:
        uidi_map = {
            'UIDI-JOB MATERIALS PURCHASED': 'M',
            'UIDI JOB MATERIAL': 'M',
            'UIDI-JOB EQUIPMENT': 'E',
            'UIDI-SPRINKLER SPECIALTY ITEM': 'M',
            'UIDI-DRAINAGE MATERIAL': 'M',
        }
        key = mpi_item.strip().upper()
        if key in uidi_map:
            return True, uidi_map[key]

    if not sheet_name:
        return False, ''

    sheet_key = sheet_name.strip().upper()
    if sheet_key in lookup:
        category = lookup[sheet_key]
        if category == 'L':
            return False, ''
        if category in CATEGORY_TO_LETTER:
            return True, CATEGORY_TO_LETTER[category]

        return False, ''

    # Fuzzy fallback via ItemClassificationController if provided
    if icc is not None:
        try:
            qb_account = icc.get_classification(sheet_name)
            letter = _map_qb_account_to_letter(qb_account)
            if letter:
                return True, letter
        except Exception:
            pass

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
        # Create controller for fuzzy fallback
        from mpi_backend.database.controllers.ItemClassification import (
            ItemClassificationController,
        )
        icc = ItemClassificationController(db)

        # Iterate using keyset pagination by primary key to avoid skipping rows
        batch_size = 5000
        passes = 0
        while True:
            passes += 1
            round_updates = 0
            last_id = 0
            while True:
                batch = (
                    db.query(InvoiceItem)
                    .filter(InvoiceItem.id > last_id)
                    .order_by(InvoiceItem.id.asc())
                    .limit(batch_size)
                    .all()
                )
                if not batch:
                    break

                for item in batch:
                    current_account = (item.account or '').strip()

                    # Preserve explicit 'A'
                    if current_account.upper() == 'A':
                        continue

                    # If current is a long QuickBooks account path, normalize to M/E
                    if current_account:
                        mapped = _map_qb_account_to_letter(current_account)
                        if mapped in ('M', 'E') and mapped != current_account:
                            round_updates += 1
                            if not dry_run:
                                item.account = mapped
                        # If not a known path, leave as-is
                        continue

                    # Current is empty: determine new account via UIDI/Classification/fuzzy
                    should_update, new_account = determine_new_account(
                        sheet_name=item.sheet_name,
                        lookup=lookup,
                        mpi_item=getattr(item, 'mpi_item', None),
                        current_account=current_account,
                        icc=icc,
                    )
                    if not should_update:
                        continue

                    # Assign new letter
                    round_updates += 1
                    if not dry_run:
                        item.account = new_account

                if not dry_run and round_updates:
                    db.commit()

                # Advance keyset cursor
                last_id = batch[-1].id

            updated_count += round_updates
            # If no changes in this pass, we're done
            if round_updates == 0:
                break

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
