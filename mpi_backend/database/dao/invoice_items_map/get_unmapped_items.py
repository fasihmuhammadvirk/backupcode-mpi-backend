"""
Get unmapped items from analytics.mart__invoice_items_map.
"""

import logging
import time
from typing import Optional, List, Dict, Any, Tuple
from datetime import date
from sqlalchemy import text
from sqlalchemy.orm import Session
from mpi_backend.database.dao.dao_models import DaoUnmappedItemsResult
from mpi_backend.database.dao.invoice_items_map.get_mapping_types import EXPECTED_MAPPING_TYPES
from mpi_backend.database.dao.invoice_items_map.constants import GROUP_BY_MAP


logger = logging.getLogger(__name__)


def _build_where_conditions(
        item_type: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        date_history: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        item_ids: Optional[List[str]] = None,
        include_null_checks: bool = False,
        table_alias: str = ""
) -> Tuple[List[str], Dict[str, Any]]:
    """
    Build WHERE conditions and query parameters for unmapped items queries.

    Args:
        item_type: mapping_type filter ('temporary', 'no_match', 'permanent', 'all', or None)
        date_from: Start date filter (optional)
        date_to: End date filter (optional)
        date_history: Date added filter (matches COALESCE(date_added, date), optional)
        supplier_names: List of supplier names to filter by (optional)
        item_ids: List of item IDs to filter by (optional)
        include_null_checks: Add "item IS NOT NULL AND item != ''" conditions
        table_alias: Optional table alias prefix (e.g. "m") for column qualification

    Returns:
        Tuple of (where_conditions list, query_params dict)
    """
    where_conditions = []
    query_params = {}
    col_prefix = f"{table_alias}." if table_alias else ""

    if include_null_checks:
        where_conditions.extend([f"{col_prefix}item IS NOT NULL", f"{col_prefix}item != ''"])

    if item_type and item_type.lower() != 'all':
        where_conditions.append(f"{col_prefix}mapping_type = :mapping_type")
        query_params['mapping_type'] = item_type

    if date_from:
        where_conditions.append(f"{col_prefix}date >= :date_from")
        query_params['date_from'] = date_from

    if date_to:
        where_conditions.append(f"{col_prefix}date <= :date_to")
        query_params['date_to'] = date_to

    if date_history:
        # Filter by "date added" (when the system first saw the item), falling back
        # to invoice date for legacy rows where date_added is NULL. Mirrors the logic
        # in mart__item_mapping_timeline.sql so the Mappings "Date History" filter
        # stays consistent with the Status History timeline.
        #
        # date_added is timestamptz, stored in UTC. We cast it to a calendar date
        # in America/New_York (the business timezone) so the filter, the available-
        # dates dropdown, and the Status History modal all agree on which day a
        # late-evening ET timestamp belongs to. Without the AT TIME ZONE cast a
        # row recorded at e.g. 2026-04-28 00:19 UTC (= 2026-04-27 20:19 ET) would
        # be filed under 04/28 by the filter but rendered as 04/27 in the modal.
        where_conditions.append(
            f"COALESCE(({col_prefix}date_added AT TIME ZONE 'America/New_York')::date, {col_prefix}date) = :date_history"
        )
        query_params['date_history'] = date_history

    if supplier_names and len(supplier_names) > 0:
        if not (len(supplier_names) == 1 and supplier_names[0].lower() == 'all'):
            supplier_params = [f"supplier_{i}" for i in range(len(supplier_names))]
            supplier_placeholders = ", ".join(f":{param}" for param in supplier_params)
            where_conditions.append(f"{col_prefix}vendor IN ({supplier_placeholders})")
            for param, supplier in zip(supplier_params, supplier_names):
                query_params[param] = supplier

    if item_ids:
        item_params = [f"item_id_{i}" for i in range(len(item_ids))]
        item_placeholders = ", ".join(f":{param}" for param in item_params)
        where_conditions.append(f"{col_prefix}item IN ({item_placeholders})")
        for param, item_id in zip(item_params, item_ids):
            query_params[param] = item_id

    return where_conditions, query_params


