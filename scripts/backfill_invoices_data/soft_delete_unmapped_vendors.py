"""
Soft delete records for unmapped or inactive email vendors.

This script performs cascading soft deletes across the data pipeline:
1. email_download_queue - emails with inactive vendor mappings OR no mapping
2. pdf_extraction_queue - records linked to soft-deleted emails
3. model_extracted_data - records linked to soft-deleted PDFs (cascade)
4. model_extracted_data - records from unsupported suppliers (direct referential check)

Step 4 catches records that may have been missed by the cascade approach,
using the FK chain: extracted_data -> pdf_queue -> email_queue -> sender.

Usage:
    python soft_delete_unmapped_vendors.py --dry-run  # Preview changes
    python soft_delete_unmapped_vendors.py            # Execute soft deletes
"""
import argparse
import logging
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor
from db_utils import connect_to_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_emails_to_soft_delete(cursor) -> list:
    """
    Find emails that should be soft deleted because:
    - They have no vendor mapping at all
    - They have no ACTIVE vendor mapping (guards against multiple mappings per sender)

    Returns list of email_queue_ids and the deletion reason.

    Note: email_vendor_mapping lacks a UNIQUE constraint on sender_email, so multiple
    rows per sender could exist. This query explicitly checks for absence of any
    active mapping rather than presence of an inactive one.
    """
    query = """
        SELECT
            edq.id as email_queue_id,
            edq.sender,
            CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM analytics.email_vendor_mapping evm
                    WHERE evm.sender_email = edq.sender
                ) THEN 'no_vendor_mapping'
                ELSE 'inactive_vendor_mapping'
            END as deletion_reason
        FROM raw.email_download_queue edq
        WHERE edq.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM analytics.email_vendor_mapping evm
              WHERE evm.sender_email = edq.sender
                AND evm.is_active = TRUE
          )
    """
    cursor.execute(query)
    return cursor.fetchall()


def soft_delete_emails(cursor, dry_run: bool = True) -> list:
    """
    Soft delete emails with inactive or no vendor mapping.

    Returns list of email_queue_ids that were (or would be) deleted.
    """
    emails = get_emails_to_soft_delete(cursor)

    if not emails:
        logger.info("No emails to soft delete")
        return []

    # Group by deletion reason for logging
    no_mapping = [e for e in emails if e['deletion_reason'] == 'no_vendor_mapping']
    inactive = [e for e in emails if e['deletion_reason'] == 'inactive_vendor_mapping']

    logger.info(f"Found {len(emails)} emails to soft delete:")
    logger.info(f"  - {len(no_mapping)} with no vendor mapping")
    logger.info(f"  - {len(inactive)} with inactive vendor mapping")

    # Extract all email IDs for cascading
    all_email_ids = [e['email_queue_id'] for e in emails]

    if dry_run:
        logger.info("[DRY RUN] Would soft delete emails")
        return all_email_ids

    now = datetime.now(timezone.utc)

    # Soft delete emails with no mapping
    if no_mapping:
        email_ids = [e['email_queue_id'] for e in no_mapping]
        cursor.execute("""
            UPDATE raw.email_download_queue
            SET deleted_at = %s, deletion_reason = 'no_vendor_mapping'
            WHERE id = ANY(%s::uuid[])
        """, (now, email_ids))
        logger.info(f"Soft deleted {len(no_mapping)} emails (no vendor mapping)")

    # Soft delete emails with inactive mapping
    if inactive:
        email_ids = [e['email_queue_id'] for e in inactive]
        cursor.execute("""
            UPDATE raw.email_download_queue
            SET deleted_at = %s, deletion_reason = 'inactive_vendor_mapping'
            WHERE id = ANY(%s::uuid[])
        """, (now, email_ids))
        logger.info(f"Soft deleted {len(inactive)} emails (inactive vendor mapping)")

    return all_email_ids


def soft_delete_pdfs(cursor, email_ids: list, dry_run: bool = True) -> list:
    """
    Soft delete PDFs linked to the given email IDs.

    Returns list of pdf_queue_ids that were (or would be) deleted.
    """
    if not email_ids:
        logger.info("No PDFs to soft delete (no parent emails)")
        return []

    query = """
        SELECT peq.id as pdf_queue_id
        FROM raw.pdf_extraction_queue peq
        WHERE peq.email_queue_id = ANY(%s::uuid[])
          AND peq.deleted_at IS NULL
    """
    cursor.execute(query, (email_ids,))
    pdfs = cursor.fetchall()

    if not pdfs:
        logger.info("No PDFs to soft delete")
        return []

    pdf_ids = [p['pdf_queue_id'] for p in pdfs]
    logger.info(f"Found {len(pdfs)} PDFs linked to emails being deleted")

    if dry_run:
        logger.info("[DRY RUN] Would soft delete PDFs")
        return pdf_ids

    now = datetime.now(timezone.utc)

    cursor.execute("""
        UPDATE raw.pdf_extraction_queue
        SET deleted_at = %s, deletion_reason = 'parent_email_deleted'
        WHERE id = ANY(%s::uuid[])
    """, (now, pdf_ids))

    logger.info(f"Soft deleted {len(pdfs)} PDFs")
    return pdf_ids


