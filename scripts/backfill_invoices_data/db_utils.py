"""
Database utilities for invoice processing.

This module provides functions for connecting to PostgreSQL and managing
extracted invoice data in the database, including insertion and retrieval
operations.

Uses raw.model_extracted_data (normalized schema) - one row per extraction.
"""
import os
import datetime
import uuid
import psycopg2
from pathlib import Path
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor, Json
from psycopg2 import sql
from typing import Optional, Dict, Any, List
import re
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Validation status priority ordering, from worst to best.
# Used by get_worst_validation_status (SQL) and multi-invoice aggregation (Python).
# 'model_approved' is omitted because it is handled separately (all invoices must
# be model_approved for the aggregate to be model_approved).
VALIDATION_STATUS_PRIORITY = [
    'low_confidence',
    'human_review_required',
    'no_line_items_extracted',
    'high_confidence',
]

project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / '.env')

# Database connection parameters loaded from environment variables
db_params = {
    'dbname': os.getenv("POSTGRES_DB", "mpi_backend"),
    'user': os.getenv("POSTGRES_USERNAME", "postgres"),
    'password': os.getenv("POSTGRES_PASSWORD", ""),
    'host': os.getenv("POSTGRES_HOST", "localhost"),
    'port': os.getenv("POSTGRES_PORT", "5432")
}

def connect_to_db():
    """
    Establish a connection to the PostgreSQL database.
    
    Uses database parameters from environment variables (loaded from .env file):
    - POSTGRES_DB: Database name (default: "mpi_backend")
    - POSTGRES_USERNAME: Database user (default: "postgres")
    - POSTGRES_PASSWORD: Database password (default: "")
    - POSTGRES_HOST: Database host (default: "localhost")
    - POSTGRES_PORT: Database port (default: "5432")
    
    Returns:
        psycopg2.connection: Database connection object if successful, None otherwise.
    
    Note:
        Connection errors are logged but exceptions are caught and not raised.
        Callers should check for None return value.
    """
    try:
        connection = psycopg2.connect(**db_params)
        logger.info("Connection to the database established successfully.")
        return connection

    except Exception as e:
        logger.exception(f"Error: Unable to connect to the database. {e}")
        return None

  
def get_invoices():
    """
    Retrieve all invoices from the database.
    
    Fetches all records from the invoices table and returns them as a list
    of dictionaries where keys are column names.
    
    Returns:
        list or None: List of invoice dictionaries (RealDictRow objects) if
            invoices are found, None if no invoices exist or if an error occurs.
            Each dictionary contains all columns from the invoices table.
    
    Note:
        Uses RealDictCursor to return results as dictionaries rather than tuples.
        Database errors are logged and None is returned, but exceptions are
        not raised.
    """
    connection = connect_to_db()
    if connection is None:
        return None

    cursor = connection.cursor(cursor_factory=RealDictCursor)

    try:
        query = sql.SQL("SELECT * FROM invoices")

        cursor.execute(query)
        invoices = cursor.fetchall()
        if invoices:
            return invoices
        else:
            return None
    except Exception as e:
        logger.exception(f"Error fetching data: {e}")
        return None
    finally:
        cursor.close()
        connection.close()

def get_supplier_from_invoice(supplier_id: str) -> Optional[str]:
    """
    Retrieve supplier name from the database using supplier ID.
    
    Queries the suppliers table to find the supplier_name field for the given
    supplier ID.
    
    Args:
        supplier_id: UUID or identifier for the supplier in the database.
            Used to query the suppliers table WHERE id = supplier_id.
    
    Returns:
        Optional[str]: The supplier name (supplier_name field) from the suppliers
            table if found, None if supplier doesn't exist, database connection
            fails, or if an error occurs.
    
    Note:
        Database errors are logged and None is returned, but exceptions are
        not raised. Uses RealDictCursor to return results as dictionaries.
    """
    connection = connect_to_db()
    if connection is None:
        return None
    
    cursor = connection.cursor(cursor_factory=RealDictCursor)
    try:
        query = sql.SQL("""
            SELECT * from suppliers where id = %s
        """)
        cursor.execute(query, (supplier_id,))
        result = cursor.fetchone()
        return result['supplier_name'] if result else None
    except Exception as e:
        logger.exception(f"Error fetching supplier: {e}")
        return None
    finally:
        cursor.close()
        connection.close()
        