def _build_order_clause(
    order_by: Optional[List[dict]],
    default: str = "amount DESC NULLS LAST"
) -> str:
    """
    Build a safe ORDER BY clause from order_by list. Supports custom mapping_type sort.
    """
    if not order_by or not isinstance(order_by, list) or len(order_by) == 0:
        return default
    order_parts: List[str] = []
    for ob in order_by:
        col = ob.get("column", "amount")
        order = ob.get("order", "desc").lower()
        if col == "status":
            col = "mapping_type"
        if col == "mapping_type":
            custom_sort = (
                f"CASE WHEN mapping_type = 'permanent' THEN 1 "
                f"WHEN mapping_type = 'possible_match' THEN 2 "
                f"WHEN mapping_type = 'temporary' THEN 3 "
                f"ELSE 4 END {order.upper()}"
            )
            order_parts.append(custom_sort)
        else:
            order_parts.append(f"{col} {order.upper()} NULLS LAST")
    return ", ".join(order_parts) if order_parts else default


def get_unmapped_items(
    db: Session,
    item_type: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    date_history: Optional[date] = None,
    supplier_names: Optional[List[str]] = None,
    search: Optional[str] = None,
    order_by: Optional[List[dict]] = None,
    page: int = 1,
    size: int = 10,
    group_by: Optional[str] = None
) -> DaoUnmappedItemsResult:
    """
    Query analytics.mart__invoice_items_map for unmapped items with pagination.

    Args:
        db: SQLAlchemy database session
        item_type: Type of items to filter - 'temporary', 'unmapped', or 'no_temporary'
        date_from: Start date filter (optional)
        date_to: End date filter (optional)
        date_history: Date added filter (matches COALESCE(date_added, date), optional)
        supplier_names: List of supplier names to filter by (optional)
        search: Search term for item/description ILIKE filter (optional)
        order_by: List of order_by dicts with 'column' and 'order' keys (optional)
        page: Page number (1-indexed)
        size: Items per page

    Returns:
        DaoUnmappedItemsResult with items, pagination metadata, and source identifier

    Notes:
        - Filters by mapping_type column based on item_type: no_match, permanent, temporary 
        - Aggregates by vendor + item (GROUP BY) to get unique items
        - Field mappings: item→original_item_id, description→original_description,
          vendor→supplier, qty→quantity
    """
    logger.info(f"DAO: Querying unmapped items from mart__invoice_items_map (item_type={item_type})")
    start_time = time.time()

    # Build WHERE conditions (with table alias since we join invoice_voided)
    where_conditions, query_params = _build_where_conditions(
        item_type=item_type,
        date_from=date_from,
        date_to=date_to,
        date_history=date_history,
        supplier_names=supplier_names,
        table_alias="m"
    )
    query_params.update({'page_size': size, 'offset': (page - 1) * size})

    where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

    # Build base CTE with aggregated unique items and isolation status
    base_cte = f"""
        WITH aggregated_items AS (
            SELECT
                m.vendor AS supplier,
                m.mapping_type,
                m.item AS original_item_id,
                MIN(m.description) AS original_description,
                MIN(m.sheet_name) AS sheet_name,
                SUM(m.rerated_cost * m.rerated_qty) / NULLIF(SUM(m.rerated_qty), 0) AS cost,
                SUM(m.rerated_qty) AS quantity,
                SUM(m.qty) AS original_quantity,
                BOOL_OR(m.is_price_rerated) AS is_price_rerated,
                COUNT(DISTINCT (m.ref_no, m.date)) AS times_bought,
                SUM(m.rerated_cost * m.rerated_qty) AS amount,
                MAX(m.date) AS date
            FROM analytics.mart__invoice_items_map m
            LEFT JOIN public.user_overrides o
                ON m.id::text = o.record_id AND o.deleted_at IS NULL
            LEFT JOIN public.invoice_voided iv
                ON m.ref_no = iv.ref_no
               AND m.date   = iv.date
               AND m.vendor = iv.vendor
            WHERE iv.ref_no IS NULL 
              AND COALESCE(o.is_row_deleted, FALSE) = FALSE
              AND {where_clause}
            GROUP BY m.vendor, m.item, m.mapping_type
        ),
        unique_items AS (
            SELECT 
                ai.*,
                (mri.item_id IS NOT NULL) AS is_isolated
            FROM aggregated_items ai
            LEFT JOIN (
                -- We select DISTINCT to ensure we don't multiply rows 
                -- if one item has multiple review entries
                SELECT DISTINCT item_id, vendor 
                FROM public.mappings_review_items
            ) mri ON mri.item_id = ai.original_item_id 
                 AND mri.vendor = ai.supplier
        )
    """

    # Apply search filter AFTER aggregation.
    # Normalize newline/carriage-return characters in both item ID and description
    # before comparing so that items extracted with embedded \n or \r are still
    # findable when the user types the text without them.
    search_condition = ""
    if search and search.strip():
        search_condition = """
            WHERE
                REPLACE(REPLACE(original_item_id, chr(10), ' '), chr(13), ' ') ILIKE :search_term
                OR REPLACE(REPLACE(original_description, chr(10), ' '), chr(13), ' ') ILIKE :search_term
        """
        query_params['search_term'] = f"%{search.strip()}%"

    # Build ORDER BY clause
    order_clause = _build_order_clause(order_by, default="amount DESC NULLS LAST")

    # Build COUNT and AGGREGATES query (using ROLLUP for single-pass if grouping is requested)
    group_col = None
    # NOTE: group_col is securely populated ONLY from the hardcoded GROUP_BY_MAP whitelist below
    # based on validated input, making it safe to interpolate into SQL.
    if group_by:
        group_col = GROUP_BY_MAP.get(group_by)

    # Both count queries use the same column order so a single parser works:
    # 0: group_key (NULL for ROLLUP grand total, or the grouped dimension)
    # 1: total (COUNT(*) unique item rows in that slice)
    # 2-4: sums for footer aggregates
    # 5: total_times_bought (aligns with PaginatedUnmappedItemsResponse / frontend)
    # 6: is_grand_total — must be last; ROLLUP uses GROUPING() == 1 for super-aggregate only.
    if group_col:
        count_agg_query = f"""
            {base_cte}
            SELECT 
                {group_col} as group_key,
                COUNT(*) as total,
                COALESCE(SUM(cost), 0) as total_cost,
                COALESCE(SUM(amount), 0) as total_amount,
                COALESCE(SUM(quantity), 0) as total_qty,
                COALESCE(SUM(times_bought), 0) as total_times_bought,
                GROUPING({group_col}) as is_grand_total
            FROM unique_items
            {search_condition}
            GROUP BY ROLLUP({group_col})
        """
    else:
        count_agg_query = f"""
            {base_cte}
            SELECT 
                NULL as group_key,
                COUNT(*) as total,
                COALESCE(SUM(cost), 0) as total_cost,
                COALESCE(SUM(amount), 0) as total_amount,
                COALESCE(SUM(quantity), 0) as total_qty,
                COALESCE(SUM(times_bought), 0) as total_times_bought,
                1 as is_grand_total
            FROM unique_items
            {search_condition}
        """

    # Execute count + aggregates query
    total_count = 0
    aggregates = {
        "total_cost": 0.0,
        "total_amount": 0.0,
        "total_qty": 0.0,
        "total_times_bought": 0,
    }
    group_counts = {}

    try:
        count_result = db.execute(text(count_agg_query), query_params)
        agg_rows = count_result.fetchall()

        for row in agg_rows:
            # is_grand_total is always the last selected column; never index by position 5/6
            # because the ROLLUP path and the "no group_by" path use different lengths otherwise.
            is_grand_total = (row[-1] == 1) if row else False

            if is_grand_total:
                # Grand total: row[0] is group_key and is NULL — never use it as a count.
                # row[1] is COUNT(*); that is what drives pagination and totalRowCount.
                count_val = int(row[1] or 0) if len(row) > 1 else 0
                total_count = count_val
                aggregates = {
                    "total_cost": float(row[2] or 0) if len(row) > 2 else 0.0,
                    "total_amount": float(row[3] or 0) if len(row) > 3 else 0.0,
                    "total_qty": float(row[4] or 0) if len(row) > 4 else 0.0,
                    "total_times_bought": int(row[5] or 0) if len(row) > 5 else 0,
                }
            else:
                # One row per group: row[0] = dimension, row[1] = that group's row count
                group_key = str(row[0]) if row[0] is not None else ""
                # Align with frontend "No Sheet Name" and "Unknown Supplier" labels
                if not group_key:
                    if group_by == "sheet":
                        group_key = "No Sheet Name"
                    elif group_by == "supplier":
                        group_key = "Unknown Supplier"
                    elif group_by == "date":
                        group_key = "No Date"
                    else:
                        group_key = "Unknown"

                group_counts[group_key] = int(row[1] or 0) if len(row) > 1 else 0
                
    except Exception as e:
        logger.error(f"Error executing count/aggregates ROLLUP query: {e}")
        raise

    # Build paginated data query
    # If size=0, omit LIMIT/OFFSET to get all items
    limit_clause = ""
    if size > 0:
        limit_clause = "LIMIT :page_size OFFSET :offset"

    data_query = f"""
        {base_cte}
        SELECT
            original_item_id,
            original_description,
            mapping_type,
            cost,
            amount,
            quantity,
            original_quantity,
            times_bought,
            sheet_name,
            supplier,
            date,
            is_isolated,
            is_price_rerated
        FROM unique_items
        {search_condition}
        ORDER BY {order_clause}
        {limit_clause}
    """

    # Execute data query
    try:
        result = db.execute(text(data_query), query_params)
        rows = result.fetchall()

        # Convert rows to list of dicts
        items = []
        if rows:
            columns = result.keys()
            for row in rows:
                items.append(dict(zip(columns, row)))

        # Pagination: normalize in case a future query change ever leaves a non-int
        count_int = int(total_count) if total_count is not None else 0
        total_pages = (count_int + size - 1) // size if size > 0 and count_int > 0 else 0

        execution_time = time.time() - start_time
        logger.info(
            f"DAO MART__INVOICE_ITEMS_MAP: {execution_time:.3f}s, "
            f"returned {len(items)}/{count_int} items"
        )

        return DaoUnmappedItemsResult(
            items=items,
            total_count=count_int,
            page=page,
            size=size,
            pages=total_pages,
            aggregates=aggregates,
            group_counts=group_counts if group_counts else None,
            source="mart__invoice_items_map"
        )

    except Exception as e:
        logger.error(f"Error executing data query for unmapped items: {e}")
        raise


