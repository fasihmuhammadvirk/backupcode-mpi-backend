"""
Shared utilities for invoice_item_mart DAO operations.
"""

import logging
from typing import Dict, Any, Optional, List, Set, Tuple
from sqlalchemy import inspect, String, Text, text
from sqlalchemy.orm import Session
from mpi_backend.database.models.InvoiceItemMart import InvoiceItemMart
from mpi_backend.database.dao.dao_utils import check_table_exists
from mpi_backend.database.schemas.Filters import PriceChangeFilter, PriceChangeType, FilterRequest
from .search_utils import (
    determine_search_mode,
    SearchMode,
    normalize_search_term,
    escape_like_pattern
)


logger = logging.getLogger(__name__)

# Canonical mapping of API comparison operators to SQL operators.
# Keep this in one place so all query builders stay in sync.
COMPARISON_OPERATOR_TO_SQL: Dict[str, str] = {
    'gte': '>=',
    'lte': '<=',
    'eq': '=',
    '=': '=',
    '==': '=',
    'gt': '>',
    'lt': '<',
    'neq': '!='
}

# COALESCE expressions for user-overrideable fields.
# Add a new entry here when adding a new overrideable field — one-line change.
OVERRIDEABLE_COALESCE_EXPRESSIONS: Dict[str, str] = {
    'sheet_name':      "COALESCE(_override_json->>'sheet_name', sheet_name) AS sheet_name",
    'mpi_item':        "COALESCE(_override_json->>'mpi_item', mpi_item) AS mpi_item",
    'mpi_description': "COALESCE(_override_json->>'mpi_description', mpi_description) AS mpi_description",
    'account':         "COALESCE(_override_json->>'account', account) AS account",
    'class_':          "COALESCE(_override_json->>'class_', class_) AS class_",
    'cost':            r"CASE WHEN (_override_json->>'cost') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (_override_json->>'cost')::numeric ELSE COALESCE(current_price, cost) END AS cost",
    'amount':          r"CASE WHEN (_override_json->>'amount') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (_override_json->>'amount')::numeric ELSE amount END AS amount",
    'memo':            "COALESCE(_override_json->>'memo', memo) AS memo",
    'description':     "COALESCE(_override_json->>'description', description) AS description",
    'qty':             r"CASE WHEN (_override_json->>'qty') IS NOT NULL AND (_override_json->>'qty') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (_override_json->>'qty')::numeric ELSE COALESCE(current_qty, qty) END AS qty",
    'customer_job':    "COALESCE(_override_json->>'customer_job', customer_job) AS customer_job",
    'date':            r"CASE WHEN (_override_json->>'date') IS NOT NULL AND (_override_json->>'date') ~ '^\d{2}-\d{2}-\d{4}$' AND TO_CHAR(TO_DATE(_override_json->>'date', 'MM-DD-YYYY'), 'MM-DD-YYYY') = (_override_json->>'date') THEN TO_DATE(_override_json->>'date', 'MM-DD-YYYY') ELSE date END AS date",
    'vendor':          "COALESCE(_override_json->>'vendor', vendor) AS vendor",
    'po_number':       "COALESCE(_override_json->>'po_number', po_number) AS po_number",
    'buyer':           "COALESCE(_override_json->>'buyer', buyer) AS buyer",
}

# Normalized column expressions recomputed from effective (COALESCE'd) values.
# These replace the stale mart-precomputed normalized columns so that overrides are
# reflected at query time without waiting for a mart refresh.
# Mirrors the normalization logic in int__invoice_items_with_normalized_fields.sql.
# buyer_normalized is intentionally absent: the mart computes it from int__buyers'
# canonical buyer_normalized_base (a fuzzy-matched form), not from the raw buyer string.
# Recomputing it here from raw buyer would produce different values for all records,
# causing a regression. It is passed through as a stale column in effective_data instead.
_RECOMPUTED_NORMALIZED_EXPRESSIONS: Dict[str, str] = {
    'mpi_item_normalized':        r"REGEXP_REPLACE(LOWER(SUBSTRING(COALESCE(mpi_item, item), 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS mpi_item_normalized",
    'mpi_description_normalized': r"REGEXP_REPLACE(LOWER(SUBSTRING(COALESCE(mpi_description, description), 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS mpi_description_normalized",
    'description_normalized':     r"REGEXP_REPLACE(LOWER(SUBSTRING(description, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS description_normalized",
    'vendor_search_normalized':   r"REGEXP_REPLACE(LOWER(SUBSTRING(vendor, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS vendor_search_normalized",
    'sheet_name_normalized':      r"CASE WHEN sheet_name IS NULL OR TRIM(sheet_name) = '' THEN 'NO SHEET NAME' ELSE TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(sheet_name, '\)\s*\(', ' - ', 'g'), '[()]', '', 'g'), '\.', '', 'g'), '\s+', ' ', 'g')) END AS sheet_name_normalized",
    'customer_job_normalized':    r"REGEXP_REPLACE(LOWER(SUBSTRING(customer_job, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS customer_job_normalized",
    'po_number_normalized':       r"REGEXP_REPLACE(LOWER(SUBSTRING(po_number, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS po_number_normalized",
}