def _clean_currency(
    value, field_name: str = None, row_context: dict = None,
    file_path: str = None
) -> float:
    """
    Clean currency string and convert to float.
    
    This helper function normalizes currency values by removing dollar signs ($)
    and comma separators, then converts to float. Only legitimately empty/null
    values (pd.isna, empty strings, or just dots) return 0.0. Malformed/unparseable
    strings log a warning with context and raise ValueError to surface data issues
    instead of silently swallowing them.
    
    Args:
        value: The value to clean and convert. Can be int, float, string, or None.
            String values are expected to contain currency formatting (e.g., "$1,234.56").
        field_name: Optional field name for better error messages
            (e.g., 'Qty', 'Cost', 'Amount'). Included in error logs and messages.
        row_context: Optional dictionary containing row data for context in error
            messages. If provided, 'Item' and 'Description' fields are included
            in error logs to help identify problematic rows.
        file_path: Optional file path for context in error messages. Included in
            error logs and ValueError messages to help identify the source file.
    
    Returns:
        float: The cleaned currency value as a float. Returns 0.0 only for
            legitimately empty/null values (None, NaN, empty string, or string
            containing only dots/whitespace).
    
    Raises:
        ValueError: If the value is malformed/unparseable and cannot be converted
            to float. The error message includes the raw value, cleaned value,
            field name (if provided), and file path (if provided).
    
    Processing:
        1. NaN/None values -> 0.0
        2. Numeric values (int/float) -> converted to float directly
        3. String values -> stripped, then $ and commas removed
        4. Empty/whitespace-only strings -> 0.0
        5. Strings containing only dots -> 0.0
        6. Remaining strings -> converted to float, ValueError if conversion fails
    """
    
    if pd.isna(value):
        return 0.0
    
    if isinstance(value, (int, float)):
        return float(value)
    
    value_str = str(value).strip()
    if not value_str:
        return 0.0
    
    cleaned = re.sub(r'[$,]', '', value_str)
    
    # Check for legitimately empty values (empty or just dots)
    if not cleaned or cleaned == '.' or cleaned.replace('.', '').strip() == '':
        return 0.0
    
    try:
        return float(cleaned)
    except ValueError:
        # Build context information for the warning
        context_parts = []
        if field_name:
            context_parts.append(f"field='{field_name}'")
        if file_path:
            context_parts.append(f"file='{file_path}'")
        if row_context:
            # Include relevant row info (item number, description, etc.)
            item_info = row_context.get('Item', '')
            desc_info = row_context.get('Description', '')
            if item_info:
                context_parts.append(f"item='{item_info}'")
            if desc_info:
                if len(desc_info) > 50:
                    context_parts.append(f"description='{desc_info[:50]}...'")
                else:
                    context_parts.append(f"description='{desc_info}'")
        
        if context_parts:
            context_str = ", ".join(context_parts)
        else:
            context_str = "no context available"
        
        logger.warning(
            f"Failed to parse currency value: raw_value='{value_str}', "
            f"cleaned='{cleaned}', {context_str}"
        )
        
        error_msg = (
            f"Unable to parse currency value '{value_str}' "
            f"(cleaned: '{cleaned}')"
        )
        if field_name:
            error_msg += f" for field '{field_name}'"
        if file_path:
            error_msg += f" in file '{file_path}'"
        raise ValueError(error_msg)