def soft_delete_extracted_data(cursor, pdf_ids: list, dry_run: bool = True) -> int:
    """
    Soft delete model_extracted_data linked to the given PDF IDs.

    Returns count of records that were (or would be) deleted.
    """
    if not pdf_ids:
        logger.info("No extracted data records to soft delete (no parent PDFs)")
        return 0

    query = """
        SELECT med.id as extracted_data_id
        FROM raw.model_extracted_data med
        WHERE med.pdf_extraction_queue_id = ANY(%s::uuid[])
          AND med.deleted_at IS NULL
    """
    cursor.execute(query, (pdf_ids,))
    records = cursor.fetchall()

    if not records:
        logger.info("No extracted data records to soft delete")
        return 0

    logger.info(f"Found {len(records)} extracted data records linked to PDFs being deleted")

    if dry_run:
        logger.info("[DRY RUN] Would soft delete extracted data records")
        return len(records)

    record_ids = [r['extracted_data_id'] for r in records]
    now = datetime.now(timezone.utc)

    cursor.execute("""
        UPDATE raw.model_extracted_data
        SET deleted_at = %s, deletion_reason = 'parent_pdf_deleted'
        WHERE id = ANY(%s::uuid[])
    """, (now, record_ids))

    logger.info(f"Soft deleted {len(records)} extracted data records")
    return len(records)


def soft_delete_extracted_data_unsupported_suppliers(cursor, dry_run: bool = True) -> int:
    """
    Directly soft delete raw.model_extracted_data records where the source
    email is not from a supported supplier.

    Uses referential chain: extracted_data -> pdf_queue -> email_queue -> sender

    This catches records that may have been missed by the cascade approach,
    such as when the email record exists but wasn't previously deleted.
    """
    query = """
        SELECT med.id as extracted_data_id
        FROM raw.model_extracted_data med
        JOIN raw.pdf_extraction_queue peq ON med.pdf_extraction_queue_id = peq.id
        JOIN raw.email_download_queue edq ON peq.email_queue_id = edq.id
        WHERE med.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM analytics.email_vendor_mapping evm
              WHERE evm.sender_email = edq.sender
                AND evm.is_active = TRUE
          )
    """
    cursor.execute(query)
    records = cursor.fetchall()

    if not records:
        logger.info("No extracted data records from unsupported suppliers to soft delete")
        return 0

    logger.info(f"Found {len(records)} extracted data records from unsupported suppliers")

    if dry_run:
        logger.info("[DRY RUN] Would soft delete extracted data records (unsupported suppliers)")
        return len(records)

    record_ids = [r['extracted_data_id'] for r in records]
    now = datetime.now(timezone.utc)

    cursor.execute("""
        UPDATE raw.model_extracted_data
        SET deleted_at = %s, deletion_reason = 'supplier_not_supported'
        WHERE id = ANY(%s::uuid[])
    """, (now, record_ids))

    logger.info(f"Soft deleted {len(records)} extracted data records (unsupported suppliers)")
    return len(records)


def run_cascading_soft_delete(dry_run: bool = True):
    """
    Execute cascading soft delete across the pipeline.

    Order matters:
    1. Emails (source of truth for vendor mapping)
    2. PDFs (linked to emails)
    3. Extracted data (linked to PDFs)
    """
    conn = connect_to_db()
    if not conn:
        raise RuntimeError("Failed to connect to database")

    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        logger.info("=" * 60)
        logger.info(f"Starting cascading soft delete {'[DRY RUN]' if dry_run else ''}")
        logger.info("=" * 60)

        # Step 1: Soft delete emails - returns list of email IDs
        logger.info("\n--- Step 1: Email Download Queue ---")
        email_ids = soft_delete_emails(cursor, dry_run)

        # Step 2: Soft delete PDFs linked to those emails - returns list of PDF IDs
        logger.info("\n--- Step 2: PDF Extraction Queue ---")
        pdf_ids = soft_delete_pdfs(cursor, email_ids, dry_run)

        # Step 3: Soft delete extracted data linked to those PDFs
        logger.info("\n--- Step 3: Model Extracted Data (cascade) ---")
        data_cascade_deleted = soft_delete_extracted_data(cursor, pdf_ids, dry_run)

        # Step 4: Direct extracted_data cleanup via referential chain
        # This catches records that may have been missed by the cascade approach
        logger.info("\n--- Step 4: Model Extracted Data (unsupported suppliers) ---")
        data_unsupported_deleted = soft_delete_extracted_data_unsupported_suppliers(cursor, dry_run)

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("Summary:")
        logger.info(f"  - Emails: {len(email_ids)}")
        logger.info(f"  - PDFs: {len(pdf_ids)}")
        logger.info(f"  - Extracted data (cascade): {data_cascade_deleted}")
        logger.info(f"  - Extracted data (unsupported suppliers): {data_unsupported_deleted}")
        logger.info("=" * 60)

        if not dry_run:
            conn.commit()
            logger.info("Changes committed to database")
        else:
            logger.info("[DRY RUN] No changes made to database")

    except Exception as e:
        logger.error(f"Error during soft delete: {e}")
        conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='Soft delete records for unmapped or inactive email vendors'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without making them'
    )
    args = parser.parse_args()

    run_cascading_soft_delete(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