def _get_allowed_columns() -> Set[str]:
    """
    Get allowed columns from InvoiceItemMart model using SQLAlchemy introspection.

    Returns:
        Set of column names that exist in the model
    """
    mapper = inspect(InvoiceItemMart)
    return {column.key for column in mapper.columns}


def get_text_columns() -> Set[str]:
    """
    Get the set of column names that are string/text based in InvoiceItemMart.
    Used for safely applying NULLIF during sorting.
    """
    mapper = inspect(InvoiceItemMart)
    return {
        column.key for column in mapper.columns 
        if isinstance(column.type, (String, Text))
    }


def _get_normalized_column(column_name: str) -> Optional[str]:
    """
    Get the corresponding normalized column name if it exists in the model.

    Convention: normalized columns are named {column}_normalized

    Args:
        column_name: Original column name

    Returns:
        Normalized column name if it exists, None otherwise
    """
    allowed_columns = _get_allowed_columns()

    # Special case for vendor -> vendor_search_normalized
    if column_name == 'vendor' and 'vendor_search_normalized' in allowed_columns:
        return 'vendor_search_normalized'

    normalized_name = f"{column_name}_normalized"
    return normalized_name if normalized_name in allowed_columns else None


def check_mart_table_exists(db: Session) -> bool:
    """
    Check if the analytics.mart__invoice_items table exists.

    Args:
        db: SQLAlchemy database session

    Returns:
        True if table exists, False otherwise
    """
    # Get schema and tablename from model
    schema = InvoiceItemMart.__table_args__.get("schema") or "analytics"
    tablename = InvoiceItemMart.__tablename__ or "mart__invoice_items"

    return check_table_exists(db, schema, tablename)