def excel_to_dict(excel_path: str, supplier_name: str) -> dict:
    """
    Convert Excel file to list of dictionaries for Tabula extraction.
    
    This function reads an Excel file generated by Tabula PDF extraction and converts
    it into a standardized list of dictionaries matching the invoice line item format
    used by AI model extractions. Currency values are cleaned and converted to floats
    using _clean_currency().
    
    Args:
        excel_path: Path to the Excel file (.xlsx) to be read. The file should contain
            columns: Item, Description, Qty, Cost, Amount, Date, Ref NO, PO #,
            Customer Job, Bill, Vendor, Buyer.
        supplier_name: Name of the supplier/vendor. Used as a fallback value for
            the 'vendor' field if not present in the Excel file.
    
    Returns:
        list | None: List of dictionaries, each representing a line item with keys:
            - item: Item number/identifier (extracted from first word of Item column)
            - description: Product/service description
            - qty: Quantity as float (cleaned from Qty column)
            - cost: Unit cost as float (cleaned from Cost column)
            - amount: Total amount as float (cleaned from Amount column)
            - date: Invoice date as string
            - ref_no: Reference number as string
            - po_no: Purchase order number as string
            - customer_job: Customer job identifier as string
            - bill: Bill information as string
            - vendor: Vendor name (from Vendor column or supplier_name fallback)
            - buyer: Buyer information as string
        Returns None if the file cannot be read, parsed, or if an error occurs
        during processing.
    
    Raises:
        pd.errors.ParserError: If the Excel file cannot be parsed.
        FileNotFoundError: If the Excel file does not exist.
        KeyError: If required columns are missing from the Excel file.
        ValueError: If currency values cannot be parsed (raised by _clean_currency).
    
    Note:
        The 'item' field is extracted by taking the first word from the Item column.
        Currency fields (qty, cost, amount) are cleaned to remove $ and comma
        separators before conversion to float. Empty or null values are converted
        to 0.0. All string fields are converted to strings, with empty values
        becoming empty strings.
    """
    try:
        df = pd.read_excel(excel_path)
        df_list = df.to_dict(orient="records")
        data = []
        for item in df_list:
            item_str = str(item.get('Item', '')).strip()
            item_value = item_str.split()[0] if item_str else ''
            data.append({
                'item': item_value,
                'description': str(item.get('Description', '')),
                'qty': _clean_currency(
                    item.get('Qty', 0), field_name='Qty',
                    row_context=item, file_path=excel_path
                ),
                'cost': _clean_currency(
                    item.get('Cost', 0), field_name='Cost',
                    row_context=item, file_path=excel_path
                ),
                'amount': _clean_currency(
                    item.get('Amount', 0), field_name='Amount',
                    row_context=item, file_path=excel_path
                ),
                'date': str(item.get('Date', '')),
                'ref_no': str(item.get('Ref NO', '')),
                'po_no': str(item.get('PO #', '')),
                'customer_job': str(item.get('Customer Job', '')),
                'bill': str(item.get('Bill', '')),
                'vendor': str(item.get('Vendor', supplier_name)),
                'buyer': str(item.get('Buyer', ''))
            })
        return data
    except (
        pd.errors.ParserError, FileNotFoundError, KeyError, IndexError, ValueError
    ) as e:
        logger.exception(f"Failed to read Excel file {excel_path}: {e}")
        return None


def get_recent_pdfs_by_vendor(samples_per_vendor: int = 5) -> List[Dict[str, str]]:
    """
    Get the most recent PDF s3_keys grouped by vendor from active email mappings.

    Uses a window function to get N most recent PDFs per vendor based on
    the email_vendor_mapping table. Uses LOWER() on sender comparison
    because the CSV has duplicate case entries.

    Args:
        samples_per_vendor: Number of recent PDFs to return per vendor.

    Returns:
        List of dicts with keys: s3_key, vendor_name.
        Returns empty list on error or if no results found.
    """
    connection = connect_to_db()
    if connection is None:
        return []

    cursor = connection.cursor(cursor_factory=RealDictCursor)
    try:
        query = sql.SQL("""
            WITH ranked AS (
                SELECT
                    peq.s3_key,
                    evm.vendor_name,
                    peq.created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY evm.vendor_name
                        ORDER BY COALESCE(edq.email_date, peq.created_at) DESC
                    ) AS rn
                FROM raw.pdf_extraction_queue peq
                LEFT JOIN raw.email_download_queue edq ON peq.email_queue_id = edq.id
                JOIN analytics.email_vendor_mapping evm
                    ON LOWER(COALESCE(edq.sender, '')) LIKE '%%' || LOWER(evm.sender_pattern)
                WHERE peq.deleted_at IS NULL
                  AND evm.is_active = true
            )
            SELECT s3_key, vendor_name
            FROM ranked
            WHERE rn <= %s
            ORDER BY vendor_name, created_at DESC
        """)
        cursor.execute(query, (samples_per_vendor,))
        results = cursor.fetchall()
        return [dict(row) for row in results] if results else []
    except Exception as e:
        logger.exception(f"Error fetching recent PDFs by vendor: {e}")
        return []
    finally:
        cursor.close()
        connection.close()


