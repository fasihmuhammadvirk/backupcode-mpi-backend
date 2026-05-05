"""
Get paginated unique values from mart__invoice_items table.
"""

import logging
import time
import traceback
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from mpi_backend.database.dao.dao_models import DaoPaginatedResult
from mpi_backend.database.schemas.Filters import FilterRequest
from .search_utils import (
    determine_search_mode,
    SearchMode,
    normalize_search_term,
    escape_like_pattern
)
from .utils import (
    _get_normalized_column,
    check_mart_table_exists,
    build_base_filtered_query
)


logger = logging.getLogger(__name__)


def _build_exact_match_query(
    base_cte: str,
    original_col: str,
) -> str:
    """
    Build SQL query for exact match search (quoted search) using base CTE.

    Args:
        base_cte: Base filtered_items CTE from build_base_filtered_query
        original_col: Column name to search

    Returns:
        SQL query string
    """
    return f"""
        {base_cte},
        distinct_values AS (
            SELECT DISTINCT {original_col}
            FROM filtered_items
            WHERE {original_col} = :exact_search
        ),
        paginated_data AS (
            SELECT
                {original_col},
                ROW_NUMBER() OVER (ORDER BY {original_col} ASC) as row_num,
                COUNT(*) OVER () as total_count
            FROM distinct_values
        )
        SELECT {original_col}, total_count
        FROM paginated_data
        WHERE row_num BETWEEN :start_row AND :end_row
        ORDER BY {original_col} ASC
    """


def _build_ranked_search_query(
    base_cte: str,
    original_col: str,
    normalized_col: Optional[str]
) -> str:
    """
    Build SQL query for ranked fuzzy search with 3-level or 5-level ranking using base CTE.

    Ranking levels (when normalized column exists):
    1. Exact match (case-insensitive)
    2. Starts with
    3. Normalized starts with (handles special chars)
    4. Contains
    5. Normalized contains (fuzzy match)

    Ranking levels (when normalized column doesn't exist):
    1. Exact match (case-insensitive)
    2. Starts with
    3. Contains

    Args:
        base_cte: Base filtered_items CTE from build_base_filtered_query
        original_col: Original column name
        normalized_col: Normalized column name (None if doesn't exist)

    Returns:
        SQL query string
    """
    # Build CASE statement for ranking based on whether normalized column exists
    if normalized_col:
        # 5-level ranking with normalized column
        case_conditions = f"""CASE
                    WHEN {original_col} ILIKE :exact_match THEN 1
                    WHEN {original_col} ILIKE :starts_with THEN 2
                    WHEN {normalized_col} LIKE :normalized_starts THEN 3
                    WHEN {original_col} ILIKE :contains THEN 4
                    WHEN {normalized_col} LIKE :normalized_contains THEN 5
                    ELSE 99
                END"""

        where_or_conditions = f"""{original_col} ILIKE :exact_match
                OR {original_col} ILIKE :starts_with
                OR {normalized_col} LIKE :normalized_starts
                OR {original_col} ILIKE :contains
                OR {normalized_col} LIKE :normalized_contains"""
    else:
        # 3-level ranking without normalized column
        case_conditions = f"""CASE
                    WHEN {original_col} ILIKE :exact_match THEN 1
                    WHEN {original_col} ILIKE :starts_with THEN 2
                    WHEN {original_col} ILIKE :contains THEN 3
                    ELSE 99
                END"""

        where_or_conditions = f"""{original_col} ILIKE :exact_match
                OR {original_col} ILIKE :starts_with
                OR {original_col} ILIKE :contains"""

    return f"""
        {base_cte},
        ranked_values AS (
            SELECT DISTINCT
                {original_col},
                {case_conditions} as relevance_rank,
                LENGTH({original_col}) as result_length
            FROM filtered_items
            WHERE (
                {where_or_conditions}
            )
        ),
        paginated_data AS (
            SELECT
                {original_col},
                relevance_rank,
                result_length,
                ROW_NUMBER() OVER (ORDER BY relevance_rank ASC, result_length ASC, {original_col} ASC) as row_num,
                COUNT(*) OVER () as total_count
            FROM ranked_values
            WHERE relevance_rank < 99
        )
        SELECT {original_col}, total_count
        FROM paginated_data
        WHERE row_num BETWEEN :start_row AND :end_row
        ORDER BY relevance_rank ASC, result_length ASC, {original_col} ASC
    """


