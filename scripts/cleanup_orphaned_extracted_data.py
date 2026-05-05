#!/usr/bin/env python3
"""
Cleanup orphaned raw.model_extracted_data records.

Finds model_extracted_data rows that are still active (deleted_at IS NULL) but
whose parent pdf_extraction_queue row has already been soft-deleted with reason
'not_invoice_nor_credit'. This happens when the cascade in
classify_and_soft_delete_non_invoices.py targeted the wrong schema
(public.model_extracted_data instead of raw.model_extracted_data).

Usage:
    # Dry run (preview only)
    python scripts/cleanup_orphaned_extracted_data.py --dry-run

    # Apply the fix
    python scripts/cleanup_orphaned_extracted_data.py --yes
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.script_logger import get_script_logger
from mpi_backend.database import db_context

logger = get_script_logger(__file__)

ORPHAN_COUNT_SQL = r"""
SELECT COUNT(*) FROM raw.model_extracted_data med
JOIN raw.pdf_extraction_queue peq ON med.pdf_extraction_queue_id = peq.id
WHERE med.deleted_at IS NULL
  AND peq.deleted_at IS NOT NULL
  AND peq.deletion_reason = 'not_invoice_nor_credit'
"""

ORPHAN_UPDATE_SQL = r"""
UPDATE raw.model_extracted_data med
SET deleted_at = :timestamp, deletion_reason = 'parent_pdf_not_invoice'
FROM raw.pdf_extraction_queue peq
WHERE med.pdf_extraction_queue_id = peq.id
  AND med.deleted_at IS NULL
  AND peq.deleted_at IS NOT NULL
  AND peq.deletion_reason = 'not_invoice_nor_credit'
"""


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Cleanup orphaned raw.model_extracted_data records",
    )
    parser.add_argument('--dry-run', action='store_true', help='Preview only')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation')
    return parser.parse_args()


def main():
    args = parse_arguments()

    logger.info("=== ORPHANED MODEL_EXTRACTED_DATA CLEANUP ===")
    logger.info(f"Dry run: {args.dry_run}")

    with db_context() as session:
        count = session.execute(text(ORPHAN_COUNT_SQL)).scalar()
        logger.info(f"Found {count} orphaned records in raw.model_extracted_data")

        if count == 0:
            logger.info("Nothing to clean up.")
            return

        if args.dry_run:
            logger.info(f"DRY-RUN: Would soft-delete {count} orphaned records")
            logger.info("*** DRY RUN COMPLETE - NO CHANGES MADE ***")
            return

        if not args.yes:
            response = input(f"\nSoft-delete {count} orphaned records? (y/N): ")
            if response.lower() != 'y':
                logger.info("Cancelled.")
                return

        now = datetime.now(timezone.utc)
        result = session.execute(text(ORPHAN_UPDATE_SQL), {'timestamp': now})
        session.commit()
        logger.info(f"Soft-deleted {result.rowcount} orphaned records")
        logger.info("*** CLEANUP COMPLETE ***")


if __name__ == "__main__":
    main()