def get_pdfs_by_ref_nos(ref_nos: List[str]) -> List[Dict[str, str]]:
    """
    Get PDF s3_keys for invoices matching the given ref_no values.

    Queries raw.model_extracted_data (JSONB raw_data->'ref_no') to find PDFs
    whose extracted ref_no matches any value in the list, then resolves the
    s3_key and vendor.

    Args:
        ref_nos: List of invoice reference numbers to look up.

    Returns:
        List of dicts with keys: s3_key, vendor_name.
        Returns empty list on error or if no results found.
    """
    if not ref_nos:
        return []

    connection = connect_to_db()
    if connection is None:
        return []

    cursor = connection.cursor(cursor_factory=RealDictCursor)
    try:
        query = sql.SQL("""
            SELECT DISTINCT ON (peq.s3_key)
                peq.s3_key,
                COALESCE(evm.vendor_name, rmed.raw_data->>'vendor') AS vendor_name
            FROM raw.model_extracted_data rmed
            JOIN raw.pdf_extraction_queue peq ON peq.id = rmed.pdf_extraction_queue_id
            LEFT JOIN raw.email_download_queue edq ON edq.id = peq.email_queue_id
            LEFT JOIN analytics.email_vendor_mapping evm
                ON (edq.sender IS NOT NULL AND LOWER(edq.sender) LIKE '%%' || LOWER(evm.sender_pattern))
            WHERE rmed.raw_data->>'ref_no' IN %s
              AND peq.deleted_at IS NULL
        """)
        cursor.execute(query, (tuple(ref_nos),))
        results = cursor.fetchall()
        return [dict(row) for row in results] if results else []
    except Exception as e:
        logger.exception(f"Error fetching PDFs by ref_nos: {e}")
        return []
    finally:
        cursor.close()
        connection.close()


def get_pdfs_by_s3_keys(s3_keys: List[str]) -> List[Dict[str, str]]:
    """
    Get PDF metadata for invoices matching the given S3 keys.

    Resolves vendor_name via email_vendor_mapping, falling back to
    'Unknown Vendor' if no mapping exists.

    Args:
        s3_keys: List of S3 keys to look up.

    Returns:
        List of dicts with keys: s3_key, vendor_name.
        Returns empty list on error or if no results found.
    """
    if not s3_keys:
        return []

    connection = connect_to_db()
    if connection is None:
        return []

    cursor = connection.cursor(cursor_factory=RealDictCursor)
    try:
        query = sql.SQL("""
            SELECT DISTINCT ON (peq.s3_key)
                peq.s3_key,
                COALESCE(evm.vendor_name, 'Unknown Vendor') AS vendor_name
            FROM raw.pdf_extraction_queue peq
            LEFT JOIN raw.email_download_queue edq ON edq.id = peq.email_queue_id
            LEFT JOIN analytics.email_vendor_mapping evm
                ON (edq.sender IS NOT NULL AND LOWER(edq.sender) LIKE '%%' || LOWER(evm.sender_pattern))
            WHERE peq.s3_key IN %s
              AND peq.deleted_at IS NULL
        """)
        cursor.execute(query, (tuple(s3_keys),))
        results = cursor.fetchall()
        return [dict(row) for row in results] if results else []
    except Exception as e:
        logger.exception("Error fetching PDFs by s3_keys")
        return []
    finally:
        cursor.close()
        connection.close()


def get_pending_extractions(limit: int = 50, include_validation_failed: bool = False) -> list[Dict]:
    """
    Get pending extraction items with email metadata for supplier detection.

    Queries the pdf_extraction_queue table for items with status='pending',
    joining with email_download_queue to get sender and subject for supplier
    detection. Excludes soft-deleted records (where deleted_at IS NOT NULL).

    Note: Items are auto-populated by DB trigger when downloads complete.

    Args:
        limit: Maximum number of items to return (default 50).
        include_validation_failed: If True, also return:
          - Items with status='validation_failed'
          - Items with status='completed' but latest extraction has bad validation

    Returns:
        List of dicts with keys: id, email_queue_id, s3_key, sender, subject, status.
        Returns empty list if no pending items or on error.
    """
    connection = connect_to_db()
    if connection is None:
        return []

    cursor = connection.cursor(cursor_factory=RealDictCursor)
    try:
        # NOTE: This order by split_part works for small records (<100k) but this needs to be optimized by
        # either creating a separate column or better indexing.
        if include_validation_failed:
            # Include: pending, validation_failed, AND completed with bad extraction status
            query = sql.SQL("""
                WITH latest_extraction_status AS (
                    -- Get the worst status from the latest extraction per queue item
                    SELECT DISTINCT ON (pdf_extraction_queue_id)
                        pdf_extraction_queue_id,
                        status AS extraction_status
                    FROM raw.model_extracted_data
                    ORDER BY pdf_extraction_queue_id, extracted_at DESC
                )
                SELECT pq.id, pq.email_queue_id, pq.s3_key, eq.sender, eq.subject, pq.status
                FROM raw.pdf_extraction_queue pq
                LEFT JOIN raw.email_download_queue eq ON eq.id = pq.email_queue_id
                LEFT JOIN latest_extraction_status les ON les.pdf_extraction_queue_id = pq.id
                WHERE pq.deleted_at IS NULL
                  AND (pq.status IN ('pending', 'validation_failed')
                       OR (pq.status = 'completed'
                           AND les.extraction_status IN ('low_confidence', 'human_review_required')))
                ORDER BY split_part(pq.s3_key, '/', 3) DESC, COALESCE(eq.email_date, pq.created_at) DESC
                LIMIT %s
                FOR UPDATE OF pq SKIP LOCKED
            """)
            cursor.execute(query, (limit,))
        else:
            # Original behavior: pending only
            query = sql.SQL("""
                SELECT pq.id, pq.email_queue_id, pq.s3_key, eq.sender, eq.subject, pq.status
                FROM raw.pdf_extraction_queue pq
                LEFT JOIN raw.email_download_queue eq ON eq.id = pq.email_queue_id
                WHERE pq.deleted_at IS NULL
                  AND pq.status = 'pending'
                ORDER BY split_part(pq.s3_key, '/', 3) DESC, COALESCE(eq.email_date, pq.created_at) DESC
                LIMIT %s
                FOR UPDATE OF pq SKIP LOCKED
            """)
            cursor.execute(query, (limit,))

        results = cursor.fetchall()
        return [dict(row) for row in results] if results else []
    except Exception as e:
        logger.exception(f"Error fetching pending extractions: {e}")
        return []
    finally:
        cursor.close()
        connection.close()