def _build_simple_distinct_query(
    base_cte: str,
    original_col: str
) -> str:
    """
    Build SQL query for simple distinct values (no search) using base CTE.

    Args:
        base_cte: Base filtered_items CTE from build_base_filtered_query
        original_col: Column name

    Returns:
        SQL query string
    """
    return f"""
        {base_cte},
        distinct_values AS (
            SELECT DISTINCT {original_col}
            FROM filtered_items
            WHERE {original_col} IS NOT NULL
            AND {original_col} != ''
        ),
        paginated_data AS (
            SELECT
                {original_col},
                ROW_NUMBER() OVER (ORDER BY {original_col} ASC) as row_num,
                COUNT(*) OVER () as total_count
            FROM distinct_values
        )
        SELECT {original_col}, total_count
        FROM paginated_data
        WHERE row_num BETWEEN :start_row AND :end_row
        ORDER BY {original_col} ASC
    """

def _build_substring_search_query(
    base_cte: str,
    original_col: str,
    normalized_col: Optional[str]
) -> str:
    """
    Build SQL query for substring search (match anywhere in string).
    
    Uses case-insensitive ILIKE with escaped special characters.
    
    Args:
        base_cte: Base filtered_items CTE from build_base_filtered_query
        original_col: Original column name
        normalized_col: Normalized column name (None if doesn't exist)
        
    Returns:
        SQL query string
    """
    # Build CASE statement for ranking based on whether normalized column exists
    if normalized_col:
        # 3-level ranking with normalized column
        case_conditions = f"""CASE
                    WHEN {original_col} ILIKE :exact_match THEN 1
                    WHEN {normalized_col} LIKE :normalized_contains THEN 2
                    WHEN {original_col} ILIKE :contains THEN 3
                    ELSE 99
                END"""

        where_or_conditions = f"""{original_col} ILIKE :exact_match
                OR {normalized_col} LIKE :normalized_contains
                OR {original_col} ILIKE :contains"""
    else:
        # 2-level ranking without normalized column
        case_conditions = f"""CASE
                    WHEN {original_col} ILIKE :exact_match THEN 1
                    WHEN {original_col} ILIKE :contains THEN 2
                    ELSE 99
                END"""

        where_or_conditions = f"""{original_col} ILIKE :exact_match
                OR {original_col} ILIKE :contains"""

    return f"""
        {base_cte},
        ranked_values AS (
            SELECT DISTINCT
                {original_col},
                {case_conditions} as relevance_rank,
                LENGTH({original_col}) as result_length
            FROM filtered_items
            WHERE (
                {where_or_conditions}
            )
        ),
        paginated_data AS (
            SELECT
                {original_col},
                relevance_rank,
                result_length,
                ROW_NUMBER() OVER (ORDER BY relevance_rank ASC, result_length ASC, {original_col} ASC) as row_num,
                COUNT(*) OVER () as total_count
            FROM ranked_values
            WHERE relevance_rank < 99
        )
        SELECT {original_col}, total_count
        FROM paginated_data
        WHERE row_num BETWEEN :start_row AND :end_row
        ORDER BY relevance_rank ASC, result_length ASC, {original_col} ASC
    """


