"""
Apply filters to mart__invoice_items table with pagination.
"""

import logging
import time
import traceback
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.orm import Session
from mpi_backend.database.dao.dao_models import DaoFilteredItemsResult
from mpi_backend.database.schemas.Filters import FilterRequest
from .utils import check_mart_table_exists, build_base_filtered_query, get_text_columns


logger = logging.getLogger(__name__)


def apply_filters(
    db: Session,
    request: FilterRequest,
    page: Optional[int] = None,
    size: Optional[int] = None,
    columns: Optional[List[str]] = None,
    total_hint: Optional[int] = None
) -> Optional[DaoFilteredItemsResult]:
    """
    Query analytics.mart__invoice_items for filtered and paginated invoice items.

    Uses pre-computed trimmed and normalized columns for ultra-fast queries.
    Note: Does NOT support color filters (price increase filtering) - caller must
    handle that separately or fall back to ORM.

    Args:
        db: SQLAlchemy database session
        request: FilterRequest Pydantic object with cleaned and validated filters
        page: Page number (1-indexed), None for all records
        size: Items per page, None for all records
        columns: Optional list of specific columns to select. If None, selects all.
        total_hint: Optional hint for total count so that we can skip the count query

    Returns:
        DaoFilteredItemsResult if successful, None to fall back to invoice_items

    Note:
        If page or size is None, returns ALL matching records without pagination.
        This is logged for debugging purposes.

    Raises:
        None - returns None on any error to allow fallback
    """
    logger.info("Attempting optimized mart table for filter query")

    # Check if mart table exists
    if not check_mart_table_exists(db):
        logger.info("mart__invoice_items not found, using invoice_items fallback")
        return None

    start_time = time.time()

    # Build base filtered query CTE (single source of truth for filtering)
    try:
        base_cte, query_params = build_base_filtered_query(request)
    except (ValueError, TypeError, NotImplementedError) as e:
        # Invalid filter - fall back to ORM
        logger.warning(f"Invalid filter for mart query, falling back: {e}")
        return None

    logger.info(f"Filters: {request.filters}")
    logger.info(f"Comparison filters: {request.comparison_filters}")
    logger.info(f"Color filters: {request.color_filters}")
    logger.info(f"Order by: {request.order_by}")

    # Build ORDER BY clause
    # Default: date DESC (newest invoices first), then filename for grouping,
    # ref_no groups items from the same invoice (critical for multi-invoice PDFs),
    # line_order preserves within-invoice item ordering
    order_clause = (
        "date DESC NULLS LAST, "
        "NULLIF(filename, '') ASC NULLS LAST, "
        "NULLIF(ref_no, '') ASC NULLS LAST, "
        "line_order ASC NULLS LAST, "
        "invoice_items_id DESC NULLS LAST"
    )
    if request.order_by and isinstance(request.order_by, list):
        order_parts = []
        id_order_part = None  # Track invoice_items_id separately to ensure it comes last
        
        # Determine which columns are text-based for safe NULLIF application
        text_columns = get_text_columns()

        for ob in request.order_by:
            col = ob.column
            # Map 'id' to actual column name 'invoice_items_id'
            if col == 'id':
                col = 'invoice_items_id'
            order = ob.order

            # Only apply NULLIF to true text columns to preserve numeric/date sort order
            if col in text_columns:
                part = f"NULLIF({col}::text, '') {order}"
            else:
                part = f"{col} {order}"

            # Track invoice_items_id separately - it must come LAST after filename/line_order
            if col == 'invoice_items_id':
                id_order_part = part
            else:
                order_parts.append(part)

        if order_parts or id_order_part:
            # Always append filename, ref_no, and line_order for grouping
            if not any("filename" in part for part in order_parts):
                order_parts.append("NULLIF(filename, '') ASC")
            if not any("ref_no" in part for part in order_parts):
                order_parts.append("NULLIF(ref_no, '') ASC")
            if not any("line_order" in part for part in order_parts):
                order_parts.append("line_order ASC")
            # invoice_items_id must come LAST for deterministic pagination within groups
            if id_order_part:
                order_parts.append(id_order_part)
            else:
                order_parts.append("invoice_items_id DESC")
            # Apply NULLS LAST to every component in the clause
            order_clause = ", ".join([f"{p} NULLS LAST" if "NULLS LAST" not in p else p for p in order_parts])

    # Handle "all records" mode when page/size are None
    if page is None or size is None:
        # No pagination - get ALL matching records
        logger.info("Returning all records (page and/or size not specified)")
        offset = 0
        limit_clause = ""
        effective_page = 1
        effective_size = None  # Will be set to total_count in return
    else:
        # Normal pagination mode
        offset = (page - 1) * size
        limit_clause = "LIMIT :limit OFFSET :offset"
        effective_page = page
        effective_size = size

    # OPTIMIZATION: Use separate COUNT and data queries
    # This allows PostgreSQL to optimize each query independently

    # 1. Fast COUNT query (no SELECT *, no ORDER BY)
    # Reuses the filtered_items CTE from base_cte
    count_query = f"""
        {base_cte}
        SELECT COUNT(*) as total
        FROM filtered_items
    """

    total_count = 0

    if total_hint is not None and page and page > 1:
        total_count = total_hint  # Skip COUNT query

    else:
        logger.info("DAO: Executing count query")
        try:
            count_result = db.execute(text(count_query), query_params)
            total_count = count_result.scalar()
        except Exception as e:
            logger.warning(f"Error using optimized mart table for filter, falling back: {e}")
            logger.debug(f"Error details: {traceback.format_exc()}")
            return None

    # Determine columns to select
    if columns:
        select_cols = []
        for col in columns:
            if col == 'id':
                select_cols.append("invoice_items_id::text AS id")
            else:
                select_cols.append(col)
        select_clause = ", ".join(select_cols)
    else:
        # Default with alias for backward compatibility
        select_clause = "*, invoice_items_id::text AS id"

    # 2. Fast paginated data query (only LIMIT/OFFSET rows)
    # Reuses the filtered_items CTE from base_cte
    data_query = f"""
        {base_cte}
        SELECT
            {select_clause}
        FROM filtered_items
        ORDER BY {order_clause}
        {limit_clause}
    """

    # Only add pagination params if using pagination
    if size is not None:
        query_params.update({
            'limit': size,
            'offset': offset
        })


    try:
        # Execute data query
        logger.info("DAO: Executing paginated data query")
        logger.debug(data_query, query_params)
        result = db.execute(text(data_query), query_params)
        rows = result.fetchall()

        # Extract results
        items = []

        if rows:
            # Get column names from result
            columns_names = result.keys()

            for row in rows:
                # Convert row to dict
                item_dict = dict(zip(columns_names, row))
                items.append(item_dict)

        execution_time = time.time() - start_time
        logger.info(
            f"DAO OPTIMIZED MART FILTER: {execution_time:.3f}s, "
            f"returned {len(items)}/{total_count} items"
        )

        return DaoFilteredItemsResult(
            items=items,
            total=int(total_count) if total_count else 0,
            page=effective_page,
            size=total_count if effective_size is None else effective_size,
            source="mart_invoice_items_filtered"
        )

    except Exception as e:
        logger.warning(f"Error using optimized mart table for filter, falling back: {e}")
        logger.debug(f"Error details: {traceback.format_exc()}")
        return None