def claim_pending_extractions(limit: int = 50, include_validation_failed: bool = False) -> list[Dict]:
    """
    Atomically claim pending extraction items for processing.

    This function uses UPDATE...RETURNING with FOR UPDATE SKIP LOCKED to
    atomically select AND mark items as 'in_progress' in a single transaction.
    This prevents race conditions when running multiple instances.
    Excludes soft-deleted records (where deleted_at IS NOT NULL).

    Note: Items are auto-populated by DB trigger when downloads complete.

    Args:
        limit: Maximum number of items to claim (default 50).
        include_validation_failed: If True, also claim:
          - Items with status='validation_failed'
          - Items with status='completed' but latest extraction has bad validation

    Returns:
        List of dicts with keys: id, email_queue_id, s3_key, sender, subject, status.
        All returned items are now marked as 'in_progress'.
        Returns empty list if no pending items or on error.
    """
    connection = connect_to_db()
    if connection is None:
        return []

    cursor = connection.cursor(cursor_factory=RealDictCursor)
    try:
        if include_validation_failed:
            # Include: pending, validation_failed, AND completed with bad extraction status
            query = sql.SQL("""
                WITH candidates AS (
                    SELECT pq.id
                    FROM raw.pdf_extraction_queue pq
                    LEFT JOIN raw.email_download_queue eq ON eq.id = pq.email_queue_id
                    LEFT JOIN (
                        SELECT DISTINCT ON (pdf_extraction_queue_id)
                            pdf_extraction_queue_id,
                            status AS extraction_status
                        FROM raw.model_extracted_data
                        ORDER BY pdf_extraction_queue_id, extracted_at DESC
                    ) les ON les.pdf_extraction_queue_id = pq.id
                    WHERE pq.deleted_at IS NULL
                      AND (pq.status IN ('pending', 'validation_failed')
                           OR (pq.status = 'completed'
                               AND les.extraction_status IN ('low_confidence', 'human_review_required')))
                    ORDER BY COALESCE(eq.email_date, pq.created_at) DESC
                    LIMIT %s
                    FOR UPDATE OF pq SKIP LOCKED
                )
                UPDATE raw.pdf_extraction_queue pq
                SET status = 'in_progress'
                FROM candidates c
                WHERE pq.id = c.id
                RETURNING pq.id, pq.email_queue_id, pq.s3_key, pq.status,
                    (SELECT eq.sender FROM raw.email_download_queue eq WHERE eq.id = pq.email_queue_id) AS sender,
                    (SELECT eq.subject FROM raw.email_download_queue eq WHERE eq.id = pq.email_queue_id) AS subject
            """)
        else:
            # Original behavior: pending only
            query = sql.SQL("""
                WITH candidates AS (
                    SELECT pq.id
                    FROM raw.pdf_extraction_queue pq
                    LEFT JOIN raw.email_download_queue eq ON eq.id = pq.email_queue_id
                    WHERE pq.deleted_at IS NULL
                      AND pq.status = 'pending'
                    ORDER BY COALESCE(eq.email_date, pq.created_at) DESC
                    LIMIT %s
                    FOR UPDATE OF pq SKIP LOCKED
                )
                UPDATE raw.pdf_extraction_queue pq
                SET status = 'in_progress'
                FROM candidates c
                WHERE pq.id = c.id
                RETURNING pq.id, pq.email_queue_id, pq.s3_key, pq.status,
                    (SELECT eq.sender FROM raw.email_download_queue eq WHERE eq.id = pq.email_queue_id) AS sender,
                    (SELECT eq.subject FROM raw.email_download_queue eq WHERE eq.id = pq.email_queue_id) AS subject
            """)

        cursor.execute(query, (limit,))
        results = cursor.fetchall()
        connection.commit()  # Commit AFTER fetching - this releases the locks
        return [dict(row) for row in results] if results else []
    except Exception as e:
        logger.exception(f"Error claiming pending extractions: {e}")
        connection.rollback()
        return []
    finally:
        cursor.close()
        connection.close()