def build_base_filtered_query(
    request,
    include_price_data: Optional[bool] = None,
    include_normalized_expressions: bool = False
) -> tuple[str, Dict[str, Any]]:
    """
    Build the base filtered query as a CTE that can be reused across all DAO functions.

    This creates a single source of truth for filtering logic that all DAOs can use.
    Returns a CTE named 'filtered_items' that other queries can SELECT from.

    Args:
        request: FilterRequest Pydantic object with filters, comparison_filters,
                 order_by, color_filters, price_change_filter, compare_all_supplier.

        include_price_data:
            Whether to JOIN analytics.mart__price_increases in normal (non-supplier) mode.
            - None (default): auto-detected — True only when color_filters or
              price_change_filter are present on the request.
            - True / False: explicit override (e.g. supplier-report callers pass True).

        include_normalized_expressions:
            Whether to emit the seven REGEXP_REPLACE ``*_normalized`` columns inside the
            ``filtered_items`` CTE (adds ~300 ms on 280 K rows).
            - False (default): columns are passed through unchanged from the mart table.
              Safe for apply_filters, get_aggregates, and tests.
            - True: callers that filter or order by normalized columns must set this.

    Returns:
        Tuple of (base_query_cte, query_params)
        - base_query_cte: SQL string for the CTE
        - query_params: Dict of parameters to bind to the query
    """
    compare_all_supplier: bool = getattr(request, 'compare_all_supplier', False)

    # Extract filters from FilterRequest
    filter_context = request.filters if request.filters else None
    comparison_filters = request.comparison_filters if request.comparison_filters else None
    color_filters = request.color_filters if hasattr(request, 'color_filters') else None
    price_change_filter = request.price_change_filter if hasattr(request, 'price_change_filter') else None
    search = request.search if hasattr(request, 'search') else ""
    substring_search = request.substring_search if hasattr(request, 'substring_search') else False
    include_voided = getattr(request, 'include_voided', False)

    # Resolve include_price_data: auto-detect from request when caller didn't specify.
    # Only needed in normal mode; supplier mode uses a different price table.
    if include_price_data is None:
        needs_price_data = bool(
            not compare_all_supplier
            and (
                (color_filters and color_filters.colors)
                or price_change_filter
            )
        )
    else:
        needs_price_data = include_price_data

    logger.info(
        f"Building base filtered query - compare_all_supplier: {compare_all_supplier}, "
        f"price_change_filter: {price_change_filter}, "
        f"needs_price_data: {needs_price_data}, "
        f"include_normalized_expressions: {include_normalized_expressions}"
    )

    # Build WHERE conditions using existing helper
    where_conditions, query_params = _build_where_conditions(filter_context, comparison_filters)

    # Color filter targets pi.percentage_increase — only valid in normal mode
    if color_filters and color_filters.colors and not compare_all_supplier:
        color_condition = _build_color_filter_condition(color_filters.colors, query_params)
        if color_condition:
            where_conditions.append(color_condition)

    # In normal mode, apply price_change_filter to pi.percentage_increase in the WHERE
    if price_change_filter and not compare_all_supplier:
        logger.info(f"Applying price_change_filter (normal mode): {price_change_filter}")
        price_change_condition = _build_price_change_filter_condition(
            price_change_filter, query_params, pct_col="pi.percentage_increase"
        )
        logger.info(f"Price change condition generated: {price_change_condition}")
        if price_change_condition:
            where_conditions.append(price_change_condition)

    # Add global search condition if present
    if search:
        search_condition = _build_multi_column_search_condition(search, substring_search, query_params)
        if search_condition:
            # Global search is applied with AND to other filters, but itself contains ORs across columns
            where_conditions.append(search_condition)

    if not include_voided:
        where_conditions.append("iv.ref_no IS NULL")

    # Build WHERE clause
    where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

    logger.info(f"Final WHERE conditions: {where_conditions}")
    logger.info(f"Final WHERE clause: {where_clause}")
    logger.info(f"Query params: {query_params}")

    # Live-join public.invoice_voided so the UI always gets real-time void state.
    # When include_voided=False the WHERE filters out matched voids (iv.ref_no IS NULL).
    # When include_voided=True all rows pass through; iv.invoice_voided_at is exposed.
    # Common JOIN — user_overrides is always required by both modes.
    join_clause = """
        LEFT JOIN public.user_overrides o
            ON mart.invoice_items_id::text = o.record_id AND o.deleted_at IS NULL
        LEFT JOIN public.invoice_voided iv
            ON mart.ref_no = iv.ref_no
           AND mart.date   = iv.date
           AND mart.vendor = iv.vendor
    """

    if compare_all_supplier:
        # Supplier mode: join mart__item_price_comparison for best_price.
        # percentage_increase is derived from best_price.
        join_clause += _build_best_price_join(comparison_filters, filter_context)
        raw_data_price_selects = _build_best_price_select()
        fi_where = _build_supplier_pct_filter_where(price_change_filter, query_params)
    elif needs_price_data:
        # Normal mode with price/color filters: join mart__price_increases.
        join_clause += """
        LEFT JOIN analytics.mart__price_increases pi
            ON mart.invoice_items_id = pi.invoice_items_id
        """
        raw_data_price_selects = """
            pi.percentage_increase,
            pi.previous_price AS previous_cost,
            NULL::numeric AS best_price,
            pi.price_change AS price_difference,
        """
        fi_where = ""
    else:
        # Normal mode without price/color filters: skip the expensive price JOIN.
        # percentage_increase, previous_cost, best_price, price_difference is unused by the caller so sending NULL.
        raw_data_price_selects = """
            NULL::numeric AS percentage_increase,
            NULL::numeric AS previous_cost,
            NULL::numeric AS best_price,
            NULL::numeric AS price_difference,
        """
        fi_where = ""

    # filtered_items CTE: optionally recompute normalized columns from effective values.
    if include_normalized_expressions:
        fi_normalized_selects = f", {', '.join(_RECOMPUTED_NORMALIZED_EXPRESSIONS.values())}"
    else:
        fi_normalized_selects = ""

    # Three-level CTE:
    # 1. raw_data    — mart + joins (including live invoice_voided); WHERE applied here.
    #                  Rows with is_row_deleted=TRUE are excluded here
    # 2. effective_data — applies COALESCE overrides; carries live void columns.
    # 3. filtered_items — optionally recomputes normalized columns from effective values.
    base_cte = f"""
        WITH raw_data AS (
            SELECT
                mart.*,
                mart.rerated_cost AS current_price,
                mart.rerated_qty AS current_qty,
                mart.qty AS original_current_qty,
                mart.cost AS original_cost,
                {raw_data_price_selects}
                o.overrides AS _override_json,
                CASE WHEN o.record_id IS NOT NULL THEN TRUE ELSE FALSE END AS is_overridden,
                iv.invoice_voided_at AS _live_voided_at,
                iv.invoice_voided_by AS _live_voided_by,
                iv.void_reason       AS _live_void_reason,
                CASE WHEN iv.ref_no IS NOT NULL THEN TRUE ELSE FALSE END AS is_voided
            FROM analytics.mart__invoice_items mart
            {join_clause}
            WHERE {where_clause}
              AND COALESCE(o.is_row_deleted, FALSE) = FALSE
        ),
        effective_data AS (
            SELECT
                invoice_items_id, invoice_id, item, ref_no,
                street_number, street_name, city, state,
                zip_code, address_confidence,
                assigned_account, filename, bill, export_status, date_added,
                item_normalized, ref_no_normalized, buyer_normalized,
                line_order, percentage_increase, is_overridden, best_price, 
                previous_cost, price_difference, is_price_rerated, is_voided, original_current_qty, original_cost,
                _live_voided_at  AS invoice_voided_at,
                _live_voided_by  AS invoice_voided_by,
                _live_void_reason AS void_reason,
                {', '.join(OVERRIDEABLE_COALESCE_EXPRESSIONS.values())}
            FROM raw_data
        ),
        filtered_items AS (
            SELECT *{fi_normalized_selects}
            FROM effective_data
            {fi_where}
        )
    """

    return base_cte, query_params

