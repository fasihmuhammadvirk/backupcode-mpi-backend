#!/usr/bin/env python3
"""
Add a misc charge to raw.model_extracted_data.raw_data.misc_charges for a given PDF filename.

Updates all non-deleted rows matching the filename pattern, replacing the entire
misc_charges array to avoid duplicates.

Usage:
    uv run scripts/add_misc_charge.py FILENAME LABEL AMOUNT --dry-run
    uv run scripts/add_misc_charge.py FILENAME LABEL AMOUNT --apply

Examples:
    uv run scripts/add_misc_charge.py PH_7157_091025_83262443.PDF "CUSTOMER DISCOUNT" 40000 --dry-run
    uv run scripts/add_misc_charge.py PH_7157_091025_83262443.PDF "CUSTOMER DISCOUNT" 40000 --apply
    uv run scripts/add_misc_charge.py PH_11_020125_79340706.PDF "BILL FOR BACKORDER" 33811.13 --apply
    uv run scripts/add_misc_charge.py PH_7181_021825_82851265.PDF "CUSTOMER DISCOUNT" -200 --apply
"""

import sys
import json
import argparse
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from scripts.backfill_invoices_data.db_utils import connect_to_db

logger = logging.getLogger(__name__)

FETCH_QUERY = """
SELECT id, raw_data->'misc_charges' AS misc_charges
FROM raw.model_extracted_data
WHERE s3_file_key ILIKE %(pattern)s ESCAPE '\\'
  AND deleted_at IS NULL
"""

UPDATE_QUERY = """
UPDATE raw.model_extracted_data
SET raw_data = jsonb_set(
    raw_data,
    '{misc_charges}',
    %(new_charges)s::jsonb
)
WHERE id = %(row_id)s
  AND deleted_at IS NULL
"""


def add_misc_charge(filename: str, label: str, amount: float,
                    dry_run: bool = False) -> int:
    connection = connect_to_db()
    if connection is None:
        logger.error("Failed to connect to database")
        return -1

    cursor = connection.cursor()
    escaped = filename.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"

    try:
        cursor.execute(FETCH_QUERY, {"pattern": pattern})
        rows = cursor.fetchall()

        if not rows:
            logger.info(f"No non-deleted rows found matching '{filename}'")
            return 0

        logger.info(f"Found {len(rows)} non-deleted row(s) matching '{filename}'")

        new_charge = {"label": label, "amount": amount}
        updated = 0

        for row_id, existing_raw in rows:
            existing_charges = existing_raw if isinstance(existing_raw, list) else []

            already_exists = any(
                c.get("label") == label and c.get("amount") == amount
                for c in existing_charges
            )
            if already_exists:
                logger.info(f"  row {row_id}: charge already exists -- skipping")
                continue

            updated_charges = existing_charges + [new_charge]
            charges_json = json.dumps(updated_charges)

            logger.info(f"  row {row_id}: {json.dumps(existing_charges)} --> {charges_json}")

            if dry_run:
                updated += 1
                continue

            cursor.execute(UPDATE_QUERY, {
                "row_id": row_id,
                "new_charges": charges_json,
            })
            updated += cursor.rowcount

        if dry_run:
            logger.info(f"DRY RUN -- would update {updated} row(s)")
        else:
            connection.commit()
            logger.info(f"Updated {updated} row(s)")

        return updated

    except Exception as e:
        logger.exception(f"Error adding misc charge: {e}")
        connection.rollback()
        return -1
    finally:
        cursor.close()
        connection.close()


def main():
    parser = argparse.ArgumentParser(
        description="Add a misc charge to raw.model_extracted_data"
    )
    parser.add_argument("filename",
                        help="PDF filename pattern (e.g. PH_7157_091025_83262443.PDF)")
    parser.add_argument("label",
                        help="Charge label (e.g. 'CUSTOMER DISCOUNT')")
    parser.add_argument("amount", type=float,
                        help="Charge amount (e.g. 40000, -200, 33811.13)")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="Preview without making changes")
    mode.add_argument("--apply", action="store_true",
                      help="Apply changes to the database")

    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.print_help()
        return 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    result = add_misc_charge(args.filename, args.label, args.amount,
                             dry_run=args.dry_run)
    return 0 if result >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