def mark_extraction_completed(extraction_id: str) -> bool:
    """
    Set extraction status to 'completed' and set extracted_at timestamp.

    Args:
        extraction_id: UUID of the pdf_extraction_queue record.

    Returns:
        True if update succeeded, False otherwise.
    """
    connection = connect_to_db()
    if connection is None:
        return False

    cursor = connection.cursor()
    try:
        query = sql.SQL("""
            UPDATE raw.pdf_extraction_queue
            SET status = 'completed', extracted_at = NOW()
            WHERE id = %s
        """)
        cursor.execute(query, (extraction_id,))
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.exception(f"Error marking extraction completed: {e}")
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()


def mark_extraction_failed(extraction_id: str, error_message: str) -> bool:
    """
    Set extraction status to 'failed' with error message.

    Args:
        extraction_id: UUID of the pdf_extraction_queue record.
        error_message: Description of what went wrong.

    Returns:
        True if update succeeded, False otherwise.
    """
    connection = connect_to_db()
    if connection is None:
        return False

    cursor = connection.cursor()
    try:
        query = sql.SQL("""
            UPDATE raw.pdf_extraction_queue
            SET status = 'failed', error_message = %s
            WHERE id = %s
        """)
        cursor.execute(query, (error_message, extraction_id))
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.exception(f"Error marking extraction failed: {e}")
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()


def mark_extraction_validation_failed(extraction_id: str) -> bool:
    """
    Set extraction status to 'validation_failed'.

    Called when extraction completes but validation score is below threshold
    (status='low_confidence' or 'human_review_required').
    Item can be retried with --include-retries flag.

    Args:
        extraction_id: UUID of the pdf_extraction_queue record.

    Returns:
        True if update succeeded, False otherwise.
    """
    connection = connect_to_db()
    if connection is None:
        return False

    cursor = connection.cursor()
    try:
        query = sql.SQL("""
            UPDATE raw.pdf_extraction_queue
            SET status = 'validation_failed'
            WHERE id = %s
        """)
        cursor.execute(query, (extraction_id,))
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.exception(f"Error marking extraction validation failed: {e}")
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()


def get_extraction_attempt_count(pdf_extraction_queue_id: str) -> int:
    """
    Count extraction attempts for a queue item.

    Counts distinct extracted_at timestamps in model_extracted_data
    for this pdf_extraction_queue_id (each extraction inserts multiple
    rows with the same extracted_at).

    Args:
        pdf_extraction_queue_id: UUID of the pdf_extraction_queue record.

    Returns:
        Number of extraction attempts (0 if none or on error).
    """
    connection = connect_to_db()
    if connection is None:
        return 0

    cursor = connection.cursor()
    try:
        query = sql.SQL("""
            SELECT COUNT(DISTINCT DATE_TRUNC('second', extracted_at))
            FROM raw.model_extracted_data
            WHERE pdf_extraction_queue_id = %s
        """)
        cursor.execute(query, (pdf_extraction_queue_id,))
        result = cursor.fetchone()
        return result[0] if result else 0
    except Exception as e:
        logger.exception(f"Error counting extraction attempts: {e}")
        return 0
    finally:
        cursor.close()
        connection.close()


