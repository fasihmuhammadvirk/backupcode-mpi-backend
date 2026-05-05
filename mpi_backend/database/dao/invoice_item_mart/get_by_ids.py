"""
Get invoice items by IDs from mart__invoice_items table.
"""

import logging
import time
import traceback
from typing import List, Optional, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session
from .utils import check_mart_table_exists, OVERRIDEABLE_COALESCE_EXPRESSIONS, get_text_columns


logger = logging.getLogger(__name__)


def get_by_ids(
    db: Session,
    ids: List[int],
    columns: Optional[List[str]] = None,
    order_by: Optional[List[Dict[str, str]]] = None
) -> Optional[List[Dict[str, Any]]]:
    """
    Query analytics.mart__invoice_items for specific invoice items by IDs.

    Uses pre-computed trimmed and normalized columns for ultra-fast queries.
    Returns raw dictionaries for efficient processing without ORM overhead.

    Args:
        db: SQLAlchemy database session
        ids: List of invoice_items IDs to retrieve
        columns: Optional list of column names to select (None = all columns)
        order_by: Optional list of OrderByFilter dicts with 'column' and 'order' keys
                  Example: [{'column': 'date', 'order': 'desc'}]

    Returns:
        List of dictionaries representing invoice items, or None to fall back to ORM

    Raises:
        None - returns None on any error to allow fallback
    """
    logger.info(f"Getting {len(ids)} items by IDs from mart table")
    logger.debug(f"IDs: {ids}")

    # Check if mart table exists
    if not check_mart_table_exists(db):
        logger.info("mart__invoice_items not found, using invoice_items fallback")
        return None

    # Validate input
    if not ids:
        logger.warning("Empty IDs list provided")
        return []

    start_time = time.time()

    try:
        # Build validated column list (None = select all)
        select_columns: Optional[List[str]] = None
        if columns:
            validated = []
            for col in columns:
                if col.replace('_', '').isalnum():
                    validated.append(col)
                else:
                    logger.warning(f"Skipping invalid column name: {col}")
            if validated:
                if 'invoice_items_id' not in validated:
                    validated.append('invoice_items_id')
                select_columns = validated
            # else: all columns were invalid — fall through to select all

        # Build ORDER BY clause
        # Default: match apply_filters.py ordering for consistent results across endpoints
        # Order by date DESC, then group by filename, ref_no, and line_order for invoice item grouping
        order_clause = (
            "mart.date DESC NULLS LAST, "
            "NULLIF(mart.filename, '') ASC NULLS LAST, "
            "NULLIF(mart.ref_no, '') ASC NULLS LAST, "
            "mart.line_order ASC NULLS LAST, "
            "mart.invoice_items_id DESC NULLS LAST"
        )
        if order_by and isinstance(order_by, list):
            order_parts = []
            id_order_part = None  # Track invoice_items_id separately to ensure it comes last

            # Determine which columns are text-based for safe NULLIF application
            text_columns = get_text_columns()

            for ob in order_by:
                col = ob.get('column') if isinstance(ob, dict) else getattr(ob, 'column', None)
                order = ob.get('order') if isinstance(ob, dict) else getattr(ob, 'order', 'asc')

                if col:
                    # Map 'id' to actual column name 'invoice_items_id'
                    if col == 'id':
                        col = 'invoice_items_id'

                    # Only apply NULLIF to true text columns to preserve numeric/date sort order
                    if col in text_columns:
                        part = f"NULLIF(mart.{col}::text, '') {order}"
                    else:
                        part = f"mart.{col} {order}"

                    # Track invoice_items_id separately - it must come LAST after filename/line_order
                    if col == 'invoice_items_id':
                        id_order_part = part
                    else:
                        order_parts.append(part)

            if order_parts or id_order_part:
                # Always append filename, ref_no, and line_order for grouping
                if not any("filename" in part for part in order_parts):
                    order_parts.append("NULLIF(mart.filename, '') ASC")
                if not any("ref_no" in part for part in order_parts):
                    order_parts.append("NULLIF(mart.ref_no, '') ASC")
                if not any("line_order" in part for part in order_parts):
                    order_parts.append("mart.line_order ASC")
                # invoice_items_id must come LAST for deterministic pagination within groups
                if id_order_part:
                    order_parts.append(id_order_part)
                else:
                    order_parts.append("mart.invoice_items_id DESC")
                order_clause = ", ".join([f"{p} NULLS LAST" if "NULLS LAST" not in p else p for p in order_parts])

        logger.info(f"get_by_ids ORDER BY clause: {order_clause}")
        logger.info(f"get_by_ids order_by parameter: {order_by}")

        # Build UNNEST ARRAY query for better performance with large ID lists
        # Use parameterized query to prevent SQL injection
        query_params = {'id_array': ids}

        # Two-level CTE to avoid duplicate column names when applying COALESCE overrides.
        # The inner CTE stores override JSONB as _override_json; the outer SELECT applies
        # COALESCE without duplicating any mart column names.
        # order_clause uses 'mart.' qualifiers which are valid in the inner CTE only;
        # strip the prefix for the outer ORDER BY (columns are unambiguous there).
        outer_order_clause = order_clause.replace("mart.", "")

        if select_columns is None:
            # Columns NOT in OVERRIDEABLE_COALESCE_EXPRESSIONS are passed through raw.
            # Overrideable columns (date, vendor, qty, cost, amount, etc.) are ONLY
            # emitted via the COALESCE expressions to avoid duplicate column names
            # which would make ORDER BY ambiguous.
            outer_select = f"""
                invoice_items_id, invoice_id, item, ref_no,
                street_number, street_name, city, state,
                zip_code, address_confidence,
                assigned_account, filename, bill, export_status, date_added,
                item_normalized, mpi_item_normalized, description_normalized,
                mpi_description_normalized, vendor_search_normalized,
                buyer_normalized, sheet_name_normalized, customer_job_normalized,
                ref_no_normalized, line_order, id, is_overridden,
                {', '.join(OVERRIDEABLE_COALESCE_EXPRESSIONS.values())}
            """
        else:
            assert select_columns is not None  # narrowed from Optional by the if-branch above
            outer_parts = [
                OVERRIDEABLE_COALESCE_EXPRESSIONS[col] if col in OVERRIDEABLE_COALESCE_EXPRESSIONS else col
                for col in select_columns
            ]
            if 'id' not in outer_parts:
                outer_parts.append('id')
            if 'is_overridden' not in outer_parts:
                outer_parts.append('is_overridden')
            outer_select = ', '.join(outer_parts)

        sql_query = f"""
            WITH raw_data AS (
                SELECT
                    mart.*,
                    mart.invoice_items_id::text AS id,
                    o.overrides AS _override_json,
                    CASE WHEN o.record_id IS NOT NULL THEN TRUE ELSE FALSE END AS is_overridden,
                    mart.rerated_cost AS current_price,
                    mart.rerated_qty AS current_qty,
                    mart.qty AS original_current_qty
                FROM analytics.mart__invoice_items mart
                INNER JOIN UNNEST(CAST(:id_array AS NUMERIC[])) AS temp_ids(id)
                    ON mart.invoice_items_id = temp_ids.id
                LEFT JOIN public.user_overrides o
                    ON mart.invoice_items_id::text = o.record_id AND o.deleted_at IS NULL
                LEFT JOIN public.invoice_voided iv
                    ON mart.ref_no = iv.ref_no
                   AND mart.date   = iv.date
                   AND mart.vendor = iv.vendor
                WHERE iv.ref_no IS NULL
                  AND COALESCE(o.is_row_deleted, FALSE) = FALSE
            )
            SELECT {outer_select}
            FROM raw_data
            ORDER BY {outer_order_clause}
        """

        # Execute query
        logger.info(f"Executing mart get_by_ids query for {len(ids)} items using UNNEST")
        logger.debug(f"Query: {sql_query}")
        result = db.execute(text(sql_query), query_params)
        rows = result.fetchall()

        # Convert to list of dictionaries
        items = []
        if rows:
            # Get column names from result
            column_names = result.keys()

            for row in rows:
                # Convert row to dict
                item_dict = dict(zip(column_names, row))
                items.append(item_dict)

        execution_time = time.time() - start_time
        logger.info(
            f"DAO OPTIMIZED MART GET_BY_IDS: {execution_time:.3f}s, "
            f"returned {len(items)}/{len(ids)} items"
        )

        return items

    except Exception as e:
        logger.warning(f"Error using optimized mart table for get_by_ids, falling back: {e}")
        logger.debug(f"Error details: {traceback.format_exc()}")
        # Roll back so the failed query doesn't poison the session for the caller's
        # next statement (otherwise psycopg2 reports InFailedSqlTransaction downstream).
        try:
            db.rollback()
        except Exception:
            logger.exception("rollback after mart get_by_ids failure also failed")
        return None