def _build_best_price_join(
    comparison_filters: Optional[List],
    filter_context: Optional[Dict] = None
) -> str:
    """
    Build the LEFT JOIN fragment that attaches cheapest per-item prices from
    ``analytics.mart__item_price_comparison`` to the main query.

    Date range filters from ``comparison_filters`` are pushed into the
    sub-query so the "best price" is scoped to the same period as the main
    query.

    Args:
        comparison_filters: List of ComparisonFilter Pydantic objects or dicts.

    Returns:
        SQL LEFT JOIN fragment (starts with a newline, ready to append).
    """
    # Always exclude zero / negative prices from the best-price computation.
    bp_conditions: List[str] = ["bpc.item_cost > 0"]

    if comparison_filters:
        for i, cf in enumerate(comparison_filters):
            col = cf.column if hasattr(cf, 'column') else cf.get('column')
            if col != 'date':
                continue
            op  = cf.operator if hasattr(cf, 'operator') else cf.get('operator', '=')
            op_sql = COMPARISON_OPERATOR_TO_SQL.get(op, '=')
            # Reuse the same bound parameter that _build_where_conditions already set.
            bp_conditions.append(f"bpc.purchase_date {op_sql} :date_{i}")

    # If the user is filtering the main query for a specific vendor,
    # the "best price" should also be restricted to that same vendor.
    if filter_context and 'vendor' in filter_context:
        v = filter_context['vendor']
        if v is not None:
             if isinstance(v, list) and v:
                 vendor_placeholders = [f":filter_vendor_{i}" for i in range(len(v))]
                 bp_conditions.append(f"bpc.supplier_name IN ({', '.join(vendor_placeholders)})")
             elif not isinstance(v, list):
                 bp_conditions.append("bpc.supplier_name = :filter_vendor")

    bp_where = " AND ".join(bp_conditions)

    bp_subquery = f"""
        (
            SELECT item_mpi_code, MIN(item_cost) AS best_price
            FROM analytics.mart__item_price_comparison bpc
            WHERE {bp_where}
            GROUP BY item_mpi_code
        ) bp"""

    return f"""
        LEFT JOIN {bp_subquery}
            ON bp.item_mpi_code = COALESCE(o.overrides->>'mpi_item', mart.mpi_item)"""