def get_worst_validation_status(pdf_extraction_queue_id: str) -> str | None:
    """
    Get the worst validation status from the latest extraction attempt.

    Returns the "worst" status from model_extracted_data for this queue item's
    most recent extraction (by extracted_at). Priority (worst to best) follows
    VALIDATION_STATUS_PRIORITY, then model_approved as the best status.

    Args:
        pdf_extraction_queue_id: UUID of the pdf_extraction_queue record.

    Returns:
        Worst status string, or None if no records found.
    """
    connection = connect_to_db()
    if connection is None:
        return None

    cursor = connection.cursor()
    try:
        query = sql.SQL("""
            WITH latest AS (
                SELECT status
                FROM raw.model_extracted_data
                WHERE pdf_extraction_queue_id = %s
                  AND extracted_at = (
                      SELECT MAX(extracted_at)
                      FROM raw.model_extracted_data
                      WHERE pdf_extraction_queue_id = %s
                  )
            )
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM latest WHERE status = 'low_confidence') THEN 'low_confidence'
                WHEN EXISTS (SELECT 1 FROM latest WHERE status = 'human_review_required') THEN 'human_review_required'
                WHEN EXISTS (SELECT 1 FROM latest WHERE status = 'no_line_items_extracted') THEN 'no_line_items_extracted'
                WHEN EXISTS (SELECT 1 FROM latest WHERE status = 'high_confidence') THEN 'high_confidence'
                WHEN EXISTS (SELECT 1 FROM latest WHERE status = 'model_approved') THEN 'model_approved'
                ELSE NULL
            END AS worst_status
        """)
        cursor.execute(query, (pdf_extraction_queue_id, pdf_extraction_queue_id))
        result = cursor.fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.exception(f"Error getting worst validation status: {e}")
        return None
    finally:
        cursor.close()
        connection.close()


# =============================================================================
# Raw Schema Functions
# =============================================================================

