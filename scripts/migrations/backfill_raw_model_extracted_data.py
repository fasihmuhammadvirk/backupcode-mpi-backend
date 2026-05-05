"""
Backfill raw.model_extracted_data from public.model_extracted_data

Phase 2 of the model_extracted_data refactor.
See docs/architecture/model_extracted_data_refactor_plan.md

Strategy:
1. Group by (s3_file_key, pdf_extraction_queue_id, email_queue_id, model_name, prompt_hash, extracted_at) to get unique extractions
2. Take the first row's raw_data (it's identical across all rows in the group)
3. Aggregate validation metrics (prefer 'model_approved' status, max validation_score)
4. Insert into raw.model_extracted_data
5. Verify data integrity

Usage:
    python scripts/migrations/backfill_raw_model_extracted_data.py
    python scripts/migrations/backfill_raw_model_extracted_data.py --dry-run
    python scripts/migrations/backfill_raw_model_extracted_data.py --verify-only
"""
import os
import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / '.env')

# Database connection parameters
db_params = {
    'dbname': os.getenv("POSTGRES_DB", "mpi_backend"),
    'user': os.getenv("POSTGRES_USERNAME", "postgres"),
    'password': os.getenv("POSTGRES_PASSWORD", ""),
    'host': os.getenv("POSTGRES_HOST", "localhost"),
    'port': os.getenv("POSTGRES_PORT", "5432")
}


def connect_to_db():
    """Establish a connection to the PostgreSQL database."""
    try:
        connection = psycopg2.connect(**db_params)
        logger.info("Database connection established successfully.")
        return connection
    except Exception as e:
        logger.exception(f"Error: Unable to connect to the database. {e}")
        return None


# Main backfill SQL - aggregates denormalized rows into single extraction records
BACKFILL_SQL = """
INSERT INTO raw.model_extracted_data (
    id,
    s3_file_key,
    pdf_extraction_queue_id,
    email_queue_id,
    model_name,
    prompt_hash,
    status,
    validation_score,
    confidence_score,
    raw_data,
    extracted_at,
    deleted_at,
    deletion_reason
)
SELECT
    gen_random_uuid() AS id,
    s3_file_key,
    pdf_extraction_queue_id,
    email_queue_id,
    model_name,
    prompt_hash,
    -- Take 'model_approved' if any row has it, else first status by row id
    CASE
        WHEN bool_or(status = 'model_approved') THEN 'model_approved'
        ELSE (array_agg(status ORDER BY id))[1]
    END AS status,
    -- Take max validation/confidence scores
    MAX(validation_score) AS validation_score,
    MAX(confidence_score) AS confidence_score,
    -- Take raw_data from first row (they're all identical per extraction group)
    (array_agg(raw_data ORDER BY id))[1] AS raw_data,
    extracted_at,
    -- If any row is deleted, mark the extraction as deleted (take latest deletion)
    MAX(deleted_at) AS deleted_at,
    -- Take deletion reason from most recently deleted row
    (array_agg(deletion_reason ORDER BY deleted_at DESC NULLS LAST))[1] AS deletion_reason
FROM public.model_extracted_data
WHERE raw_data IS NOT NULL
GROUP BY
    s3_file_key,
    pdf_extraction_queue_id,
    email_queue_id,
    model_name,
    prompt_hash,
    extracted_at
ORDER BY extracted_at
ON CONFLICT ON CONSTRAINT uq_med_raw_extraction_key DO NOTHING
"""

# Count unique extractions in source table
# Must match the GROUP BY columns in BACKFILL_SQL for accurate row count prediction
COUNT_SOURCE_EXTRACTIONS_SQL = """
SELECT COUNT(DISTINCT (s3_file_key, pdf_extraction_queue_id, email_queue_id, model_name, prompt_hash, extracted_at)) AS unique_extractions
FROM public.model_extracted_data
WHERE raw_data IS NOT NULL
"""

# Count total rows in source table
COUNT_SOURCE_ROWS_SQL = """
SELECT COUNT(*) AS total_rows
FROM public.model_extracted_data
WHERE raw_data IS NOT NULL
"""

# Count rows in target table
COUNT_TARGET_SQL = """
SELECT COUNT(*) AS total_rows FROM raw.model_extracted_data
"""

# Verification: Sample line item counts match
VERIFY_LINE_ITEM_COUNTS_SQL = """
WITH source_counts AS (
    -- Count line items per extraction (excluding tax records)
    SELECT
        s3_file_key,
        model_name,
        extracted_at,
        COUNT(*) FILTER (WHERE description != 'Tax') AS line_count
    FROM public.model_extracted_data
    WHERE raw_data IS NOT NULL
    GROUP BY s3_file_key, model_name, extracted_at
    LIMIT 100
),
target_counts AS (
    -- Count line items from raw_data JSONB
    SELECT
        s3_file_key,
        model_name,
        extracted_at,
        COALESCE(jsonb_array_length(raw_data->'line_items'), 0) AS line_count
    FROM raw.model_extracted_data
)
SELECT
    s.s3_file_key,
    s.line_count AS source_line_count,
    t.line_count AS target_line_count,
    CASE
        WHEN s.line_count = t.line_count THEN 'MATCH'
        ELSE 'MISMATCH'
    END AS status
FROM source_counts s
JOIN target_counts t USING (s3_file_key, model_name, extracted_at)
WHERE s.line_count != t.line_count
LIMIT 20
"""

# Verification: Check status distribution
VERIFY_STATUS_DISTRIBUTION_SQL = """
SELECT status, COUNT(*) AS count
FROM raw.model_extracted_data
GROUP BY status
ORDER BY count DESC
"""

