#!/usr/bin/env python3
"""
Delete Failed Invoices
======================

Removes invoices with status 'FAILED' from the database, deletes all related
invoice items, and attempts to remove associated PDF files from local storage
and S3.

Usage:
  python scripts/delete_failed_invoices.py [--dry-run] [--older-than DAYS]

Options:
  --dry-run          Show what would be deleted without performing deletions
  --older-than DAYS  Only delete failed invoices older than N days
  --limit N          Maximum number to process in this run (default: 500)

Notes:
  - Requires project environment to be configured (DB, AWS creds).
  - S3 deletion uses key pattern '<Supplier Name>/<invoice_id>.pdf' with
    multiple case/extension variants handled.
"""

import argparse
from datetime import datetime, timedelta
import os
import sys
from pathlib import Path
import logging
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.controllers.Invoice import InvoiceController
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.database.models import Invoice as InvoiceModel
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.utils.s3_utils import delete_file_from_s3


logger = logging.getLogger("scripts.delete_failed_invoices")
logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")


def delete_one_failed_invoice(db: Session, invoice: InvoiceModel, dry_run: bool) -> bool:
    try:
        supplier_name = (
            SupplierController(db).get_supplier_by_id(invoice.supplier_id)
            or "unknown"
        )
        local_pdf_path = os.path.join(
            INVOICE_DOWNLOAD_FOLDER, invoice.filename
        )

        logger.info(
            f"Deleting FAILED invoice: id={invoice.id} "
            f"supplier='{supplier_name}' "
            f"file='{invoice.filename}'"
        )

        if dry_run:
            logger.info(
                "DRY RUN: Would delete items, DB record, local file, "
                "and S3 file"
            )
            return True

        # Delete items first
        InvoiceItemController(db).delete_invoice_items(invoice_id=invoice.id, db=db)

        # Delete S3 file (best-effort)
        s3_key_base = f"{supplier_name}/{invoice.id}"
        deleted_s3 = delete_file_from_s3(s3_key_base, is_invoice=True)
        if not deleted_s3:
            logger.warning(
                f"S3 object not found for base: {s3_key_base}"
            )

        # Delete local file if exists
        if os.path.exists(local_pdf_path):
            try:
                os.remove(local_pdf_path)
                logger.info(f"Deleted local file: {local_pdf_path}")
            except Exception as e:
                logger.warning(
                    f"Failed to delete local file '{local_pdf_path}': {e}"
                )

        # Delete invoice record
        InvoiceController(db).delete_invoice(str(invoice.id), db)
        return True
    except Exception as e:
        logger.error(f"Error deleting failed invoice {invoice.id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Delete invoices with status FAILED"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without deleting"
    )
    parser.add_argument(
        "--older-than",
        type=int,
        default=0,
        help="Only delete if older than N days",
    )
    parser.add_argument(
        "--limit", type=int, default=500, help="Maximum records to process"
    )
    args = parser.parse_args()

    cutoff_date = None
    if args.older_than and args.older_than > 0:
        cutoff_date = datetime.utcnow().date() - timedelta(days=args.older_than)
        logger.info(f"Only deleting FAILED invoices before: {cutoff_date}")

    db_gen = get_db()
    db = next(db_gen)
    try:
        # Query FAILED invoices (limit applied)
        q = db.query(InvoiceModel).filter(InvoiceModel.status == 'FAILED')
        if cutoff_date:
            q = q.filter(InvoiceModel.date is not None).filter(
                InvoiceModel.date < cutoff_date
            )
        failed_invoices = q.limit(args.limit).all()

        if not failed_invoices:
            logger.info("No FAILED invoices found to delete.")
            return 0

        logger.info(
            f"Found {len(failed_invoices)} FAILED invoices to process"
        )
        successes = 0
        for inv in failed_invoices:
            if delete_one_failed_invoice(db, inv, args.dry_run):
                successes += 1

        status_word = 'Would delete' if args.dry_run else 'Deleted'
        logger.info(
            f"Completed. {status_word} {successes}/"
            f"{len(failed_invoices)} FAILED invoices"
        )
        return 0
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