def add_model_extracted_data_batch_raw(
    models: List[str],
    model_responses: Dict[str, Dict[str, Any]],
    pdf_extraction_queue_id: str,
    file_path: str,
    s3_file_key: str = "",
    email_queue_id: str = None
) -> Optional[int]:
    """
    Insert extraction data into raw.model_extracted_data (normalized schema).

    Creates ONE ROW PER MODEL EXTRACTION. All invoice data (global fields +
    line items) is stored in the raw_data JSONB column.

    This is the Phase 4 implementation for the model_extracted_data refactor.
    dbt handles parsing the JSONB into normalized structures.

    Args:
        models: List of model names (e.g., ["gemini-2.0-flash", "tabula"]).
        model_responses: Dictionary mapping model names to their extraction results.
            Each value should be a dict with line_items, confidence_score, and
            validation metadata (_validation_passed, _header_details, etc.)
        pdf_extraction_queue_id: UUID from pdf_extraction_queue table.
        file_path: Local file path to the invoice file (unused, kept for API compat).
        s3_file_key: S3 key/path where the file was downloaded from.
        email_queue_id: Optional UUID from email_download_queue table.

    Returns:
        int | None: Number of rows inserted (one per model) if successful,
            None if operation failed.

    Note:
        - Inserts into raw.model_extracted_data
        - All inserts are wrapped in a single transaction
    """
    if not models or not model_responses:
        logger.warning("No models or responses provided to add_model_extracted_data_batch_raw")
        return None

    connection = connect_to_db()
    if connection is None:
        return None

    cursor = connection.cursor()
    inserted_count = 0

    try:
        for model in models:
            if model not in model_responses:
                logger.warning(f"Model {model} missing from responses, skipping")
                continue

            response = model_responses[model]
            if not response:
                logger.warning(f"Model {model} has empty response, skipping")
                continue

            # Detect multi-invoice response
            invoices = response.get('invoices') if isinstance(response, dict) else None

            if invoices and isinstance(invoices, list) and len(invoices) > 0:
                # --- Multi-invoice aggregation ---
                per_invoice_scores = []
                per_invoice_statuses = []

                for invoice in invoices:
                    # Compute per-invoice validation_score (same logic as single)
                    inv_header_details = invoice.get('_header_details', {})
                    inv_line_items_details = invoice.get('_line_items_details', {})
                    inv_total_fields = inv_header_details.get('fields_checked', 0) + inv_line_items_details.get('fields_checked', 0)
                    inv_passed_fields = inv_header_details.get('fields_passed', 0) + inv_line_items_details.get('fields_passed', 0)
                    inv_validation_score = (inv_passed_fields / inv_total_fields) * 100 if inv_total_fields > 0 else None

                    # Compute per-invoice status (same thresholds as single)
                    inv_validation_passed = invoice.get('_validation_passed', True)
                    inv_has_line_items = len(invoice.get('line_items', [])) > 0
                    if not inv_has_line_items:
                        inv_status = 'no_line_items_extracted'
                    elif inv_validation_score is not None and inv_validation_score >= 99:
                        inv_status = 'model_approved'
                    elif inv_validation_score is not None and inv_validation_score >= 80:
                        inv_status = 'high_confidence'
                    elif not inv_validation_passed or (inv_validation_score is not None and inv_validation_score < 80):
                        inv_status = 'low_confidence'
                    else:
                        inv_status = 'human_review_required'

                    if inv_validation_score is not None:
                        per_invoice_scores.append(inv_validation_score)
                    per_invoice_statuses.append(inv_status)

                # Aggregate validation_score = average
                validation_score = sum(per_invoice_scores) / len(per_invoice_scores) if per_invoice_scores else None

                # Aggregate status: model_approved only if ALL are model_approved
                if all(s == 'model_approved' for s in per_invoice_statuses):
                    status = 'model_approved'
                else:
                    # Use worst status (same priority as get_worst_validation_status)
                    status = next((s for s in VALIDATION_STATUS_PRIORITY if s in per_invoice_statuses), 'low_confidence')

                # Aggregate confidence_score = average (skip None, empty, non-numeric)
                invoice_confidence_scores = []
                for inv in invoices:
                    val = inv.get('confidence_score')
                    if val is None or val == '':
                        continue
                    try:
                        invoice_confidence_scores.append(float(val))
                    except (ValueError, TypeError):
                        continue
                confidence_score = sum(invoice_confidence_scores) / len(invoice_confidence_scores) if invoice_confidence_scores else None

                logger.info(
                    f"Multi-invoice aggregation for {model}: {len(invoices)} invoices, "
                    f"validation_score={validation_score}, status={status}, "
                    f"per_invoice_statuses={per_invoice_statuses}"
                )
            else:
                # --- Single-invoice logic (unchanged) ---
                # Calculate validation_score from validation details (same as legacy function)
                validation_score = None
                header_details = response.get('_header_details', {})
                line_items_details = response.get('_line_items_details', {})
                total_fields = header_details.get('fields_checked', 0) + line_items_details.get('fields_checked', 0)
                passed_fields = header_details.get('fields_passed', 0) + line_items_details.get('fields_passed', 0)
                if total_fields > 0:
                    validation_score = (passed_fields / total_fields) * 100

                # Determine status (same logic as legacy function)
                validation_passed = response.get('_validation_passed', True)
                has_line_items = len(response.get('line_items', [])) > 0

                if not has_line_items:
                    status = 'no_line_items_extracted'
                elif validation_score is not None and validation_score >= 99:
                    status = 'model_approved'
                elif validation_score is not None and validation_score >= 80:
                    status = 'high_confidence'
                elif not validation_passed or (validation_score is not None and validation_score < 80):
                    status = 'low_confidence'
                else:
                    status = 'human_review_required'

                confidence_score = response.get('confidence_score')

            extraction_id = str(uuid.uuid4())

            insert_query = sql.SQL("""
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
                    extracted_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """)

            cursor.execute(insert_query, (
                extraction_id,
                s3_file_key,
                pdf_extraction_queue_id,
                email_queue_id,
                model,
                response.get('prompt_hash'),
                status,
                validation_score,
                confidence_score,
                Json(response),
                datetime.datetime.now(datetime.timezone.utc)
            ))
            inserted_count += 1
            if invoices:
                total_line_items = sum(len(inv.get('line_items', [])) for inv in invoices)
                logger.debug(
                    f"Inserted raw extraction: id={extraction_id}, model={model}, "
                    f"invoices={len(invoices)}, total_line_items={total_line_items}, status={status}"
                )
            else:
                logger.debug(
                    f"Inserted raw extraction: id={extraction_id}, model={model}, "
                    f"line_items={len(response.get('line_items', []))}, status={status}"
                )

        connection.commit()
        logger.info(
            f"Saved {inserted_count} extractions to raw.model_extracted_data "
            f"for queue item {pdf_extraction_queue_id}"
        )
        return inserted_count

    except Exception as e:
        logger.exception(
            f"Error saving extraction batch to raw schema for queue item "
            f"{pdf_extraction_queue_id}. Rolling back."
        )
        connection.rollback()
        return None
    finally:
        cursor.close()
        connection.close()