def _build_best_price_select() -> str:
    """
    Return the two SELECT expressions added in supplier-comparison mode:

    1. ``bp.best_price``   — the cheapest known market price for this item.
    2. ``percentage_increase`` — derived as ``(rerated_cost - best_price) / best_price * 100``
       using ``mart.rerated_cost`` as the effective rerated_cost at this stage (user overrides are
       applied one level up in ``effective_data``).  ``NULLIF`` guards against
       division-by-zero; the whole expression evaluates to NULL when no best
       price is available.
    3. ``previous_cost`` — the previous cost of the item (NULL as it is not related to best price)
    4. ``price_difference`` — the absolute difference between the current rerated_cost and the previous cost

    Here using `rerated_cost` as cost after Y & S BOX→EACH issue.

    The trailing comma is intentional: the caller embeds this string between
    other SELECT items inside the ``raw_data`` CTE.

    Returns:
        SQL SELECT fragment (two expressions, trailing comma included).
    """
    return """
            bp.best_price,
            NULL::numeric AS previous_cost,
            CASE
                WHEN bp.best_price IS NOT NULL AND bp.best_price > 0
                     AND mart.rerated_cost IS NOT NULL
                THEN ROUND(
                    ((mart.rerated_cost - bp.best_price) / NULLIF(bp.best_price, 0)) * 100,
                    2
                )
                ELSE NULL
            END AS percentage_increase,
            CASE
                WHEN bp.best_price IS NOT NULL AND
                     CASE
                         WHEN (o.overrides->>'cost') ~ '^-?[0-9]+(\.[0-9]+)?$'
                         THEN (o.overrides->>'cost')::numeric
                         ELSE mart.rerated_cost
                     END IS NOT NULL
                THEN ROUND((
                    CASE
                        WHEN (o.overrides->>'cost') ~ '^-?[0-9]+(\.[0-9]+)?$'
                        THEN (o.overrides->>'cost')::numeric
                        ELSE mart.rerated_cost
                    END - bp.best_price
                )::numeric, 2)
                ELSE NULL
            END AS price_difference,"""


def _build_supplier_pct_filter_where(
    price_change_filter: Optional[PriceChangeFilter],
    query_params: Dict[str, Any],
) -> str:
    """
    Resolve ``price_change_filter`` into a ``WHERE ...`` clause fragment suitable
    for the ``filtered_items`` CTE in supplier-comparison mode.

    Args:
        price_change_filter: Optional PriceChangeFilter; if None an empty string
            is returned so the caller can embed it unconditionally.
        query_params: Mutable dict of bound parameters (modified in place).

    Returns:
        ``"WHERE <condition>"`` string, or ``""`` when no filter is requested.
    """
    if not price_change_filter:
        return ""

    logger.info(f"Applying price_change_filter (compare_all_supplier mode): {price_change_filter}")
    condition = _build_price_change_filter_condition(
        price_change_filter, query_params, pct_col="percentage_increase"
    )
    logger.info(f"Supplier-mode price change condition: {condition}")

    return f"WHERE {condition}" if condition else ""


def _build_color_filter_condition(colors: List[str], query_params: Dict[str, Any]) -> Optional[str]:
    """
    Build WHERE condition for color filters based on percentage_increase thresholds.

    Color mapping:
    - green: percentage_increase > 10
    - orange: percentage_increase BETWEEN 4 AND 10
    - both: percentage_increase > 4

    Args:
        colors: List of color strings (normalized to lowercase by controller)
        query_params: Dict to add parameters to (modified in place)

    Returns:
        SQL WHERE condition string or None
    """
    if not colors:
        return None

    colors_lower = [c.lower() for c in colors]

    # Optimize: if 'both' is present, just use > 4
    if 'both' in colors_lower:
        query_params['color_threshold'] = 4.0
        return "pi.percentage_increase > :color_threshold"

    # Optimize: if both green and orange, equivalent to > 4
    if 'green' in colors_lower and 'orange' in colors_lower:
        query_params['color_threshold'] = 4.0
        return "pi.percentage_increase > :color_threshold"

    # Single color filters
    if 'green' in colors_lower:
        query_params['color_threshold_green'] = 10.0
        return "pi.percentage_increase > :color_threshold_green"

    if 'orange' in colors_lower:
        query_params['color_threshold_orange_min'] = 4.0
        query_params['color_threshold_orange_max'] = 10.0
        return "pi.percentage_increase BETWEEN :color_threshold_orange_min AND :color_threshold_orange_max"

    return None