def _build_onword_search_query(
    base_cte: str,
    original_col: str,
    normalized_col: Optional[str]
) -> str:
    """
    Build SQL query for onword search (match only when string starts with search term).
    
    Onword search matches ONLY when the search term appears at the START of the string.
    It does NOT match if the search term appears later in the string, even if it starts a word.
    
    Matches:
    - Strings that start with the search term: "abc" matches "abc processing", "abc modeling"
    - Strings that start with the search term: "1/2" matches "1/2 processing company"
    Does NOT match:
    - Strings where search term appears later: "processing" does NOT match "abc processing"
    - Strings where search term appears later: "processing" does NOT match "1/2 processing company"
    - Strings where search term appears in middle of word: "abc" does NOT match "xyzabc"
    
    Args:
        base_cte: Base filtered_items CTE from build_base_filtered_query
        original_col: Original column name
        normalized_col: Normalized column name (None if doesn't exist)
        
    Returns:
        SQL query string
    """
    # For onword search, we ONLY match if the string STARTS with the search term
    # We use ILIKE with starts_with pattern (search_term%)
    # This ensures we only match at the beginning of the string, not in the middle
    
    # Build CASE statement for ranking based on whether normalized column exists
    if normalized_col:
        # 3-level ranking with normalized column
        case_conditions = f"""CASE
                    WHEN {original_col} ILIKE :exact_match THEN 1
                    WHEN {original_col} ILIKE :starts_with THEN 2
                    WHEN {normalized_col} LIKE :normalized_starts THEN 3
                    ELSE 99
                END"""

        where_or_conditions = f"""{original_col} ILIKE :exact_match
                OR {original_col} ILIKE :starts_with
                OR {normalized_col} LIKE :normalized_starts"""
    else:
        # 2-level ranking without normalized column
        case_conditions = f"""CASE
                    WHEN {original_col} ILIKE :exact_match THEN 1
                    WHEN {original_col} ILIKE :starts_with THEN 2
                    ELSE 99
                END"""

        where_or_conditions = f"""{original_col} ILIKE :exact_match
                OR {original_col} ILIKE :starts_with"""

    return f"""
        {base_cte},
        ranked_values AS (
            SELECT DISTINCT
                {original_col},
                {case_conditions} as relevance_rank,
                LENGTH({original_col}) as result_length
            FROM filtered_items
            WHERE (
                {where_or_conditions}
            )
        ),
        paginated_data AS (
            SELECT
                {original_col},
                relevance_rank,
                result_length,
                ROW_NUMBER() OVER (ORDER BY relevance_rank ASC, result_length ASC, {original_col} ASC) as row_num,
                COUNT(*) OVER () as total_count
            FROM ranked_values
            WHERE relevance_rank < 99
        )
        SELECT {original_col}, total_count
        FROM paginated_data
        WHERE row_num BETWEEN :start_row AND :end_row
        ORDER BY relevance_rank ASC, result_length ASC, {original_col} ASC
    """


