#!/usr/bin/env python3
"""
Restore Misclassified Soft-Deleted PDFs

Re-classifies soft-deleted PDFs that were marked as 'not_invoice_nor_credit' and
restores any that the updated classifier now recognises as invoices or credits
(e.g. Flowmark "Customer Credit" PDFs that should be CREDIT).

Reverse cascade (mirrors classify_and_soft_delete_non_invoices.py):
1. pdf_extraction_queue        -- clear deleted_at / deletion_reason
2. model_extracted_data        -- restore children deleted with reason 'parent_pdf_not_invoice'
3. email_download_queue        -- restore parent deleted with reason 'all_pdfs_not_invoices'

Usage:
    # Dry run (preview only)
    uv run python scripts/restore_misclassified_deleted_pdfs.py --dry-run

    # Small batch test
    uv run python scripts/restore_misclassified_deleted_pdfs.py --limit 10 --yes

    # Full run
    uv run python scripts/restore_misclassified_deleted_pdfs.py --yes
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import text

# Add the parent directory to Python path to import from mpi_backend
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.script_logger import get_script_logger, timed
from mpi_backend.database import db_context
from mpi_backend.utils.document_classifier import DocumentClassifier
from mpi_backend.config import (
    INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
    INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
    INVOICES_PDFS_BUCKET_NAME,
    INVOICES_PDFS_REGION,
)

import boto3
from urllib.parse import urlparse

logger = get_script_logger(__file__)

# S3 client (initialized lazily)
s3_client = None


def get_s3_client():
    """Initialize S3 client if needed."""
    global s3_client
    if s3_client is None:
        if INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY and INVOICES_PDFS_AWS_SERVER_SECRET_KEY:
            s3_client = boto3.client(
                "s3",
                aws_access_key_id=INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
                aws_secret_access_key=INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
                region_name=INVOICES_PDFS_REGION or "us-east-2",
            )
        else:
            s3_client = boto3.client("s3")
    return s3_client


def stream_from_s3(s3_key: str) -> Optional[bytes]:
    """Stream a PDF from S3 directly into memory (no disk I/O)."""
    try:
        if s3_key.startswith("s3://"):
            parsed = urlparse(s3_key)
            bucket = parsed.netloc
            key = parsed.path.lstrip("/")
        else:
            bucket = INVOICES_PDFS_BUCKET_NAME or "mpi-plumbing-invoices"
            key = s3_key

        s3 = get_s3_client()
        response = s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    except Exception as e:
        logger.error(f"Failed to stream {s3_key}: {e}")
        return None


def classify_single_pdf(pdf_id: UUID, s3_key: str) -> Tuple[UUID, str, bool, Optional[str]]:
    """Classify a single PDF (thread-safe, no DB writes).

    Returns:
        (pdf_id, doc_type, is_invoice_or_credit, error_or_none)
    """
    try:
        pdf_bytes = stream_from_s3(s3_key)
        if pdf_bytes is None:
            return (pdf_id, "ERROR", False, "missing_file")

        result = DocumentClassifier.classify(s3_key, pdf_bytes=pdf_bytes)
        is_valid = result.is_invoice_or_credit
        doc_type = result.doc_type.value

        if is_valid:
            logger.info(f"PDF {pdf_id} ({s3_key}): now classified as {doc_type} -- will restore")
        else:
            logger.debug(f"PDF {pdf_id} ({s3_key}): still {doc_type} -- stays deleted")

        return (pdf_id, doc_type, is_valid, None)

    except Exception as e:
        logger.error(f"Error classifying PDF {pdf_id}: {e}")
        return (pdf_id, "ERROR", False, str(e))


def classify_pdfs_batch(
    work_items: List[Tuple[UUID, str]],
    workers: int = 1,
) -> Tuple[List[UUID], Dict[str, int]]:
    """Classify a batch of deleted PDFs and return IDs that should be restored.

    Returns:
        (pdf_ids_to_restore, classification_stats)
    """
    pdfs_to_restore: List[UUID] = []
    classification_stats: Dict[str, int] = {
        "INVOICE": 0,
        "CREDIT": 0,
        "STATEMENT": 0,
        "BID": 0,
        "OTHER": 0,
        "ERROR": 0,
    }

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdf_classify") as executor:
        futures = {
            executor.submit(classify_single_pdf, pdf_id, s3_key): pdf_id
            for pdf_id, s3_key in work_items
        }

        for future in as_completed(futures):
            pdf_id, doc_type, is_valid, _error = future.result()
            classification_stats[doc_type] += 1
            if is_valid:
                pdfs_to_restore.append(pdf_id)

    return pdfs_to_restore, classification_stats


def cascade_restore(
    pdf_ids: List[UUID], session, dry_run: bool = False
) -> Dict[str, int]:
    """Reverse cascade: restore PDFs, their children, and parent emails.

    Restore order:
    1. pdf_extraction_queue        (reason was 'not_invoice_nor_credit')
    2. model_extracted_data        (reason was 'parent_pdf_not_invoice')
    3. email_download_queue        (reason was 'all_pdfs_not_invoices')

    Returns:
        Dict with counts: {'pdfs': n, 'extracted_data': n, 'emails': n}
    """
    if not pdf_ids:
        return {"pdfs": 0, "extracted_data": 0, "emails": 0}

    pdf_id_strings = [str(pid) for pid in pdf_ids]

    if dry_run:
        logger.info(f"DRY-RUN: Would cascade restore for {len(pdf_ids)} PDFs")

        count_med_sql = r"""
        SELECT COUNT(*) FROM raw.model_extracted_data
        WHERE pdf_extraction_queue_id = ANY(:pdf_ids\:\:uuid[])
        AND deleted_at IS NOT NULL
        AND deletion_reason = 'parent_pdf_not_invoice'
        """
        med_count = session.execute(text(count_med_sql), {"pdf_ids": pdf_id_strings}).scalar()

        count_emails_sql = r"""
        SELECT COUNT(DISTINCT eq.id)
        FROM raw.email_download_queue eq
        INNER JOIN raw.pdf_extraction_queue peq ON peq.email_queue_id = eq.id
        WHERE peq.id = ANY(:pdf_ids\:\:uuid[])
        AND eq.deleted_at IS NOT NULL
        AND eq.deletion_reason = 'all_pdfs_not_invoices'
        """
        email_count = session.execute(text(count_emails_sql), {"pdf_ids": pdf_id_strings}).scalar()

        logger.info(
            f"DRY-RUN: Would restore {len(pdf_ids)} PDFs, "
            f"{med_count} extracted_data records, {email_count} emails"
        )
        return {
            "pdfs": len(pdf_ids),
            "extracted_data": med_count or 0,
            "emails": email_count or 0,
        }

    try:
        # Step 1 -- Restore PDFs
        restore_pdfs_sql = r"""
        UPDATE raw.pdf_extraction_queue
        SET deleted_at = NULL, deletion_reason = NULL
        WHERE id = ANY(:pdf_ids\:\:uuid[])
        AND deleted_at IS NOT NULL
        """
        pdf_result = session.execute(text(restore_pdfs_sql), {"pdf_ids": pdf_id_strings})
        pdfs_restored = pdf_result.rowcount

        # Step 2 -- Restore child extracted data (only those deleted because of parent)
        restore_med_sql = r"""
        UPDATE raw.model_extracted_data
        SET deleted_at = NULL, deletion_reason = NULL
        WHERE pdf_extraction_queue_id = ANY(:pdf_ids\:\:uuid[])
        AND deleted_at IS NOT NULL
        AND deletion_reason = 'parent_pdf_not_invoice'
        """
        med_result = session.execute(text(restore_med_sql), {"pdf_ids": pdf_id_strings})
        med_restored = med_result.rowcount

        # Step 3 -- Restore parent emails that were deleted because all PDFs were non-invoices
        restore_emails_sql = r"""
        UPDATE raw.email_download_queue
        SET deleted_at = NULL, deletion_reason = NULL
        WHERE id IN (
            SELECT DISTINCT email_queue_id
            FROM raw.pdf_extraction_queue
            WHERE id = ANY(:pdf_ids\:\:uuid[])
        )
        AND deleted_at IS NOT NULL
        AND deletion_reason = 'all_pdfs_not_invoices'
        """
        email_result = session.execute(text(restore_emails_sql), {"pdf_ids": pdf_id_strings})
        emails_restored = email_result.rowcount

        session.commit()
        logger.info(
            f"Cascade restore: {pdfs_restored} PDFs, "
            f"{med_restored} extracted_data, {emails_restored} emails"
        )
        return {
            "pdfs": pdfs_restored,
            "extracted_data": med_restored,
            "emails": emails_restored,
        }

    except Exception as e:
        session.rollback()
        logger.error(f"Failed to cascade restore: {e}")
        raise


def get_deleted_pdfs(session, limit: Optional[int] = None) -> List[Tuple[UUID, str]]:
    """Query soft-deleted PDFs that were removed by the classification script.

    Returns:
        List of (id, s3_key) tuples.
    """
    sql = r"""
    SELECT id, s3_key FROM raw.pdf_extraction_queue
    WHERE deleted_at IS NOT NULL
      AND deletion_reason = 'not_invoice_nor_credit'
    """
    if limit:
        sql += f"\nLIMIT {int(limit)}"

    rows = session.execute(text(sql)).fetchall()
    return [(row[0], row[1]) for row in rows]


def print_verification_queries():
    """Print SQL queries for verifying the restore results."""
    queries = [
        (
            "PDFs by deletion reason",
            """SELECT deletion_reason, COUNT(*)
            FROM raw.pdf_extraction_queue
            WHERE deleted_at IS NOT NULL
            GROUP BY deletion_reason;""",
        ),
        (
            "Active PDFs",
            "SELECT COUNT(*) FROM raw.pdf_extraction_queue WHERE deleted_at IS NULL;",
        ),
        (
            "Extracted data by deletion reason",
            """SELECT deletion_reason, COUNT(*)
            FROM raw.model_extracted_data
            WHERE deleted_at IS NOT NULL
            GROUP BY deletion_reason;""",
        ),
        (
            "Active extracted data",
            "SELECT COUNT(*) FROM raw.model_extracted_data WHERE deleted_at IS NULL;",
        ),
        (
            "Emails by deletion reason",
            """SELECT deletion_reason, COUNT(*)
            FROM raw.email_download_queue
            WHERE deleted_at IS NOT NULL
            GROUP BY deletion_reason;""",
        ),
        (
            "Active emails",
            "SELECT COUNT(*) FROM raw.email_download_queue WHERE deleted_at IS NULL;",
        ),
    ]

    logger.info("=== VERIFICATION QUERIES ===")
    for name, query in queries:
        logger.info(f"{name}:")
        logger.info(f"  {query.strip()}")
        logger.info("")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Re-classify soft-deleted PDFs and restore misclassified invoices/credits",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview what would be restored (dry run)
  uv run python scripts/restore_misclassified_deleted_pdfs.py --dry-run

  # Restore first 10 records for testing
  uv run python scripts/restore_misclassified_deleted_pdfs.py --limit 10 --yes

  # Full run
  uv run python scripts/restore_misclassified_deleted_pdfs.py --yes
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview counts without making DB changes",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="PDFs per batch (default: 1000)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Max PDFs to process (for testing)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="S3/classify thread count (default: 8)",
    )

    return parser.parse_args()


def repair_orphaned_children(session, dry_run: bool = False) -> int:
    """Fix extracted_data records left soft-deleted after a previous partial restore.

    Finds active PDFs (deleted_at IS NULL) whose children in raw.model_extracted_data
    are still soft-deleted with reason 'parent_pdf_not_invoice'.
    """
    if dry_run:
        count_sql = r"""
        SELECT COUNT(*) FROM raw.model_extracted_data med
        WHERE med.deleted_at IS NOT NULL
        AND med.deletion_reason = 'parent_pdf_not_invoice'
        AND EXISTS (
            SELECT 1 FROM raw.pdf_extraction_queue peq
            WHERE peq.id = med.pdf_extraction_queue_id
            AND peq.deleted_at IS NULL
        )
        """
        count = session.execute(text(count_sql)).scalar() or 0
        logger.info(f"DRY-RUN: Would repair {count} orphaned extracted_data records")
        return count

    repair_sql = r"""
    UPDATE raw.model_extracted_data
    SET deleted_at = NULL, deletion_reason = NULL
    WHERE deleted_at IS NOT NULL
    AND deletion_reason = 'parent_pdf_not_invoice'
    AND EXISTS (
        SELECT 1 FROM raw.pdf_extraction_queue peq
        WHERE peq.id = raw.model_extracted_data.pdf_extraction_queue_id
        AND peq.deleted_at IS NULL
    )
    """
    result = session.execute(text(repair_sql))
    repaired = result.rowcount
    session.commit()
    logger.info(f"Repaired {repaired} orphaned extracted_data records")
    return repaired


def main():
    args = parse_arguments()

    logger.info("=== RESTORE MISCLASSIFIED SOFT-DELETED PDFs ===")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Limit: {args.limit or 'None'}")
    logger.info(f"Workers: {args.workers}")

    # Pre-initialize S3 client before thread pool starts
    get_s3_client()

    with db_context() as session:
        logger.info("Querying soft-deleted PDFs (deletion_reason = 'not_invoice_nor_credit')...")
        work_items = get_deleted_pdfs(session, args.limit)

        if not work_items:
            logger.info("No soft-deleted PDFs found to re-classify")
            logger.info("Checking for orphaned children from a previous partial restore...")
            orphan_count = repair_orphaned_children(session, args.dry_run)
            if orphan_count:
                logger.info(f"Repaired {orphan_count} orphaned extracted_data records")
            else:
                logger.info("No orphaned children found")
            return

        logger.info(f"Found {len(work_items)} soft-deleted PDFs to re-classify")

        if not args.dry_run and not args.yes:
            response = input(
                f"\nRe-classify {len(work_items)} deleted PDFs and restore misclassified ones? (y/N): "
            )
            if response.lower() != "y":
                logger.info("Operation cancelled")
                return

        total_stats: Dict[str, int] = {
            "INVOICE": 0,
            "CREDIT": 0,
            "STATEMENT": 0,
            "BID": 0,
            "OTHER": 0,
            "ERROR": 0,
        }
        total_restore_stats: Dict[str, int] = {"pdfs": 0, "extracted_data": 0, "emails": 0}
        batch_count = 0
        total_items = len(work_items)
        num_batches = (total_items + args.batch_size - 1) // args.batch_size

        with timed("full_reclassification", logger):
            for i in range(0, total_items, args.batch_size):
                batch_count += 1
                batch_items = work_items[i : i + args.batch_size]

                logger.info(
                    f"Processing batch {batch_count}/{num_batches}: "
                    f"PDFs {i + 1} to {min(i + args.batch_size, total_items)}"
                )

                with timed(f"batch_{batch_count}", logger):
                    pdfs_to_restore, batch_stats = classify_pdfs_batch(
                        batch_items, workers=args.workers
                    )

                    for key, value in batch_stats.items():
                        total_stats[key] += value

                    restore_stats = cascade_restore(pdfs_to_restore, session, args.dry_run)
                    for key in total_restore_stats:
                        total_restore_stats[key] += restore_stats[key]

                    logger.info(
                        f"Batch {batch_count} complete: re-classified {len(batch_items)} PDFs, "
                        f"restoring {len(pdfs_to_restore)}"
                    )

    # Final summary
    logger.info("=== FINAL SUMMARY ===")
    logger.info(f"Total PDFs re-classified: {total_items}")
    logger.info("Classification breakdown:")
    for doc_type, count in total_stats.items():
        logger.info(f"  {doc_type}: {count}")
    logger.info("Cascade restores:")
    logger.info(f"  PDFs restored: {total_restore_stats['pdfs']}")
    logger.info(f"  Extracted data records restored: {total_restore_stats['extracted_data']}")
    logger.info(f"  Emails restored: {total_restore_stats['emails']}")

    # Repair any orphaned children from a previous partial restore
    with db_context() as session:
        orphan_count = repair_orphaned_children(session, args.dry_run)
        if orphan_count:
            logger.info(f"Repaired {orphan_count} orphaned extracted_data records")
            total_restore_stats["extracted_data"] += orphan_count

    if args.dry_run:
        logger.info("*** DRY RUN COMPLETE -- NO CHANGES MADE ***")
    else:
        logger.info("*** RESTORE COMPLETE ***")
        print_verification_queries()


if __name__ == "__main__":
    main()
