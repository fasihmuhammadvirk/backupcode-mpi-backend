#!/usr/bin/env python3
"""
Replace a line item 'item' value in raw.model_extracted_data.raw_data.

Handles both data structures:
  1. Flat: raw_data -> line_items[]
  2. Multi-invoice: raw_data -> invoices[] -> line_items[]

Usage:
    python scripts/replace_raw_line_item.py OLD_ITEM NEW_ITEM [options]

Examples:
    python scripts/replace_raw_line_item.py "BKCAP 30" BKCAP30 --dry-run
    python scripts/replace_raw_line_item.py "BKCAP 30" BKCAP30
"""

import sys
import argparse
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from scripts.backfill_invoices_data.db_utils import connect_to_db

logger = logging.getLogger(__name__)

REPLACE_QUERY = """
WITH params AS (
    SELECT %(old_item)s AS old_item, %(new_item)s AS new_item
)
UPDATE raw.model_extracted_data m
SET raw_data = CASE
    WHEN m.raw_data ? 'invoices' THEN
        jsonb_set(
            m.raw_data,
            '{invoices}',
            (
                SELECT jsonb_agg(
                    jsonb_set(
                        inv,
                        '{line_items}',
                        (
                            SELECT jsonb_agg(
                                CASE
                                    WHEN li->>'item' = p.old_item
                                    THEN jsonb_set(li, '{item}', to_jsonb(p.new_item))
                                    ELSE li
                                END
                            )
                            FROM jsonb_array_elements(inv->'line_items') AS li
                        )
                    )
                )
                FROM jsonb_array_elements(m.raw_data->'invoices') AS inv
            )
        )
    ELSE
        jsonb_set(
            m.raw_data,
            '{line_items}',
            (
                SELECT jsonb_agg(
                    CASE
                        WHEN li->>'item' = p.old_item
                        THEN jsonb_set(li, '{item}', to_jsonb(p.new_item))
                        ELSE li
                    END
                )
                FROM jsonb_array_elements(m.raw_data->'line_items') AS li
            )
        )
END
FROM params p
WHERE
    EXISTS (
        SELECT 1
        FROM jsonb_array_elements(m.raw_data->'line_items') AS li
        WHERE li->>'item' = p.old_item
    )
    OR
    EXISTS (
        SELECT 1
        FROM jsonb_array_elements(m.raw_data->'invoices') AS inv,
             jsonb_array_elements(inv->'line_items') AS li
        WHERE li->>'item' = p.old_item
    )
"""

COUNT_QUERY = """
SELECT count(*) FROM raw.model_extracted_data m
WHERE
    EXISTS (
        SELECT 1
        FROM jsonb_array_elements(m.raw_data->'line_items') AS li
        WHERE li->>'item' = %(old_item)s
    )
    OR
    EXISTS (
        SELECT 1
        FROM jsonb_array_elements(m.raw_data->'invoices') AS inv,
             jsonb_array_elements(inv->'line_items') AS li
        WHERE li->>'item' = %(old_item)s
    )
"""


def replace_item(old_item: str, new_item: str, dry_run: bool = False) -> int:
    connection = connect_to_db()
    if connection is None:
        logger.error("Failed to connect to database")
        return -1

    cursor = connection.cursor()
    params = {"old_item": old_item, "new_item": new_item}

    try:
        # Count matching rows first
        cursor.execute(COUNT_QUERY, params)
        count = cursor.fetchone()[0]
        logger.info(f"Found {count} row(s) containing item '{old_item}'")

        if count == 0:
            logger.info("Nothing to update.")
            return 0

        if dry_run:
            logger.info(f"DRY RUN -- would update {count} row(s): "
                        f"'{old_item}' --> '{new_item}'")
            return count

        cursor.execute(REPLACE_QUERY, params)
        updated = cursor.rowcount
        connection.commit()
        logger.info(f"Updated {updated} row(s): '{old_item}' --> '{new_item}'")
        return updated

    except Exception as e:
        logger.exception(f"Error replacing item: {e}")
        connection.rollback()
        return -1
    finally:
        cursor.close()
        connection.close()


def main():
    parser = argparse.ArgumentParser(
        description="Replace a line item 'item' value in raw.model_extracted_data"
    )
    parser.add_argument("old_item", help="Current item value to find")
    parser.add_argument("new_item", help="New item value to replace with")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without making changes")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    result = replace_item(args.old_item, args.new_item, dry_run=args.dry_run)
    return 0 if result >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