# Verification: Check records per month
VERIFY_MONTHLY_DISTRIBUTION_SQL = """
SELECT
    DATE_TRUNC('month', extracted_at) AS month,
    COUNT(*) AS count
FROM raw.model_extracted_data
GROUP BY DATE_TRUNC('month', extracted_at)
ORDER BY month DESC
LIMIT 12
"""


def get_source_stats(cursor) -> dict:
    """Get statistics from the source table."""
    cursor.execute(COUNT_SOURCE_EXTRACTIONS_SQL)
    unique_extractions = cursor.fetchone()[0]

    cursor.execute(COUNT_SOURCE_ROWS_SQL)
    total_rows = cursor.fetchone()[0]

    return {
        'unique_extractions': unique_extractions,
        'total_rows': total_rows,
        'dedup_ratio': total_rows / unique_extractions if unique_extractions > 0 else 0
    }


def get_target_count(cursor) -> int:
    """Get row count from the target table."""
    cursor.execute(COUNT_TARGET_SQL)
    return cursor.fetchone()[0]


def run_backfill(dry_run: bool = False) -> bool:
    """
    Execute the backfill from public to raw schema.

    Args:
        dry_run: If True, show what would be done without executing.

    Returns:
        True if successful, False otherwise.
    """
    connection = connect_to_db()
    if connection is None:
        return False

    cursor = connection.cursor()

    try:
        # Get source statistics
        logger.info("Analyzing source table...")
        source_stats = get_source_stats(cursor)
        logger.info(f"Source table statistics:")
        logger.info(f"  Total rows: {source_stats['total_rows']:,}")
        logger.info(f"  Unique extractions: {source_stats['unique_extractions']:,}")
        logger.info(f"  Deduplication ratio: {source_stats['dedup_ratio']:.2f}x")

        # Get current target count
        target_before = get_target_count(cursor)
        logger.info(f"Target table current rows: {target_before:,}")

        if dry_run:
            logger.info("DRY RUN - Would insert approximately "
                       f"{source_stats['unique_extractions']:,} rows")
            return True

        # Execute backfill
        logger.info("Starting backfill...")
        start_time = datetime.now()
        cursor.execute(BACKFILL_SQL)
        rows_inserted = cursor.rowcount
        connection.commit()
        elapsed = (datetime.now() - start_time).total_seconds()

        # Get final target count
        target_after = get_target_count(cursor)

        logger.info("=" * 60)
        logger.info("Backfill Summary:")
        logger.info(f"  Source rows (total):           {source_stats['total_rows']:,}")
        logger.info(f"  Unique extractions (expected): {source_stats['unique_extractions']:,}")
        logger.info(f"  Rows inserted:                 {rows_inserted:,}")
        logger.info(f"  Target rows after:             {target_after:,}")
        logger.info(f"  Time elapsed:                  {elapsed:.2f}s")
        logger.info("=" * 60)

        # Check for count mismatch
        if source_stats['unique_extractions'] != target_after:
            logger.warning(
                f"Count mismatch: expected {source_stats['unique_extractions']:,}, "
                f"got {target_after:,}. Some may have been skipped due to ON CONFLICT."
            )
        else:
            logger.info("SUCCESS: All unique extractions migrated successfully!")

        return True

    except Exception as e:
        logger.exception(f"Error during backfill: {e}")
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()


def verify_data_integrity() -> bool:
    """
    Verify that raw_data in new table can produce same line items.

    Returns:
        True if verification passed, False if mismatches found.
    """
    connection = connect_to_db()
    if connection is None:
        return False

    cursor = connection.cursor(cursor_factory=RealDictCursor)

    try:
        logger.info("Running data integrity verification...")

        # Check line item counts
        logger.info("Verifying line item counts (sample)...")
        cursor.execute(VERIFY_LINE_ITEM_COUNTS_SQL)
        mismatches = cursor.fetchall()

        if mismatches:
            logger.error(f"Found {len(mismatches)} line item count mismatches!")
            for row in mismatches[:5]:
                logger.error(
                    f"  {row['s3_file_key']}: "
                    f"source={row['source_line_count']}, "
                    f"target={row['target_line_count']}"
                )
            return False
        else:
            logger.info("  Line item counts: PASSED")

        # Check status distribution
        logger.info("Status distribution in target table:")
        cursor.execute(VERIFY_STATUS_DISTRIBUTION_SQL)
        for row in cursor.fetchall():
            logger.info(f"  {row['status']}: {row['count']:,}")

        # Check monthly distribution
        logger.info("Monthly distribution in target table:")
        cursor.execute(VERIFY_MONTHLY_DISTRIBUTION_SQL)
        for row in cursor.fetchall():
            month_str = row['month'].strftime('%Y-%m') if row['month'] else 'NULL'
            logger.info(f"  {month_str}: {row['count']:,}")

        logger.info("Data integrity verification PASSED!")
        return True

    except Exception as e:
        logger.exception(f"Error during verification: {e}")
        return False
    finally:
        cursor.close()
        connection.close()


def main():
    parser = argparse.ArgumentParser(
        description='Backfill raw.model_extracted_data from public.model_extracted_data'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without executing'
    )
    parser.add_argument(
        '--verify-only',
        action='store_true',
        help='Only run verification, skip backfill'
    )
    parser.add_argument(
        '--skip-verify',
        action='store_true',
        help='Skip verification after backfill'
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Backfill raw.model_extracted_data")
    logger.info("=" * 60)

    if args.verify_only:
        success = verify_data_integrity()
    else:
        success = run_backfill(dry_run=args.dry_run)

        if success and not args.dry_run and not args.skip_verify:
            success = verify_data_integrity()

    if success:
        logger.info("Backfill completed successfully!")
        sys.exit(0)
    else:
        logger.error("Backfill failed or verification errors found.")
        sys.exit(1)


if __name__ == "__main__":
    main()