def _build_price_change_filter_condition(
    price_change_filter: PriceChangeFilter,
    query_params: Dict[str, Any],
    pct_col: str = "pi.percentage_increase",
) -> Optional[str]:
    """
    Build a SQL WHERE condition for price-change filtering.

    Price change types:
    - "all"      : All items WITH price changes (pct_col IS NOT NULL)
    - "increase" : pct_col > 0  (price went up)
    - "decrease" : pct_col < 0  (price went down)

    IMPORTANT: All filters exclude NULL values to ensure only items with
    actual price-change data are returned.

    Optional ``min_percent`` applies an absolute-value threshold.

    Args:
        price_change_filter: PriceChangeFilter Pydantic object.
        query_params: Dict to add bound parameters to (modified in place).
        pct_col: SQL column reference for percentage_increase.
            In normal mode this is ``"pi.percentage_increase"``;
            in supplier-comparison mode it is ``"percentage_increase"``.

    Returns:
        SQL condition string or None.
    """
    if not price_change_filter:
        logger.info("No price_change_filter provided")
        return None

    change_type = price_change_filter.change_type
    min_percent = price_change_filter.min_percent
    max_percent = price_change_filter.max_percent

    logger.info(f"Price change filter - change_type: {change_type}, min_percent: {min_percent}, pct_col: {pct_col}")

    conditions = []

    # Always exclude NULLs — only items with actual price-change data pass through
    conditions.append(f"{pct_col} IS NOT NULL")
    logger.info(f"Adding condition: {pct_col} IS NOT NULL")

    # Direction filter
    if change_type == PriceChangeType.INCREASE:
        conditions.append(f"{pct_col} > 0")
        logger.info(f"Adding condition: {pct_col} > 0")
    elif change_type == PriceChangeType.DECREASE:
        conditions.append(f"{pct_col} < 0")
        logger.info(f"Adding condition: {pct_col} < 0")
    else:
        # PriceChangeType.ALL — NULL exclusion above is the only filter
        logger.info(f"No direction filter for change_type: {change_type} (showing all non-null)")

    # Minimum-percentage threshold (absolute value)
    if min_percent is not None and min_percent > 0:
        query_params['price_change_min_percent'] = min_percent
        if change_type == PriceChangeType.DECREASE:
            conditions.append(f"{pct_col} <= -:price_change_min_percent")
            logger.info(f"Adding min_percent condition for decrease: {pct_col} <= -{min_percent}")
        elif change_type == PriceChangeType.INCREASE:
            conditions.append(f"{pct_col} >= :price_change_min_percent")
            logger.info(f"Adding min_percent condition for increase: {pct_col} >= {min_percent}")
        else:
            conditions.append(f"ABS({pct_col}) >= :price_change_min_percent")
            logger.info(f"Adding min_percent condition for all: ABS({pct_col}) >= {min_percent}")

    # Maximum-percentage threshold (absolute value)
    if max_percent is not None and max_percent > 0:
        query_params['price_change_max_percent'] = max_percent
        if change_type == PriceChangeType.DECREASE:
            # e.g. Decrease + max 10% -> pct IN [-10, 0] -> pct >= -10
            conditions.append(f"{pct_col} >= -:price_change_max_percent")
            logger.info(f"Adding max_percent condition for decrease: {pct_col} >= -{max_percent}")
        elif change_type == PriceChangeType.INCREASE:
            # e.g. Increase + max 10% -> pct IN [0, 10] -> pct <= 10
            conditions.append(f"{pct_col} <= :price_change_max_percent")
            logger.info(f"Adding max_percent condition for increase: {pct_col} <= {max_percent}")
        else:
            # e.g. All + max 10% -> ABS(pct) <= 10
            conditions.append(f"ABS({pct_col}) <= :price_change_max_percent")
            logger.info(f"Adding max_percent condition for all: ABS({pct_col}) <= {max_percent}")

    result = " AND ".join(conditions)
    logger.info(f"Final price change condition: {result}")
    return result


