#!/usr/bin/env python3
"""
Set tax to "0" in raw.model_extracted_data.raw_data for given ref_no(s).

Updates all non-deleted rows matching each ref_no.

Usage:
    uv run scripts/zero_out_tax.py REF_NO [REF_NO ...] --dry-run
    uv run scripts/zero_out_tax.py REF_NO [REF_NO ...] --apply

Examples:
    uv run scripts/zero_out_tax.py I-0012104 170651 --dry-run
    uv run scripts/zero_out_tax.py I-0012104 I-0012051 170651 170259-01 --apply
"""

import sys
import argparse
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from scripts.backfill_invoices_data.db_utils import connect_to_db

logger = logging.getLogger(__name__)

FETCH_QUERY = """
SELECT id, raw_data->>'ref_no' AS ref_no, raw_data->>'tax' AS tax
FROM raw.model_extracted_data
WHERE raw_data->>'ref_no' = %(ref_no)s
  AND deleted_at IS NULL
"""

UPDATE_QUERY = """
UPDATE raw.model_extracted_data
SET raw_data = jsonb_set(raw_data, '{tax}', '"0"')
WHERE raw_data->>'ref_no' = %(ref_no)s
  AND deleted_at IS NULL
  AND raw_data->>'tax' NOT IN ('0', '0.0', '0.00')
  AND raw_data->>'tax' IS NOT NULL
"""


def zero_out_tax(ref_nos: list[str], dry_run: bool = False) -> int:
    connection = connect_to_db()
    if connection is None:
        logger.error("Failed to connect to database")
        return -1

    cursor = connection.cursor()
    total_updated = 0

    try:
        for ref_no in ref_nos:
            cursor.execute(FETCH_QUERY, {"ref_no": ref_no})
            rows = cursor.fetchall()

            if not rows:
                logger.info(f"  {ref_no}: no non-deleted rows found")
                continue

            non_zero = [r for r in rows if r[2] not in ("0", "0.00", "0.0", None)]
            if not non_zero:
                logger.info(f"  {ref_no}: {len(rows)} row(s), tax already 0 -- skipping")
                continue

            current_tax = non_zero[0][2]
            logger.info(f"  {ref_no}: {len(rows)} row(s), tax={current_tax} --> 0")

            if dry_run:
                total_updated += len(non_zero)
                continue

            cursor.execute(UPDATE_QUERY, {"ref_no": ref_no})
            total_updated += cursor.rowcount

        if dry_run:
            logger.info(f"DRY RUN -- would update {total_updated} row(s) total")
        else:
            connection.commit()
            logger.info(f"Updated {total_updated} row(s) total")

        return total_updated

    except Exception as e:
        logger.exception(f"Error zeroing out tax: {e}")
        connection.rollback()
        return -1
    finally:
        cursor.close()
        connection.close()


def main():
    parser = argparse.ArgumentParser(
        description="Set tax to 0 in raw.model_extracted_data for given ref_no(s)"
    )
    parser.add_argument("ref_nos", nargs="+",
                        help="One or more ref_no values to zero out tax for")

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

    result = zero_out_tax(args.ref_nos, dry_run=args.dry_run)
    return 0 if result >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