def get_unmapped_items_by_ids(
    db: Session,
    item_ids: List[str],
    order_by: Optional[List[dict]] = None,
    item_type: Optional[str] = None
) -> Optional[List[Dict[str, Any]]]:
    """
    Get unmapped items by their item IDs from analytics.mart__invoice_items_map.

    Args:
        db: SQLAlchemy database session
        item_ids: List of item ID strings to filter by (e.g., ["ABC123-B", "XYZ789-F"])
        order_by: List of order_by dicts with 'column' and 'order' keys (optional)

    Returns:
        List of item dicts for compatibility with export_items_generic,
        or None if no items found.

    Notes:
        - Filters by mapping_type IN ('no_match', 'temporary') for unmapped items
        - Aggregates by vendor + item (GROUP BY) to get unique items
        - Returns raw list of dicts (not wrapped in dataclass)
    """
    if not item_ids:
        return None

    logger.info(f"DAO: Querying unmapped items by IDs from mart__invoice_items_map ({len(item_ids)} IDs)")
    start_time = time.time()

    # Build WHERE conditions (with table alias since we join invoice_voided)
    where_conditions, query_params = _build_where_conditions(
        item_type=item_type if item_type and item_type.lower() != 'all' else None,
        item_ids=item_ids,
        include_null_checks=True,
        table_alias="m"
    )

    if not item_type or (item_type and item_type.lower() != 'all'):
        if 'mapping_type' not in query_params:
            where_conditions.append("m.mapping_type IN (:mapping_type_no_match, :mapping_type_temp)")
            query_params['mapping_type_no_match'] = 'no_match'
            query_params['mapping_type_temp'] = 'temporary'

    where_clause = " AND ".join(where_conditions)

    # Build ORDER BY clause
    order_clause = _build_order_clause(order_by, default="amount DESC NULLS LAST")

    # Build data query with aggregation
    data_query = f"""
        SELECT
            m.vendor AS supplier,
            m.item AS original_item_id,
            MIN(m.description) AS original_description,
            MIN(m.sheet_name) AS sheet_name,
            SUM(m.rerated_cost * m.rerated_qty) / NULLIF(SUM(m.rerated_qty), 0) AS cost,
            SUM(m.rerated_qty) AS quantity,
            COUNT(DISTINCT (m.ref_no, m.date)) AS times_bought,
            SUM(m.rerated_cost * m.rerated_qty) AS amount,
            BOOL_OR(m.is_price_rerated) AS is_price_rerated,
            EXISTS (
                SELECT 1 FROM public.mappings_review_items mri 
                WHERE mri.item_id = m.item AND mri.vendor = m.vendor
            ) AS is_isolated
        FROM analytics.mart__invoice_items_map m
        LEFT JOIN public.user_overrides o
            ON m.id::text = o.record_id AND o.deleted_at IS NULL
        LEFT JOIN public.invoice_voided iv
            ON m.ref_no = iv.ref_no
           AND m.date   = iv.date
           AND m.vendor = iv.vendor        
        WHERE iv.ref_no IS NULL 
          AND COALESCE(o.is_row_deleted, FALSE) = FALSE
          AND {where_clause}
        GROUP BY m.vendor, m.item
        ORDER BY {order_clause}
    """

    try:
        result = db.execute(text(data_query), query_params)
        rows = result.fetchall()

        if not rows:
            logger.info("DAO: No unmapped items found for the given IDs")
            return None

        # Convert rows to list of dicts
        items = []
        columns = result.keys()
        for row in rows:
            items.append(dict(zip(columns, row)))

        execution_time = time.time() - start_time
        logger.info(
            f"DAO MART__INVOICE_ITEMS_MAP by IDs: {execution_time:.3f}s, "
            f"returned {len(items)} items"
        )

        return items

    except Exception as e:
        logger.error(f"Error executing query for unmapped items by IDs: {e}")
        raise