def _build_where_conditions(
    filter_context: Optional[Dict],
    comparison_filters: Optional[List]
) -> tuple[List[str], Dict[str, Any]]:
    """
    Build WHERE conditions and query parameters for filtering.

    Args:
        filter_context: Dictionary of column: value filters
        comparison_filters: List of ComparisonFilter Pydantic objects or dicts

    Returns:
        Tuple of (where_conditions list, query_params dict)
    """
    where_conditions = []
    query_params = {}

    # Apply date range filters
    if comparison_filters:
        for i, cf in enumerate(comparison_filters):
            # Handle both Pydantic objects and dicts
            # TODO: Consolidate the DAOs to always use Pydantic objects
            column = cf.column if hasattr(cf, 'column') else cf.get('column')
            if not column:
                continue
            operator = cf.operator if hasattr(cf, 'operator') else cf.get('operator', '=')
            value = cf.value if hasattr(cf, 'value') else cf.get('value')

            param_name = f"{column}_{i}"
            # Qualify column with table alias to avoid ambiguity with JOIN
            qualified_column = f"mart.{column}"
            operator_sql = COMPARISON_OPERATOR_TO_SQL.get(operator)
            if operator_sql:
                where_conditions.append(f"{qualified_column} {operator_sql} :{param_name}")
                query_params[param_name] = value

    # Apply context filters
    if filter_context:
        allowed_columns = _get_allowed_columns()
        for col, values in filter_context.items():
            # Skip export_status filter - mart table only contains active records
            if col == 'export_status':
                logger.info(f"Skipping export_status filter - mart table pre-filtered to active records")
                continue

            # Validate column against model schema before using in SQL
            if col not in allowed_columns:
                logger.warning(f"Column '{col}' not in InvoiceItemMart model, falling back to ORM")
                raise ValueError(f"Invalid column: {col}")

            # Treat explicit None as "no filter" but allow falsy values like 0
            if values is None:
                continue

            # Validate values type
            if isinstance(values, list):
                # Validate list is not empty and contains valid types
                # Empty list means there's no filter so we want to avoid empty "IN ()" statements
                if not values:
                    continue

                if not all(isinstance(v, (str, int, float, type(None))) for v in values):
                    logger.warning(f"Invalid filter_context values type for {col}")
                    raise TypeError(f"Invalid filter values for {col}")

                # Use override-aware column if field is overrideable
                if col in OVERRIDEABLE_COALESCE_EXPRESSIONS:
                    if col in ('amount', 'cost', 'qty'):
                        qualified_col = f"CASE WHEN (o.overrides->>'{col}') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (o.overrides->>'{col}')::numeric ELSE mart.{col} END"
                    elif col == 'date':
                        qualified_col = f"CASE WHEN (o.overrides->>'{col}') IS NOT NULL AND (o.overrides->>'{col}') ~ '^\\d{{2}}-\\d{{2}}-\\d{{4}}$' AND TO_CHAR(TO_DATE(o.overrides->>'{col}', 'MM-DD-YYYY'), 'MM-DD-YYYY') = (o.overrides->>'{col}') THEN TO_DATE(o.overrides->>'{col}', 'MM-DD-YYYY') ELSE mart.date END"
                    else:
                        qualified_col = f"COALESCE(o.overrides->>'{col}', mart.{col})"
                else:
                    qualified_col = f"mart.{col}"

                param_names = [f"filter_{col}_{i}" for i in range(len(values))]
                placeholders = ", ".join(f":{pname}" for pname in param_names)
                where_conditions.append(f"{qualified_col} IN ({placeholders})")

                for param_name, value in zip(param_names, values):
                    query_params[param_name] = value
            else:
                # Validate single value type
                if not isinstance(values, (str, int, float, type(None))):
                    logger.warning(f"Invalid filter_context value type for {col}")
                    raise TypeError(f"Invalid filter value for {col}")
                # Use override-aware column if field is overrideable
                if col in OVERRIDEABLE_COALESCE_EXPRESSIONS:
                    if col in ('amount', 'cost', 'qty'):
                        qualified_col = f"CASE WHEN (o.overrides->>'{col}') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (o.overrides->>'{col}')::numeric ELSE mart.{col} END"
                    elif col == 'date':
                        qualified_col = f"CASE WHEN (o.overrides->>'{col}') IS NOT NULL AND (o.overrides->>'{col}') ~ '^\\d{{2}}-\\d{{2}}-\\d{{4}}$' AND TO_CHAR(TO_DATE(o.overrides->>'{col}', 'MM-DD-YYYY'), 'MM-DD-YYYY') = (o.overrides->>'{col}') THEN TO_DATE(o.overrides->>'{col}', 'MM-DD-YYYY') ELSE mart.date END"
                    else:
                        qualified_col = f"COALESCE(o.overrides->>'{col}', mart.{col})"
                else:
                    qualified_col = f"mart.{col}"

                param_name = f"filter_{col}"
                where_conditions.append(f"{qualified_col} = :{param_name}")
                query_params[param_name] = values

    return where_conditions, query_params


