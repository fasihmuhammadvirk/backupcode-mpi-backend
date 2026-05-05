#!/usr/bin/env python3
"""
Document Classification and Cascading Soft Delete Script

This script uses the existing document classifier to identify non-invoice/credit
documents by processing unique PDFs from pdf_extraction_queue and cascades
soft-deletes across all three tables:
- pdf_extraction_queue (primary)
- model_extracted_data (child records)
- email_download_queue (parent, only if ALL PDFs are deleted)

Data Relationships:
    email_download_queue (1) → (many) pdf_extraction_queue → (many) model_extracted_data

Features:
- Processes unique PDFs (avoids re-classifying same PDF multiple times)
- Cascading soft deletes with consistent timestamps
- Batch processing for memory efficiency
- Dry-run mode for preview without changes
- Comprehensive error handling and logging
- Progress tracking and statistics
- S3 in-memory streaming (no disk I/O)
- Command line arguments for customization
- Atomic transactions with rollback on error

Deletion Reasons:
- pdf_extraction_queue: 'not_invoice_nor_credit'
- model_extracted_data: 'parent_pdf_not_invoice'
- email_download_queue: 'all_pdfs_not_invoices'

Usage:
    # Dry run (preview only)
    python scripts/classify_and_soft_delete_non_invoices.py --dry-run

    # Process with custom batch size
    python scripts/classify_and_soft_delete_non_invoices.py --batch-size 200

    # Process limited PDFs for testing
    python scripts/classify_and_soft_delete_non_invoices.py --limit 100

    # Full run with confirmation
    python scripts/classify_and_soft_delete_non_invoices.py --yes

Example output:
    [2026-01-17 15:30:00 - script.classify_and_soft_delete_non_invoices->main():123]INFO: Starting document classification backfill
    [2026-01-17 15:30:01 - script.classify_and_soft_delete_non_invoices->main():125]INFO: Found 1,234 PDFs to process
    [2026-01-17 15:30:15 - script.classify_and_soft_delete_non_invoices->process_batch():89]INFO: Processed batch 1/13: classified 100 PDFs, marked 23 for deletion
    [2026-01-17 15:30:30 - script.classify_and_soft_delete_non_invoices->main():156]INFO: SUMMARY: Processed 1,234 PDFs, cascaded soft-deletes
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from urllib.parse import urlparse
from uuid import UUID

import boto3
from sqlalchemy import text

# Add the parent directory to Python path to import from mpi_backend
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.script_logger import get_script_logger, timed
from mpi_backend.database import db_context
from mpi_backend.database.models.PdfExtractionQueue import PdfExtractionQueue
from mpi_backend.utils.document_classifier import DocumentClassifier
from mpi_backend.utils.document_types import DocumentType
from mpi_backend.config import (
    INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
    INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
    INVOICES_PDFS_BUCKET_NAME,
    INVOICES_PDFS_REGION
)

logger = get_script_logger(__file__)

# Classification source: 'keyword' (default) or 'gemini' (use Gemini doc_type from raw.model_extracted_data)
CLASSIFICATION_SOURCE = os.environ.get("CLASSIFICATION_SOURCE", "gemini")

# S3 client (initialized lazily)
s3_client = None

def get_s3_client():
    """Initialize S3 client if needed"""
    global s3_client
    if s3_client is None:
        # Use invoice-specific credentials if available, otherwise default boto3 behavior
        if INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY and INVOICES_PDFS_AWS_SERVER_SECRET_KEY:
            s3_client = boto3.client(
                's3',
                aws_access_key_id=INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
                aws_secret_access_key=INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
                region_name=INVOICES_PDFS_REGION or 'us-east-2'
            )
        else:
            # Fall back to default boto3 credentials (env vars, IAM role, etc.)
            s3_client = boto3.client('s3')
    return s3_client

def stream_from_s3(s3_key: str) -> Optional[bytes]:
    """
    Stream a PDF from S3 directly into memory (no disk I/O).

    Args:
        s3_key: S3 key (format: s3://bucket/path or just the key path)

    Returns:
        Raw PDF bytes, or None on failure.
    """
    try:
        if s3_key.startswith('s3://'):
            parsed = urlparse(s3_key)
            bucket = parsed.netloc
            key = parsed.path.lstrip('/')
        else:
            bucket = INVOICES_PDFS_BUCKET_NAME or 'mpi-plumbing-invoices'
            key = s3_key

        s3 = get_s3_client()
        response = s3.get_object(Bucket=bucket, Key=key)
        return response['Body'].read()

    except Exception as e:
        logger.error(f"Failed to stream {s3_key}: {e}")
        return None

def organize_file_by_classification(
    pdf_bytes: Optional[bytes], doc_type: str, organize_dir: str, record_id: str, s3_key: str,
) -> None:
    """
    Write PDF bytes to a classification-based folder for manual assessment.

    Args:
        pdf_bytes: Raw PDF content (None signals a missing/error file).
        doc_type: Classification type (INVOICE, CREDIT, STATEMENT, OTHER, ERROR)
        organize_dir: Base directory for organized files
        record_id: Database record ID (as string) for unique naming
        s3_key: Original S3 key, used to derive the filename.
    """
    try:
        organize_path = Path(organize_dir)

        # Create classification folder
        class_folder = organize_path / doc_type
        class_folder.mkdir(parents=True, exist_ok=True)

        if pdf_bytes is None:
            # Create a text file with the error info
            dest_filename = f"{record_id}_MISSING_FILE.txt"
            dest_path = class_folder / dest_filename
            with open(dest_path, 'w') as f:
                f.write(f"Record ID: {record_id}\nS3 key: {s3_key}\nClassification: {doc_type}\n")
            logger.debug(f"Created error marker: {dest_path}")
            return

        # Derive filename from S3 key
        base_name = Path(s3_key).name
        dest_filename = f"{record_id}_{base_name}"
        dest_path = class_folder / dest_filename

        dest_path.write_bytes(pdf_bytes)
        logger.debug(f"Organized file: {s3_key} -> {dest_path}")

    except Exception as e:
        logger.warning(f"Failed to organize file for {record_id}: {e}")

def _lookup_gemini_doc_types(pdf_id: UUID, session) -> Optional[list[str]]:
    """Look up Gemini doc_type(s) from raw.model_extracted_data for a given PDF.

    Returns a list of doc_type strings (one per invoice in the extraction),
    or None if no Gemini extraction exists.
    """
    try:
        row = session.execute(
            text(
                "SELECT raw_data FROM raw.model_extracted_data "
                "WHERE pdf_extraction_queue_id = :pdf_id "
                "AND deleted_at IS NULL "
                "ORDER BY extracted_at DESC LIMIT 1"
            ),
            {"pdf_id": str(pdf_id)},
        ).fetchone()
        if row is None:
            return None

        import json
        raw_data = row[0] if isinstance(row[0], dict) else json.loads(row[0])

        # Multi-invoice format: {invoices: [{doc_type: ...}, ...]}
        if "invoices" in raw_data and isinstance(raw_data["invoices"], list):
            return [inv.get("doc_type", "") for inv in raw_data["invoices"]]

        # Single-invoice format
        doc_type = raw_data.get("doc_type", "")
        return [doc_type] if doc_type else None

    except Exception as e:
        session.rollback()
        logger.warning(f"Failed to look up Gemini doc_type for {pdf_id}: {e}")
        return None


def classify_single_pdf(
    pdf_id: UUID,
    s3_key: str,
    organize_dir: Optional[str] = None,
    gemini_doc_types: Optional[list[str]] = None,
) -> Tuple[UUID, str, bool, Optional[str]]:
    """Classify a single PDF (thread-safe, no DB writes).

    Streams bytes from S3, runs classifier in-memory, optionally organizes file.
    When CLASSIFICATION_SOURCE=gemini and gemini_doc_types is provided, uses
    the Gemini-extracted doc_type instead of the keyword classifier.

    Args:
        pdf_id: Primary key of the PdfExtractionQueue row.
        s3_key: S3 object key for the PDF.
        organize_dir: Optional directory to write classified files into.
        gemini_doc_types: Pre-fetched list of Gemini doc_type strings for this PDF.

    Returns:
        (pdf_id, doc_type, is_valid, error_or_none)
    """
    try:
        # Gemini classification path
        if CLASSIFICATION_SOURCE == "gemini" and gemini_doc_types:
            # If ANY page is invoice-like, keep the PDF
            doc_types = []
            for dt_str in gemini_doc_types:
                try:
                    doc_types.append(DocumentType(dt_str))
                except ValueError:
                    doc_types.append(DocumentType.UNKNOWN)

            is_valid = any(dt.is_invoice_like for dt in doc_types)
            # Use first doc_type as the "primary" classification for stats
            primary_doc_type = doc_types[0] if doc_types else DocumentType.UNKNOWN

            if organize_dir:
                pdf_bytes = stream_from_s3(s3_key)
                organize_file_by_classification(pdf_bytes, primary_doc_type.value, organize_dir, str(pdf_id), s3_key)

            source_label = "gemini"
            if not is_valid:
                logger.info(f"PDF {pdf_id} ({s3_key}): {source_label} classified as {[dt.value for dt in doc_types]}, marking for deletion")
            else:
                logger.debug(f"PDF {pdf_id} ({s3_key}): {source_label} classified as {[dt.value for dt in doc_types]}, keeping")

            return (pdf_id, primary_doc_type.value, is_valid, None)

        # Keyword classification path (default)
        pdf_bytes = stream_from_s3(s3_key)
        if pdf_bytes is None:
            if organize_dir:
                organize_file_by_classification(None, "ERROR", organize_dir, str(pdf_id), s3_key)
            return (pdf_id, "ERROR", True, "missing_file")

        result = DocumentClassifier.classify(s3_key, pdf_bytes=pdf_bytes)
        is_valid, doc_type = result.is_invoice_or_credit, result.doc_type.value

        if organize_dir:
            organize_file_by_classification(pdf_bytes, doc_type, organize_dir, str(pdf_id), s3_key)

        if not is_valid:
            logger.info(f"PDF {pdf_id} ({s3_key}): classified as {doc_type}, marking for deletion")
        else:
            logger.debug(f"PDF {pdf_id} ({s3_key}): classified as {doc_type}, keeping")

        return (pdf_id, doc_type, is_valid, None)

    except Exception as e:
        logger.error(f"Error classifying PDF {pdf_id}: {e}")
        if organize_dir:
            organize_file_by_classification(None, "ERROR", organize_dir, str(pdf_id), s3_key)
        return (pdf_id, "ERROR", True, str(e))


def classify_pdfs_batch(
    work_items: List[Tuple[UUID, str]],
    organize_dir: Optional[str] = None,
    workers: int = 1,
    session=None,
) -> Tuple[List[UUID], Dict[str, int]]:
    """
    Classify a batch of PDFs and return IDs to mark for deletion.

    Uses ThreadPoolExecutor when workers > 1 to parallelize S3 streaming
    and PDF classification.  DB writes stay on the main thread.

    Args:
        work_items: List of (pdf_id, s3_key) tuples -- plain scalars, no ORM objects.
        organize_dir: Optional directory to organize files by classification
        workers: Number of threads for parallel classification (default: 1)
        session: Database session (required when CLASSIFICATION_SOURCE=gemini)

    Returns:
        Tuple of (pdf_ids_to_delete, classification_stats)
    """
    pdfs_to_delete = []
    classification_stats: Dict[str, int] = {dt.value: 0 for dt in DocumentType}
    classification_stats['ERROR'] = 0

    # Pre-fetch Gemini doc_types when in gemini mode
    gemini_lookup: Dict[UUID, list[str]] = {}
    if CLASSIFICATION_SOURCE == "gemini" and session is not None:
        for pdf_id, _ in work_items:
            doc_types = _lookup_gemini_doc_types(pdf_id, session)
            if doc_types is not None:
                gemini_lookup[pdf_id] = doc_types

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdf_classify") as executor:
        futures = {
            executor.submit(
                classify_single_pdf, pdf_id, s3_key, organize_dir,
                gemini_lookup.get(pdf_id),
            ): pdf_id
            for pdf_id, s3_key in work_items
        }

        for future in as_completed(futures):
            pdf_id, doc_type, is_valid, error = future.result()
            # doc_type may be a DocumentType enum or a string "ERROR"
            key = doc_type.value if isinstance(doc_type, DocumentType) else doc_type
            classification_stats[key] = classification_stats.get(key, 0) + 1
            if not is_valid:
                pdfs_to_delete.append(pdf_id)

    return pdfs_to_delete, classification_stats

def cascade_soft_delete(pdf_ids: List[UUID], session, dry_run: bool = False) -> Dict[str, int]:
    """
    Cascade soft deletes across all three tables with the same timestamp.

    Deletion order:
    1. pdf_extraction_queue (reason: 'not_invoice_nor_credit')
    2. model_extracted_data (reason: 'parent_pdf_not_invoice')
    3. email_download_queue (reason: 'all_pdfs_not_invoices') - ONLY if ALL PDFs are deleted

    Args:
        pdf_ids: List of PDF IDs (UUIDs) to soft delete
        session: Database session
        dry_run: If True, don't actually update

    Returns:
        Dict with counts: {'pdfs': n, 'extracted_data': n, 'emails': n}
    """
    if not pdf_ids:
        return {'pdfs': 0, 'extracted_data': 0, 'emails': 0}

    # Convert UUIDs to strings for SQL
    pdf_id_strings = [str(pid) for pid in pdf_ids]

    if dry_run:
        # In dry-run mode, estimate the cascade impact
        logger.info(f"DRY-RUN: Would cascade soft-delete for {len(pdf_ids)} PDFs")

        # Count model_extracted_data that would be affected
        # Note: Use \: to escape :: cast syntax for SQLAlchemy text()
        count_med_sql = r"""
        SELECT COUNT(*) FROM raw.model_extracted_data
        WHERE pdf_extraction_queue_id = ANY(:pdf_ids\:\:uuid[])
        AND deleted_at IS NULL
        """
        med_count = session.execute(text(count_med_sql), {'pdf_ids': pdf_id_strings}).scalar()

        # Count emails that would be fully deleted (all PDFs deleted)
        count_emails_sql = r"""
        SELECT COUNT(DISTINCT eq.id)
        FROM raw.email_download_queue eq
        INNER JOIN raw.pdf_extraction_queue peq ON peq.email_queue_id = eq.id
        WHERE peq.id = ANY(:pdf_ids\:\:uuid[])
        AND eq.deleted_at IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM raw.pdf_extraction_queue other_peq
            WHERE other_peq.email_queue_id = eq.id
            AND other_peq.deleted_at IS NULL
            AND other_peq.id != ALL(:pdf_ids\:\:uuid[])
        )
        """
        email_count = session.execute(text(count_emails_sql), {'pdf_ids': pdf_id_strings}).scalar()

        logger.info(f"DRY-RUN: Would soft-delete {len(pdf_ids)} PDFs, {med_count} extracted_data records, {email_count} emails")
        return {'pdfs': len(pdf_ids), 'extracted_data': med_count or 0, 'emails': email_count or 0}

    try:
        # Use a consistent timestamp for all tables
        now = datetime.now(timezone.utc)

        # 1. Soft delete PDFs
        # Note: Use \: to escape :: cast syntax for SQLAlchemy text()
        update_pdfs_sql = r"""
        UPDATE raw.pdf_extraction_queue
        SET deleted_at = :timestamp, deletion_reason = 'not_invoice_nor_credit'
        WHERE id = ANY(:pdf_ids\:\:uuid[])
        AND deleted_at IS NULL
        """
        pdf_result = session.execute(
            text(update_pdfs_sql),
            {'timestamp': now, 'pdf_ids': pdf_id_strings}
        )
        pdfs_deleted = pdf_result.rowcount

        # 2. Soft delete all model_extracted_data for those PDFs
        update_med_sql = r"""
        UPDATE raw.model_extracted_data
        SET deleted_at = :timestamp, deletion_reason = 'parent_pdf_not_invoice'
        WHERE pdf_extraction_queue_id = ANY(:pdf_ids\:\:uuid[])
        AND deleted_at IS NULL
        """
        med_result = session.execute(
            text(update_med_sql),
            {'timestamp': now, 'pdf_ids': pdf_id_strings}
        )
        med_deleted = med_result.rowcount

        # 3. Soft delete emails ONLY IF all their PDFs are now deleted
        update_emails_sql = r"""
        UPDATE raw.email_download_queue
        SET deleted_at = :timestamp, deletion_reason = 'all_pdfs_not_invoices'
        WHERE id IN (
            SELECT DISTINCT email_queue_id
            FROM raw.pdf_extraction_queue
            WHERE id = ANY(:pdf_ids\:\:uuid[])
            AND email_queue_id IS NOT NULL
        )
        AND deleted_at IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM raw.pdf_extraction_queue peq
            WHERE peq.email_queue_id = email_download_queue.id
            AND peq.deleted_at IS NULL
        )
        """
        email_result = session.execute(
            text(update_emails_sql),
            {'timestamp': now, 'pdf_ids': pdf_id_strings}
        )
        emails_deleted = email_result.rowcount

        session.commit()
        logger.info(f"Cascade soft-delete: {pdfs_deleted} PDFs, {med_deleted} extracted_data, {emails_deleted} emails")
        return {'pdfs': pdfs_deleted, 'extracted_data': med_deleted, 'emails': emails_deleted}

    except Exception as e:
        session.rollback()
        logger.error(f"Failed to cascade soft-delete: {e}")
        raise

def get_pdfs_to_process(session, limit: Optional[int] = None) -> List[PdfExtractionQueue]:
    """
    Query unique PDFs from pdf_extraction_queue that need classification.

    Only returns PDFs where deleted_at IS NULL (not yet classified/deleted).

    Args:
        session: Database session
        limit: Optional limit for testing

    Returns:
        List of PdfExtractionQueue records
    """
    query = session.query(PdfExtractionQueue).filter(
        PdfExtractionQueue.deleted_at.is_(None)
    )

    if limit:
        query = query.limit(limit)

    return query.all()

def print_verification_queries():
    """Print SQL queries for verifying the results across all three tables"""
    queries = [
        # PDF extraction queue
        ("Total PDFs", "SELECT COUNT(*) FROM raw.pdf_extraction_queue;"),
        ("Active PDFs", "SELECT COUNT(*) FROM raw.pdf_extraction_queue WHERE deleted_at IS NULL;"),
        ("Soft-deleted PDFs", "SELECT COUNT(*) FROM raw.pdf_extraction_queue WHERE deleted_at IS NOT NULL;"),
        ("PDFs by deletion reason", """
            SELECT deletion_reason, COUNT(*)
            FROM raw.pdf_extraction_queue
            WHERE deleted_at IS NOT NULL
            GROUP BY deletion_reason;
        """),
        # Model extracted data
        ("Total extracted_data", "SELECT COUNT(*) FROM raw.model_extracted_data;"),
        ("Active extracted_data", "SELECT COUNT(*) FROM raw.model_extracted_data WHERE deleted_at IS NULL;"),
        ("Soft-deleted extracted_data", "SELECT COUNT(*) FROM raw.model_extracted_data WHERE deleted_at IS NOT NULL;"),
        ("Extracted_data by deletion reason", """
            SELECT deletion_reason, COUNT(*)
            FROM raw.model_extracted_data
            WHERE deleted_at IS NOT NULL
            GROUP BY deletion_reason;
        """),
        # Email download queue
        ("Total emails", "SELECT COUNT(*) FROM raw.email_download_queue;"),
        ("Active emails", "SELECT COUNT(*) FROM raw.email_download_queue WHERE deleted_at IS NULL;"),
        ("Soft-deleted emails", "SELECT COUNT(*) FROM raw.email_download_queue WHERE deleted_at IS NOT NULL;"),
        ("Emails by deletion reason", """
            SELECT deletion_reason, COUNT(*)
            FROM raw.email_download_queue
            WHERE deleted_at IS NOT NULL
            GROUP BY deletion_reason;
        """),
        # Recent activity
        ("Recent PDF deletions (1h)", """
            SELECT COUNT(*)
            FROM raw.pdf_extraction_queue
            WHERE deleted_at >= NOW() - INTERVAL '1 hour';
        """)
    ]

    logger.info("=== VERIFICATION QUERIES ===")
    for name, query in queries:
        logger.info(f"{name}:")
        logger.info(f"  {query.strip()}")
        logger.info("")

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Classify documents and soft-delete non-invoices/credits",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes (dry run)
  python scripts/classify_and_soft_delete_non_invoices.py --dry-run

  # Process first 100 records for testing with file organization
  python scripts/classify_and_soft_delete_non_invoices.py --limit 100 --dry-run --organize-files ./classified_files

  # Full run with larger batch size
  python scripts/classify_and_soft_delete_non_invoices.py --batch-size 500 --yes

  # Organize files by classification for manual assessment
  python scripts/classify_and_soft_delete_non_invoices.py --dry-run --organize-files ./assessment_folders
        """
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without updating database'
    )

    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Records to process per batch (default: 1000)'
    )

    parser.add_argument(
        '--limit',
        type=int,
        help='Limit total records to process (for testing)'
    )

    parser.add_argument(
        '--yes',
        action='store_true',
        help='Skip confirmation prompt'
    )

    parser.add_argument(
        '--organize-files',
        help='Organize classified files into folders by type (Invoice/Credit/Statement/Other/Error) for manual assessment'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=8,
        help='Number of threads for parallel S3 download + classification (default: 8, use 1 for sequential/debug)'
    )

    return parser.parse_args()