def get_unmapped_items_graph_stats(
    db: Session,
    item_type: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    date_history: Optional[date] = None,
    supplier_names: Optional[List[str]] = None,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get date-based counts for unmapped items graph statistics (no pagination).
    Returns dynamic mapping type counts based on actual data for ALL dates.

    Args:
        db: SQLAlchemy database session
        item_type: Type of items to filter - 'temporary', 'no_match', 'permanent', or 'all'
        date_from: Start date filter (optional, not used - returns all dates)
        date_to: End date filter (optional, not used - returns all dates)
        date_history: Date added filter (matches COALESCE(date_added, date), optional)
        supplier_names: List of supplier names to filter by (optional)
        search: Search term for item/description ILIKE filter (optional)

    Returns:
        List of dicts with date and dynamic {mapping_type}: count pairs
        Example: [{"date": "2024-01-01", "permanent": 10, "temporary": 5, "no_match": 3}]
    """
    logger.info(f"DAO: Querying graph stats from mart__invoice_items_map (item_type={item_type})")
    start_time = time.time()

    where_conditions, query_params = _build_where_conditions(
        date_history=date_history,
        item_type=item_type,
        supplier_names=supplier_names,
        table_alias="m"
    )

    where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

    search_condition = ""
    if search and search.strip():
        search_condition = """
            AND (
                m.item ILIKE :search_term
                OR m.description ILIKE :search_term
            )
        """
        query_params['search_term'] = f"%{search.strip()}%"

    data_query = f"""
        WITH unique_items AS (
            SELECT DISTINCT
                m.vendor,
                m.item,
                m.mapping_type,
                MAX(m.date) AS date
            FROM analytics.mart__invoice_items_map m
            LEFT JOIN public.user_overrides o
                ON m.id::text = o.record_id AND o.deleted_at IS NULL
            LEFT JOIN public.invoice_voided iv
                ON m.ref_no = iv.ref_no
               AND m.date   = iv.date
               AND m.vendor = iv.vendor
            WHERE iv.ref_no IS NULL 
              AND COALESCE(o.is_row_deleted, FALSE) = FALSE
              AND {where_clause}
            {search_condition}
            GROUP BY m.vendor, m.item, m.mapping_type
        )
        SELECT
            date,
            mapping_type,
            COUNT(*) AS count
        FROM unique_items
        WHERE date IS NOT NULL
        GROUP BY date, mapping_type
        ORDER BY date ASC
    """

    try:
        result = db.execute(text(data_query), query_params)
        rows = result.fetchall()

        # Pivot the data: group by date, with dynamic mapping_type keys
        date_map: Dict[str, Dict[str, Any]] = {}
        all_mapping_types: set = set()
        
        for row in rows:
            date_val, mapping_type, count = row
            
            # Format the date
            if date_val:
                if hasattr(date_val, 'strftime'):
                    date_str = date_val.strftime("%Y-%m-%d")
                else:
                    date_str = str(date_val)
            else:
                continue  # Skip null dates
            
            # Track all mapping types
            if mapping_type:
                all_mapping_types.add(mapping_type)
            
            # Initialize date entry if not exists
            if date_str not in date_map:
                date_map[date_str] = {"date": date_str}
            
            # Add the count for this mapping type (dynamic key)
            if mapping_type:
                date_map[date_str][mapping_type] = count

        # Return all dates sorted ascending (oldest to newest for graph display)
        items = []
        # Use union of expected types and any discovered types from data
        all_types_to_include = EXPECTED_MAPPING_TYPES | all_mapping_types
        for date_str in sorted(date_map.keys()):
            entry = date_map[date_str]
            # Ensure all expected mapping types are present (with 0 for missing)
            for mt in all_types_to_include:
                if mt not in entry:
                    entry[mt] = 0
            items.append(entry)

        execution_time = time.time() - start_time
        logger.info(
            f"DAO GRAPH STATS: {execution_time:.3f}s, "
            f"returned {len(items)} date groups with types: {all_mapping_types}"
        )

        return items

    except Exception as e:
        logger.error(f"Error executing graph stats query: {e}")
        raise



def get_unmapped_items_available_dates(
    db: Session,
    item_type: Optional[str] = None,
    supplier_names: Optional[List[str]] = None
) -> List[str]:
    """
    Return a sorted (newest → oldest) list of distinct "date added" values present
    in analytics.mart__invoice_items_map, respecting item_type and supplier filters.

    Uses COALESCE(date_added, date) so legacy rows without a date_added still show
    up (under their invoice date), matching the logic used in
    mart__item_mapping_timeline.sql and the date_history filter.

    Used to populate the "Date History" dropdown on the frontend.

    Args:
        db: SQLAlchemy database session
        item_type: mapping_type filter ('temporary', 'no_match', 'permanent', 'all', or None)
        supplier_names: list of vendor names to restrict to (optional)

    Returns:
        List of date strings in dd/mm/yyyy format, newest first.
        "dates": ["04/11/2023", "03/11/2023", "11/05/2023", "11/02/2023"],
    """
    logger.info(f"DAO: Querying available dates (item_type={item_type})")
    start_time = time.time()

    where_conditions, query_params = _build_where_conditions(
        item_type=item_type,
        supplier_names=supplier_names,
        table_alias="m"
    )
    # Use COALESCE(date_added, date) so the dropdown lists the same anchor the
    # Status History timeline and the date_history filter use (date_added, with
    # invoice date as a fallback for legacy rows where date_added is NULL).
    # Cast date_added (timestamptz, stored in UTC) to a calendar date in
    # America/New_York so the dropdown shows business-timezone days and matches
    # what the date_history filter and Status History modal will display.
    where_conditions.insert(
        0,
        "COALESCE((m.date_added AT TIME ZONE 'America/New_York')::date, m.date) IS NOT NULL",
    )

    where_clause = " AND ".join(where_conditions)

    data_query = f"""
        SELECT DISTINCT COALESCE((m.date_added AT TIME ZONE 'America/New_York')::date, m.date) AS date
        FROM analytics.mart__invoice_items_map m
        LEFT JOIN public.user_overrides o
            ON m.id::text = o.record_id AND o.deleted_at IS NULL
        LEFT JOIN public.invoice_voided iv
            ON m.ref_no = iv.ref_no
           AND m.date   = iv.date
           AND m.vendor = iv.vendor
        WHERE iv.ref_no IS NULL 
          AND COALESCE(o.is_row_deleted, FALSE) = FALSE
          AND {where_clause}
        ORDER BY 1 DESC
    """

    try:
        result = db.execute(text(data_query), query_params)
        rows = result.fetchall()

        dates = []
        for row in rows:
            date_val = row[0]
            if date_val:
                if hasattr(date_val, "strftime"):
                    dates.append(date_val.strftime("%d/%m/%Y"))
                else:
                    dates.append(str(date_val))

        execution_time = time.time() - start_time
        logger.info(
            f"DAO AVAILABLE DATES: {execution_time:.3f}s, returned {len(dates)} dates"
        )
        return dates

    except Exception as e:
        logger.error(f"Error executing available dates query: {e}")
        raise