def get_paginated_unique_values(
    db: Session,
    column_name: str,
    request: FilterRequest,
    page: int = 1,
    limit: int = 20,
    search: str = "",
    substring_search: bool = False
) -> DaoPaginatedResult:
    """
    Query analytics.mart__invoice_items for paginated unique column values.

    Uses pre-computed normalized columns for ultra-fast queries with:
    - 5-level ranking for search relevance
    - Support for all filters via FilterRequest (filters, comparison_filters, color_filters)
    - Efficient pagination using window functions
    - Supports three search modes: onword (default), substring (toggle), exact (quotes)

    Args:
        db: SQLAlchemy database session
        column_name: Column to get unique values from (must be in whitelist)
        request: FilterRequest Pydantic object with filters, comparison_filters, color_filters
        page: Page number (1-indexed)
        limit: Number of results per page
        search: Optional search term (use quotes for exact match)
        substring_search: Whether substring search toggle is enabled (default: False, uses onword search)

    Returns:
        DaoPaginatedResult if successful, None to fall back to invoice_items

    Raises:
        None - returns None on any error to allow fallback
    """
    logger.info(f"DAO: Attempting optimized mart table for column: {column_name}")
    logger.info(f"DAO: Search: {search}")
    logger.info(f"DAO: Request filters: {request.filters}")
    logger.info(f"DAO: Comparison filters: {request.comparison_filters}")
    logger.info(f"DAO: Color filters: {request.color_filters}")

    if not check_mart_table_exists(db):
        raise NotImplementedError("mart__invoice_items not found, using invoice_items fallback")

    try:
        # Check if mart table exists

        start_time = time.time()

        # Build base filtered query CTE (single source of truth).
        # Normalized expressions are required here: the search queries built below
        # filter and order by *_normalized columns (e.g. vendor_search_normalized).
        try:
            base_cte, query_params = build_base_filtered_query(
                request,
                include_normalized_expressions=True,
            )
        except ValueError as e:
            # Invalid filter - fall back
            logger.warning(f"Invalid filter, falling back: {e}")
            raise

        # Use convention-based naming for normalized column (may be None)
        original_col = column_name
        normalized_col = _get_normalized_column(column_name)

        if normalized_col:
            logger.info(f"Using normalized column '{normalized_col}' for search optimization")
        else:
            logger.info(f"No normalized column for '{column_name}', using original column only")

        # Determine query type based on search
        if not search:
            # No search - simple distinct query
            sql_query = _build_simple_distinct_query(base_cte, original_col)
        else:
            # Determine search mode using search_utils
            search_mode_result = determine_search_mode(search, substring_search)
            search_mode = search_mode_result.mode
            search_term = search_mode_result.search_term
            
            logger.info(f"DAO: Search mode determined: {search_mode.value}, search term: '{search_term}'")

            if search_mode == SearchMode.EXACT:
                # Exact match query (quoted search) - case-sensitive
                sql_query = _build_exact_match_query(base_cte, original_col)
                query_params['exact_search'] = search_term

            elif search_mode == SearchMode.SUBSTRING:
                # Substring search - match anywhere in string (case-insensitive)
                sql_query = _build_substring_search_query(base_cte, original_col, normalized_col)
                
                # Escape special characters for ILIKE patterns
                escaped_term = escape_like_pattern(search_term)
                
                # Add ranking parameters (always include original column patterns)
                query_params.update({
                    'exact_match': escaped_term,
                    'contains': f"%{escaped_term}%",
                })

                # Only add normalized search patterns if normalized column exists
                if normalized_col:
                    normalized_search = normalize_search_term(search_term)
                    query_params.update({
                        'normalized_contains': f"%{normalized_search}%",
                    })

            else:  # SearchMode.ONWORD (default)
                # Onword search - match ONLY when string starts with search term (case-insensitive)
                sql_query = _build_onword_search_query(base_cte, original_col, normalized_col)
                
                # Escape special characters for ILIKE patterns
                escaped_term = escape_like_pattern(search_term)
                
                # Add ranking parameters for onword search
                # - exact_match: exact match (case-insensitive)
                # - starts_with: string starts with search term (this is the key - only matches at start)
                query_params.update({
                    'exact_match': escaped_term,
                    'starts_with': f"{escaped_term}%",
                })

                # Only add normalized search patterns if normalized column exists
                if normalized_col:
                    normalized_search = normalize_search_term(search_term)
                    query_params.update({
                        'normalized_starts': f"{normalized_search}%",
                    })


        # Calculate pagination
        start_row = (page - 1) * limit + 1
        end_row = page * limit
        query_params.update({
            'start_row': start_row,
            'end_row': end_row
        })

        # Execute query
        logger.info(f"DAO: Executing optimized mart query for {column_name}")
        result = db.execute(text(sql_query), query_params)
        rows = result.fetchall()

        # Extract results
        data = []
        total_records = 0

        if rows:
            data = [row[0] for row in rows if row[0] is not None]
            total_records = rows[0][1] if rows[0][1] is not None else 0

        total_pages = (total_records + limit - 1) // limit if total_records > 0 else 0

        execution_time = time.time() - start_time
        logger.info(
            f"DAO OPTIMIZED MART QUERY '{column_name}' page {page}: "
            f"{execution_time:.3f}s, {len(data)}/{total_records} items (trimmed + normalized columns)"
        )

        return DaoPaginatedResult(
            data=data,
            page=page,
            limit=limit,
            total_records=total_records,
            total_pages=total_pages,
            source="mart_invoice_items_optimized"
        )

    except Exception as e:
        logger.warning(f"Error using optimized mart table, falling back to invoice_items: {e}")
        logger.debug(f"Error details: {traceback.format_exc()}")
        return None
