"""
Restore soft-deleted records that were deleted with deletion_reason='no_vendor_mapping'.

This script reverses the cascading soft deletes performed by soft_delete_unmapped_vendors.py,
but ONLY for emails whose sender now matches an active sender_pattern in
analytics.email_vendor_mapping. Emails that still have no active mapping stay deleted.

Cascade restore:
1. email_download_queue  - deletion_reason='no_vendor_mapping' AND sender matches active mapping
2. pdf_extraction_queue  - deletion_reason='parent_email_deleted' linked to restored emails
3. model_extracted_data  - deletion_reason IN ('parent_pdf_deleted','supplier_not_supported') linked to restored PDFs

Usage:
    python restore_no_vendor_mapping.py --dry-run  # Preview counts
    python restore_no_vendor_mapping.py --apply     # Execute restore
"""
import argparse
import logging
from psycopg2.extras import RealDictCursor
from db_utils import connect_to_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def find_emails_to_restore(cursor) -> tuple[list, int]:
    """
    Find emails soft-deleted with deletion_reason='no_vendor_mapping'
    whose sender NOW matches an active sender_pattern in email_vendor_mapping.

    Uses the same LIKE pattern matching as the dbt model:
        LOWER(sender) LIKE '%' || LOWER(sender_pattern)

    Returns (restorable_emails, skipped_count).
    """
    # All no_vendor_mapping emails
    cursor.execute("""
        SELECT edq.id as email_queue_id, edq.sender
        FROM raw.email_download_queue edq
        WHERE edq.deleted_at IS NOT NULL
          AND edq.deletion_reason = 'no_vendor_mapping'
    """)
    all_deleted = cursor.fetchall()

    if not all_deleted:
        return [], 0

    # Filter to only those whose sender now matches an active mapping
    cursor.execute("""
        SELECT edq.id as email_queue_id, edq.sender
        FROM raw.email_download_queue edq
        WHERE edq.deleted_at IS NOT NULL
          AND edq.deletion_reason = 'no_vendor_mapping'
          AND EXISTS (
              SELECT 1 FROM analytics.email_vendor_mapping evm
              WHERE LOWER(edq.sender) LIKE '%%' || LOWER(evm.sender_pattern)
                AND evm.is_active = TRUE
          )
    """)
    restorable = cursor.fetchall()

    skipped = len(all_deleted) - len(restorable)
    if skipped > 0:
        logger.info(f"Skipping {skipped} emails still without an active vendor mapping")

    return restorable, skipped


def find_pdfs_to_restore(cursor, email_ids: list) -> list:
    """Find PDFs linked to the given emails, deleted with 'parent_email_deleted'."""
    if not email_ids:
        return []

    cursor.execute("""
        SELECT id as pdf_queue_id
        FROM raw.pdf_extraction_queue
        WHERE email_queue_id = ANY(%s::uuid[])
          AND deleted_at IS NOT NULL
          AND deletion_reason = 'parent_email_deleted'
    """, (email_ids,))
    return cursor.fetchall()


def find_extracted_data_to_restore(cursor, pdf_ids: list) -> list:
    """Find extracted data linked to the given PDFs, deleted as cascade or unsupported."""
    if not pdf_ids:
        return []

    cursor.execute("""
        SELECT id as extracted_data_id
        FROM raw.model_extracted_data
        WHERE pdf_extraction_queue_id = ANY(%s::uuid[])
          AND deleted_at IS NOT NULL
          AND deletion_reason IN ('parent_pdf_deleted', 'supplier_not_supported')
    """, (pdf_ids,))
    return cursor.fetchall()


def run_restore(dry_run: bool = True):
    """
    Restore soft-deleted 'no_vendor_mapping' records across the pipeline.

    Restore order (bottom-up):
    1. Find emails, PDFs, extracted data to restore
    2. Restore extracted data first, then PDFs, then emails
    """
    conn = connect_to_db()
    if not conn:
        raise RuntimeError("Failed to connect to database")

    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        logger.info("=" * 60)
        logger.info(f"Starting restore of no_vendor_mapping records {'[DRY RUN]' if dry_run else ''}")
        logger.info("=" * 60)

        # Step 1: Find emails to restore (only those with active vendor mapping)
        logger.info("\n--- Step 1: Find emails (no_vendor_mapping + active sender_pattern) ---")
        emails, skipped_emails = find_emails_to_restore(cursor)
        email_ids = [e['email_queue_id'] for e in emails]
        logger.info(f"Found {len(emails)} emails to restore")

        # Step 2: Find PDFs linked to those emails
        logger.info("\n--- Step 2: Find PDFs (deletion_reason='parent_email_deleted') ---")
        pdfs = find_pdfs_to_restore(cursor, email_ids)
        pdf_ids = [p['pdf_queue_id'] for p in pdfs]
        logger.info(f"Found {len(pdfs)} PDFs to restore")

        # Step 3: Find extracted data linked to those PDFs
        logger.info("\n--- Step 3: Find extracted data (cascade/unsupported) ---")
        extracted = find_extracted_data_to_restore(cursor, pdf_ids)
        extracted_ids = [r['extracted_data_id'] for r in extracted]
        logger.info(f"Found {len(extracted)} extracted data records to restore")

        # Summary before action
        logger.info("\n" + "=" * 60)
        logger.info("Restore summary:")
        logger.info(f"  - Emails to restore:  {len(email_ids)}")
        logger.info(f"  - Emails skipped:     {skipped_emails} (no active vendor mapping)")
        logger.info(f"  - PDFs:               {len(pdf_ids)}")
        logger.info(f"  - Extracted data:     {len(extracted_ids)}")
        logger.info("=" * 60)

        if dry_run:
            logger.info("[DRY RUN] No changes made to database")
            return

        # Restore bottom-up: extracted data -> PDFs -> emails
        if extracted_ids:
            cursor.execute("""
                UPDATE raw.model_extracted_data
                SET deleted_at = NULL, deletion_reason = NULL
                WHERE id = ANY(%s::uuid[])
            """, (extracted_ids,))
            logger.info(f"Restored {len(extracted_ids)} extracted data records")

        if pdf_ids:
            cursor.execute("""
                UPDATE raw.pdf_extraction_queue
                SET deleted_at = NULL, deletion_reason = NULL
                WHERE id = ANY(%s::uuid[])
            """, (pdf_ids,))
            logger.info(f"Restored {len(pdf_ids)} PDFs")

        if email_ids:
            cursor.execute("""
                UPDATE raw.email_download_queue
                SET deleted_at = NULL, deletion_reason = NULL
                WHERE id = ANY(%s::uuid[])
            """, (email_ids,))
            logger.info(f"Restored {len(email_ids)} emails")

        conn.commit()
        logger.info("Changes committed to database")

    except Exception as e:
        logger.error(f"Error during restore: {e}")
        conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='Restore soft-deleted records with deletion_reason=no_vendor_mapping'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview counts without making changes'
    )
    group.add_argument(
        '--apply',
        action='store_true',
        help='Execute the restore and commit changes'
    )
    args = parser.parse_args()

    run_restore(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