def _build_multi_column_search_condition(
    search: str,
    substring_search: bool,
    query_params: Dict[str, Any]
) -> Optional[str]:
    """
    Build a multi-column OR condition for global search.
    Reuses the search mode and normalization logic from column-specific search.

    Searches across: item, description, mpi_item, mpi_description, vendor,
    customer_job, ref_no, po_number, bill, buyer, memo, class_, account, sheet_name.

    Args:
        search: Raw search term
        substring_search: Whether to use substring match instead of onword
        query_params: Params dict to add values to

    Returns:
        SQL search condition string or None
    """
    if not search:
        return None

    search_result = determine_search_mode(search, substring_search)
    mode = search_result.mode
    term = search_result.search_term

    # Text columns that support search in Data Review page
    base_columns = [
        'item', 'description', 'mpi_item', 'mpi_description', 'vendor',
        'customer_job', 'ref_no', 'buyer', 'sheet_name', 'po_number'
    ]
    searchable_columns = [(col, _get_normalized_column(col)) for col in base_columns]

    conditions = []

    # 1. Exact Match (Quoted Search)
    if mode == SearchMode.EXACT:
        query_params['global_exact_search'] = term
        for orig, _ in searchable_columns:
            conditions.append(f"mart.{orig} = :global_exact_search")

    # 2. Substring Match
    elif mode == SearchMode.SUBSTRING:
        escaped_term = escape_like_pattern(term)
        normalized_term = normalize_search_term(term)

        query_params.update({
            'global_contains': f"%{escaped_term}%",
            'global_norm_contains': f"%{normalized_term}%"
        })

        for orig, norm in searchable_columns:
            # If normalized column exists, use it with normalized term
            if norm:
                conditions.append(f"mart.{norm} LIKE :global_norm_contains")
            # Always include ILIKE on original column for non-normalized matches
            conditions.append(f"mart.{orig} ILIKE :global_contains")

    # 3. Onward Match (Default)
    else:
        escaped_term = escape_like_pattern(term)
        normalized_term = normalize_search_term(term)

        query_params.update({
            'global_starts': f"{escaped_term}%",
            'global_norm_starts': f"{normalized_term}%"
        })

        for orig, norm in searchable_columns:
            if norm:
                conditions.append(f"mart.{norm} LIKE :global_norm_starts")
            conditions.append(f"mart.{orig} ILIKE :global_starts")

    if not conditions:
        return None

    return f"({' OR '.join(conditions)})"


def _merge_excluded_fragment(
    query_params: Dict[str, Any], excluded_rows_ids: Optional[List[int]]
) -> Tuple[str, Dict[str, Any]]:
    """Non-empty excluded_rows_ids → AND NOT IN (UNNEST array); same pattern as export-all."""
    if not excluded_rows_ids:
        return "", query_params
    merged = {**query_params, "excluded_ids": list(excluded_rows_ids)}
    fragment = (
        "AND invoice_items_id NOT IN (SELECT UNNEST(CAST(:excluded_ids AS BIGINT[])))"
    )
    return fragment, merged


def count_filtered_rows_for_aggregate(
    db: Session,
    request: FilterRequest,
    excluded_rows_ids: Optional[List[int]] = None,
) -> Optional[int]:
    """Row count for current filters (and optional exclusions); None if mart/filter build fails."""
    if not check_mart_table_exists(db):
        return None
    try:
        base_cte, query_params = build_base_filtered_query(request)
    except (ValueError, TypeError, NotImplementedError) as e:
        # Narrow catch: ValueError/TypeError/NotImplementedError are known invalid-filter
        # errors from build_base_filtered_query. Other unexpected exceptions propagate to
        # the caller rather than being silently swallowed.
        logger.warning("count_filtered_rows_for_aggregate: invalid filter: %s", e)
        return None

    excl_sql, query_params = _merge_excluded_fragment(query_params, excluded_rows_ids)
    # base_cte is "WITH ... filtered_items AS (...)" — main query follows without a leading comma.
    sql = f"""
        {base_cte.strip()}
        SELECT COUNT(*) AS cnt
        FROM filtered_items
        WHERE 1=1 {excl_sql}
    """
    try:
        row = db.execute(text(sql), query_params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as e:
        logger.exception("count_filtered_rows_for_aggregate failed")
        return None