def main():
    """Main execution"""
    args = parse_arguments()

    logger.info("=== DOCUMENT CLASSIFICATION WITH CASCADING SOFT DELETES ===")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Limit: {args.limit or 'None'}")
    logger.info(f"Workers: {args.workers}")
    logger.info(f"Classification source: {CLASSIFICATION_SOURCE}")
    logger.info(f"Organize files: {args.organize_files or 'Disabled'}")

    # Pre-initialize S3 client before thread pool starts (eliminates init race)
    get_s3_client()

    # Create organize directory if specified
    if args.organize_files:
        organize_path = Path(args.organize_files)
        organize_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created organize directory: {organize_path}")

    with db_context() as session:
        # Get PDFs to process (unique PDFs from pdf_extraction_queue)
        logger.info("Querying PDFs to process from pdf_extraction_queue...")
        pdfs = get_pdfs_to_process(session, args.limit)

        if not pdfs:
            logger.info("No PDFs found to process")
            return

        logger.info(f"Found {len(pdfs)} PDFs to process")

        # Extract scalars before entering the thread pool -- ORM objects
        # are not safe to share across threads.
        work_items: List[Tuple[UUID, str]] = [(pdf.id, pdf.s3_key) for pdf in pdfs]

        # Confirmation prompt
        if not args.dry_run and not args.yes:
            response = input(f"\nProcess {len(work_items)} PDFs with cascading deletes? (y/N): ")
            if response.lower() != 'y':
                logger.info("Operation cancelled")
                return

        # Process in batches
        total_stats: Dict[str, int] = {dt.value: 0 for dt in DocumentType}
        total_stats['ERROR'] = 0
        total_cascade_stats = {'pdfs': 0, 'extracted_data': 0, 'emails': 0}
        batch_count = 0
        total_items = len(work_items)

        with timed("full_classification", logger):
            for i in range(0, total_items, args.batch_size):
                batch_count += 1
                batch_items = work_items[i:i + args.batch_size]

                logger.info(f"Processing batch {batch_count}/{(total_items + args.batch_size - 1) // args.batch_size}: "
                           f"PDFs {i+1} to {min(i + args.batch_size, total_items)}")

                with timed(f"batch_{batch_count}", logger):
                    # Classify batch of PDFs
                    pdfs_to_delete, batch_stats = classify_pdfs_batch(
                        batch_items,
                        args.organize_files,
                        workers=args.workers,
                        session=session,
                    )

                    # Update classification statistics
                    for key, value in batch_stats.items():
                        total_stats[key] = total_stats.get(key, 0) + value

                    # Cascade soft-delete across all tables
                    cascade_stats = cascade_soft_delete(pdfs_to_delete, session, args.dry_run)
                    for key in total_cascade_stats:
                        total_cascade_stats[key] += cascade_stats[key]

                    logger.info(f"Batch {batch_count} complete: classified {len(batch_items)} PDFs, "
                               f"marked {len(pdfs_to_delete)} for cascading deletion")

    # Final summary
    logger.info("=== FINAL SUMMARY ===")
    logger.info(f"Total PDFs processed: {total_items}")
    logger.info(f"Classification breakdown:")
    for doc_type, count in total_stats.items():
        logger.info(f"  {doc_type}: {count}")
    logger.info(f"Cascading soft-deletes:")
    logger.info(f"  PDFs deleted: {total_cascade_stats['pdfs']}")
    logger.info(f"  Extracted data records deleted: {total_cascade_stats['extracted_data']}")
    logger.info(f"  Emails deleted (all PDFs removed): {total_cascade_stats['emails']}")

    if args.organize_files:
        organize_path = Path(args.organize_files)
        logger.info("=== FILE ORGANIZATION SUMMARY ===")
        for doc_type in ['INVOICE', 'CREDIT', 'STATEMENT', 'UNKNOWN', 'ERROR']:
            type_folder = organize_path / doc_type
            if type_folder.exists():
                file_count = len(list(type_folder.glob('*')))
                logger.info(f"{doc_type} folder: {file_count} files in {type_folder}")

    if args.dry_run:
        logger.info("*** DRY RUN COMPLETE - NO CHANGES MADE ***")
    else:
        logger.info("*** CASCADING SOFT DELETE COMPLETE ***")
        print_verification_queries()

if __name__ == "__main__":
    main()
