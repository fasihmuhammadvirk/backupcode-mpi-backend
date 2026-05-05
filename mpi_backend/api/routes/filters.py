import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Body, BackgroundTasks, status as status_code
from fastapi.responses import ORJSONResponse as JSONResponse
from typing import List, Dict, Optional, Any
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.controllers.UnmappedItems import (
    UnmappedItemsController
)
from mpi_backend.database.controllers.MappingsReviewController import MappingsReviewController
from mpi_backend.database.controllers.SupplierReportController import SupplierReportController
from mpi_backend.database.schemas import (
    FilterRequest, PaginatedInvoiceItemsResponse,
    PriceHistoryRequest, PriceHistoryResponse
)
from mpi_backend.database.schemas.MappingsReview import MappingsReviewItemRequest, PaginatedIsolatedItemsResponse
from mpi_backend.database.schemas.Filters import ColorFilter, SupplierReportRequest, PriceChangeFilter, PriceChangeType
from mpi_backend.database.schemas.InvoiceItems import (
    UnmappedItemsFilterRequest,
    PaginatedUnmappedItemsResponse,
    AvailableDatesResponse,
)
from mpi_backend.database.models.User import User
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.utils.auth.schema_selector import validate_column_access, get_invoice_item_schema
from mpi_backend.utils.pdf_to_excel.formatting_util import (
    export_price_history_to_excel, save_final_data, save_final_data_fast
)
from mpi_backend.utils.s3_utils import upload_export_and_get_url
from mpi_backend.utils.export_utils import export_items_generic
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.database.dao import get_unmapped_items_by_ids, get_unmapped_items_available_dates
import os
import logging
import time
from functools import lru_cache
import hashlib
from datetime import datetime, date
from sqlalchemy import func
from sqlalchemy.sql import text
from math import ceil
import gc
import pandas as pd

router = APIRouter(prefix="/filter", tags=["Filtering Data"])

logger = logging.getLogger(__name__)

# OPTIMIZED: Enhanced caching with resource-aware fallback
cache_store = {}
cache_timestamps = {}
response_cache = {}  # Pre-computed responses
CACHE_TTL = 300  # 5 minutes

# Performance thresholds (disabled for maximum speed)
MAX_CPU_USAGE = 100.0  # No CPU monitoring
MAX_MEMORY_USAGE = 100.0  # No memory monitoring
CACHE_FALLBACK_THRESHOLD = 100.0  # No cache fallback

# Pre-computed static responses for ultra-fast delivery
static_responses = {
    "column_mappings": None,
    "empty_filter_result": None
}


def _get_system_resources():
    """Resource monitoring disabled for maximum performance"""
    return {
        "cpu_percent": 0,
        "memory_percent": 0,
        "available_memory_mb": 8000,
        "monitoring": "DISABLED"
    }


def _should_use_cache_fallback():
    """Cache fallback disabled for maximum performance"""
    return False


def _get_cached_response(cache_key: str):
    """Get cached response - caching enabled for maximum performance"""
    if cache_key in cache_store:
        timestamp = cache_timestamps.get(cache_key, 0)
        if time.time() - timestamp < CACHE_TTL:
            return cache_store[cache_key]
    return None


def _set_cached_response(cache_key: str, data: Any):
    """Set cached response - aggressive caching for maximum performance"""
    cache_store[cache_key] = data
    cache_timestamps[cache_key] = time.time()
    
    # UNLIMITED PERFORMANCE: No cache size limits
    if len(cache_store) > 10000:  # Only cleanup if extremely large
        # Keep only recent items
        cutoff_time = time.time() - CACHE_TTL
        old_keys = [
            k for k, v in cache_timestamps.items() 
            if v < cutoff_time
        ]
        for k in old_keys[:1000]:  # Clean up in batches
            cache_store.pop(k, None)
            cache_timestamps.pop(k, None)


def _warmup_cache():
    """Pre-warm frequently used responses"""
    try:
        # Pre-compute column mappings
        if not static_responses["column_mappings"]:
            static_responses["column_mappings"] = {
                "filename": "Filename",
                "sheet_name": "Sheet Name", 
                "mpi_item": "MPI Item Code",
                "mpi_description": "MPI Description",
                "item": "Item",
                "description": "Description",
                "qty": "Quantity",
                "cost": "Cost",
                "amount": "Amount",
                "date": "Date",
                "ref_no": "Reference Number",
                "po_number": "PO Number",
                "customer_job": "Customer Job",
                "bill": "Bill",
                "vendor": "Vendor",
                "class_": "Class",
                "memo": "Memo",
                "buyer": "Buyer",
                "date_added": "Date Added"
            }
        logger.info("Cache warmed up for ultra-fast responses")
    except Exception as e:
        logger.error(f"Cache warmup failed: {e}")

# Warm up cache on module load
_warmup_cache()


# Optimized JSON response with better error handling
def create_optimized_response(content, status_code: int = 200):
    """Create optimized JSON response with compression and error handling."""
    try:
        # Convert content to JSON-serializable format
        serializable_content = _convert_to_serializable(content)
        
        # Create standard JSONResponse with serializable content
        response = JSONResponse(content=serializable_content, status_code=status_code)
        
        # Add performance headers
        response.headers["X-Optimized"] = "true"
        
        # Add caching headers for filter endpoints
        response.headers["Cache-Control"] = "public, max-age=60"
        
        return response
        
    except Exception as e:
        logger.error(f"Error creating optimized response: {e}")
        # Fallback to standard JSONResponse with basic serialization
        try:
            fallback_content = _convert_to_serializable(content)
            return JSONResponse(content=fallback_content, status_code=status_code)
        except Exception as fallback_error:
            logger.error(f"Fallback serialization failed: {fallback_error}")
            return JSONResponse(content={"error": "Serialization failed"}, status_code=500)


def _convert_to_serializable(obj):
    """Convert SQLAlchemy objects and other non-serializable objects to JSON-serializable format."""
    if obj is None:
        return None
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, list):
        return [_convert_to_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: _convert_to_serializable(value) for key, value in obj.items()}
    elif hasattr(obj, 'model_dump'):
        # Handle Pydantic models (use model_dump to respect field exclusions)
        return obj.model_dump(exclude_unset=False, exclude_none=False)
    elif hasattr(obj, '__dict__'):
        # Handle SQLAlchemy objects (like InvoiceItem)
        result = {}
        for key, value in obj.__dict__.items():
            if not key.startswith('_'):  # Skip SQLAlchemy internal attributes
                result[key] = _convert_to_serializable(value)
        return result
    else:
        # Fallback for other types
        try:
            return str(obj)
        except Exception:
            return None


# Cache for column mappings (static data)
@lru_cache(maxsize=1)
def get_column_mappings():
    """Cached column mappings for better performance."""
    return {
        "filename": "Filename",
        "sheet_name": "Sheet Name",
        "mpi_item": "MPI Item Code",
        "mpi_description": "MPI Description",
        "item": "Item",
        "description": "Description",
        "qty": "Quantity",
        "cost": "Cost",
        "amount": "Amount",
        "date": "Date",
        "ref_no": "Reference Number",
        "po_number": "PO Number",
        "customer_job": "Customer Job",
        "bill": "Bill",
        "vendor": "Vendor",
        "class_": "Class",
        "account": "Account",
        "memo": "Memo",
        "buyer": "Buyer",
        "date_added": "Date Added"
    }


@router.get("/get-locations", response_model=List[str])
def customer_job_filter(
    include_voided: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get unique customer job locations for filtering and dropdown population.
    
    **Summary:**
        Returns a list of unique customer job names from active invoice items.
        This endpoint is optimized for fast response times with aggressive caching
        and is commonly used to populate dropdown filters in the frontend.
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **List[str]**: Array of unique customer job names, sorted alphabetically
        
    **Response Example:**
    ```json
    [
        "Project Alpha",
        "Project Beta", 
        "Project Gamma",
        "Site A Development",
        "Site B Renovation"
    ]
    ```
    
    **Performance Features:**
        - Aggressive caching with 5-minute TTL
        - Ultra-fast raw SQL query optimization
        - Returns ALL customer jobs (no limit)
        - Fallback to cached data on errors
        
    **Notes:**
        - Only returns active invoice items (is_active = true)
        - Results are sorted alphabetically for consistent ordering
        - Cache is automatically warmed up on module load
    """
    
    # DYNAMIC: Bypass static cache to ensure manual overrides are instantly visible
    # We remove the static cache check "customer_job_locations_v2"
    
    try:
        start_time = time.time()
        
        # Return ALL customer jobs
        # We return without any filters, let the user determine if the data is off
        # If we filter by, for example, `customer_job IS NOT NULL` then the user won't
        # know that there are line items which have a missing/null address
        void_filter = "" if include_voided else "WHERE iv.ref_no IS NULL"
        raw_query = text(f"""
            SELECT DISTINCT COALESCE(ov.overrides->>'customer_job', mart.customer_job) AS customer_job
            FROM analytics.mart__invoice_items mart
            LEFT JOIN public.user_overrides ov
                ON mart.invoice_items_id::text = ov.record_id AND ov.deleted_at IS NULL
            LEFT JOIN public.invoice_voided iv
                ON mart.ref_no = iv.ref_no
               AND mart.date   = iv.date
               AND mart.vendor = iv.vendor
            {void_filter}
            ORDER BY customer_job
        """)
        
        result = db.execute(raw_query)
        locations = [row[0] for row in result.fetchall()]
        
        # DYNAMIC: No longer caching this result to ensure manual overrides are instantly visible
        
        execution_time = time.time() - start_time
        logger.info(f"ULTRA-FAST locations: {execution_time:.3f}s, {len(locations)} items")
        
        return create_optimized_response(locations)
        
    except Exception as e:
        logger.error(f"Failed to fetch customer-job address: {e}")
        # Return cached fallback if available
        fallback = cache_store.get("customer_job_locations_fallback", [])
        return create_optimized_response(fallback)


@router.get("/column-mapping")
def column_mappings(current_user: User = Depends(get_current_user)):
    """
    Get column mapping definitions for frontend display.
    
    **Summary:**
        Returns a mapping of database column names to their display names
        used in the frontend interface. This provides consistent column
        labeling across the application.
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict[str, str]**: Mapping of database column names to display names
        
    **Response Example:**
    ```json
    {
        "filename": "Filename",
        "sheet_name": "Sheet Name",
        "mpi_item": "MPI Item Code",
        "mpi_description": "MPI Description",
        "item": "Item",
        "description": "Description",
        "qty": "Quantity",
        "cost": "Cost",
        "amount": "Amount",
        "date": "Date",
        "ref_no": "Reference Number",
        "po_number": "PO Number",
        "customer_job": "Customer Job",
        "bill": "Bill",
        "vendor": "Vendor",
        "class_": "Class",
        "memo": "Memo",
        "buyer": "Buyer",
        "date_added": "Date Added"
    }
    ```
    
    **Performance Features:**
        - Pre-computed static response for microsecond response times
        - No database queries required
        - Cached at module load for instant access
        
    **Notes:**
        - This mapping is used by the frontend to display proper column headers
        - Database column names are mapped to user-friendly display names
        - The response is static and rarely changes
    """
    # Return pre-computed static response (microsecond speed)
    return create_optimized_response(static_responses["column_mappings"])




@router.post("/by-column")
def get_column_data_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    column_name: str = Query(..., description="Column name to get distinct values from"),
    payload: Dict = Body(..., description="Request payload containing search and filter context")
):
    """
    Get ALL distinct values for a specific column (non-paginated).

    **Summary:**
        Returns ALL unique values from a specified column in the invoice_items table with support
        for search functionality and date range filtering. This endpoint is optimized for "Select All"
        operations where you need the complete list of values matching the current filters.

    **Query Parameters:**
        - **column_name** (`str`, required): The database column name to get distinct values from

    **Request Body:**
        - **search** (`str`, optional): Search query supporting three search modes (see `/by-column-paginated` for details)
        - **substring_search** (`bool`, optional, default=false): Enable substring search mode via UI toggle
        - **comparison_filters** (`List`, required): Date range filters using comparison operators
        - **filter_context** (`Dict`, optional): Additional filter context from other columns
        - **color_filters** (`Dict`, optional): Color-based price comparison filter

    **URL Example:**
    ```
    POST /filter/by-column?column_name=vendor
    ```

    **Request Body Example:**
    ```json
    {
        "comparison_filters": [
            {"column": "date", "operator": "gte", "value": "2000-01-01"},
            {"column": "date", "operator": "lte", "value": "2025-08-15"}
        ],
        "search": "BMW",
        "filter_context": {"customer_job": ["Project A"]}
    }
    ```

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **List[str]**: Array of ALL unique values from the specified column matching filters

    **Response Example:**
    ```json
    ["BMW Plumbing", "Flow Mark", "HD Supply", "World Wide"]
    ```

    **Performance Features:**
        - Aggressive caching with 5-minute TTL
        - Uses the same optimized query as paginated endpoint but without LIMIT
        - Suitable for "Select All" operations in dropdowns

    **Notes:**
        - This is the non-paginated version for fetching ALL values
        - Use `/by-column-paginated` for incremental loading during scrolling
        - Results are sorted alphabetically
        - Only returns active invoice items (is_active = true)
    """
    # CRITICAL SECURITY: Validate column access BEFORE executing query
    validate_column_access(column_name, current_user.role)

    start_time = time.time()

    try:
        search = payload.get("search", "").strip() if payload.get("search") else ""
        substring_search = payload.get("substring_search", False)
        raw_comparison_filters = payload.get("comparison_filters", [])
        filter_context = payload.get("filter_context", {}) or {}
        raw_color_filters = payload.get("color_filters")
        raw_price_change_filter = payload.get("price_change_filter")
        compare_all_supplier = payload.get("compare_all_supplier", False)

        # Avoid self-filtering on the same column to expand choices
        if column_name in filter_context:
            filter_context = {
                k: v for k, v in filter_context.items()
                if k != column_name
            }

        # Validate column_name
        if not column_name:
            return create_optimized_response([])

        # Convert color_filters to Pydantic object for validation
        color_filters = None
        if raw_color_filters and raw_color_filters.get("colors"):
            color_filters = ColorFilter(colors=raw_color_filters["colors"])

        # Convert price_change_filter to Pydantic object for validation
        price_change_filter = None
        if raw_price_change_filter:
            try:
                price_change_filter = PriceChangeFilter.from_request(raw_price_change_filter)
            except Exception as e:
                logger.warning(f"Invalid price_change_filter in by-column: {e}")

        # Create cache key
        s_hash = hashlib.md5(search.encode()).hexdigest()[:8]
        ss_hash = "1" if substring_search else "0"
        fc_hash = hashlib.md5(str(filter_context).encode()).hexdigest()[:8]
        cf_hash = hashlib.md5(str(raw_comparison_filters).encode()).hexdigest()[:8]
        color_hash = hashlib.md5(str(color_filters.dict() if color_filters else {}).encode()).hexdigest()[:8]
        price_change_hash = hashlib.md5(str(price_change_filter.dict() if price_change_filter else {}).encode()).hexdigest()[:8]
        c_a_hash = "1" if compare_all_supplier else "0"
        cache_key = f"col_all_v3_{column_name}_{s_hash}_{ss_hash}_{fc_hash}_{cf_hash}_{color_hash}_{price_change_hash}_{c_a_hash}"

        # Check cache first for instant response
        cached_result = _get_cached_response(cache_key)
        if cached_result is not None:
            logger.info(f"INSTANT cache hit: {column_name} all values ({len(cached_result)} items)")
            return create_optimized_response(cached_result)

        # Create controller with current_user for feature flags
        controller = InvoiceItemController(db, current_user=current_user)

        # Use paginated method with a very high limit to get all values
        # This reuses the same optimized query logic
        result = controller.get_data_by_column_name_paginated(
            column_name=column_name,
            page=1,
            limit=50000,  # High limit to get all values
            search=search,
            filter_context=filter_context,
            comparison_filters=raw_comparison_filters,
            color_filters=color_filters,
            price_change_filter=price_change_filter,
            substring_search=substring_search,
            compare_all_supplier=compare_all_supplier
        )

        # Extract just the data array
        all_values = result.get('data', [])

        # Cache the result
        _set_cached_response(cache_key, all_values)

        execution_time = time.time() - start_time

        logger.info(
            f"by-column ALL: {column_name} took "
            f"{execution_time:.3f}s, {len(all_values)} items"
        )

        return create_optimized_response(all_values)

    except Exception as e:
        logger.error(f"Error in by-column endpoint: {e}")
        return create_optimized_response([])


@router.post("/by-column-paginated")
def get_column_data_paginated(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    column_name: str = Query(..., description="Column name to get distinct values from"),
    payload: Dict = Body(..., description="Request payload containing pagination, search, and filter context")
):
    """
    Get paginated and searchable distinct values for a specific column to populate dropdown filters.
    
    **Summary:**
        Returns paginated unique values from a specified column in the invoice_items table with support
        for search functionality and date range filtering. This endpoint is optimized for large datasets 
        and provides efficient pagination with search capabilities.
        
    **Query Parameters:**
        - **column_name** (`str`, required): The database column name to get distinct values from
        
    **Request Body:**
        - **page** (`int`, optional, default=1): Page number for pagination (1-based)
        - **limit** (`int`, optional, default=20): Number of items per page (max 100)
        - **search** (`str`, optional): Search query supporting three search modes:
            
            **Search Mode Precedence:**
            1. **Quoted search** (`"abc"`) → Full text exact match (case-sensitive)
            2. **Substring Search toggle ON** → Substring search (case-insensitive, match anywhere)
            3. **Default** → Onword search (case-insensitive, match only when word starts with search term)
            
            **Search Modes:**
            
            - **Onword Search (Default)**: Matches only when a word begins with the search text
              - Example: `search = "abc"` matches "ABC Plumbing", "ABCD Supplies"
              - Example: `search = "abc"` does NOT match "XYZABC Company" (abc appears inside word)
              - Case-insensitive
            
            - **Substring Search (Toggle)**: Matches anywhere inside the string
              - Enable via `substring_search: true` in request body
              - Example: `search = "abc"` with toggle ON matches "ABC Plumbing", "XYZABC Company", "Super ABCCompany"
              - Case-insensitive
            
            - **Exact Match (Quotes)**: Full text exact match, case-sensitive
              - Use double quotes: `search = "\"abc\""`
              - Example: `search = "\"abc\""` matches "abc" exactly
              - Example: `search = "\"abc\""` does NOT match "ABC", "abcd", "xabc", "abc plumbing"
              - Overrides substring_search toggle
            
            - **Whitespace**: Automatically trimmed before processing
            - **Empty input**: Returns all values (no error)
        - **substring_search** (`bool`, optional, default=false): Enable substring search mode via UI toggle
        - **comparison_filters** (`List`, required): Date range filters using comparison operators
        - **color_filters** (`Dict`, optional): Color-based price comparison filter containing:
            - **colors** (`List[str]`): Array of color codes to filter by:
                - **"green"**: Items with price increase > 10%
                - **"orange"**: Items with price increase 4-9%
                - **"both"**: Items with price increase > 4%
        
    **URL Example:**
    ```
    POST /filter/by-column-paginated?column_name=ref_no
    ```
        
    **Request Body Example (Default Onword Search):**
    ```json
    {
        "comparison_filters": [
            {"column": "date", "operator": "gte", "value": "2000-01-01"},
            {"column": "date", "operator": "lte", "value": "2025-08-15"}
        ],
        "page": 1,
        "limit": 20,
        "search": "abc"
    }
    ```
    Matches: "ABC Plumbing", "ABCD Supplies" (words starting with "abc")
    Does NOT match: "XYZABC Company" (abc appears inside word)
    
    **Request Body Example (Substring Search with Toggle):**
    ```json
    {
        "comparison_filters": [
            {"column": "date", "operator": "gte", "value": "2000-01-01"},
            {"column": "date", "operator": "lte", "value": "2025-08-15"}
        ],
        "page": 1,
        "limit": 20,
        "search": "abc",
        "substring_search": true
    }
    ```
    Matches: "ABC Plumbing", "XYZABC Company", "Super ABCCompany" (anywhere in string)
    
    **Request Body Example (Exact Match with Quotes):**
    ```json
    {
        "comparison_filters": [
            {"column": "date", "operator": "gte", "value": "2000-01-01"},
            {"column": "date", "operator": "lte", "value": "2025-08-15"}
        ],
        "page": 1,
        "limit": 20,
        "search": "\"abc\""
    }
    ```
    Matches: "abc" exactly (case-sensitive)
    Does NOT match: "ABC", "abcd", "xabc", "abc plumbing"
    
    **Request Body Example with Color Filter:**
    ```json
    {
        "comparison_filters": [
            {"column": "date", "operator": "gte", "value": "2024-01-01"},
            {"column": "date", "operator": "lte", "value": "2024-12-31"}
        ],
        "page": 1,
        "limit": 20,
        "search": "pipe",
        "substring_search": false,
        "color_filters": {
            "colors": ["green", "orange"]
        }
    }
    ```
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Paginated response containing:
            - **data** (`List[str]`): Array of unique values from the specified column
            - **page** (`int`): Current page number
            - **limit** (`int`): Number of items per page
            - **total_records** (`int`): Total number of records matching search/filters
            - **total_pages** (`int`): Total number of pages
        
    **Response Example:**
    ```json
    {
        "data": [
            "REF001",
            "REF002",
            "REF003"
        ],
        "page": 1,
        "limit": 20,
        "total_records": 45,
        "total_pages": 3
    }
    ```
    
    **Performance Features:**
        - Ultra-fast raw SQL queries with sub-1 second response times
        - Aggressive caching with 5-minute TTL for repeated requests
        - Database-level pattern matching for search optimization
        - Efficient pagination using window functions
        - Memory-efficient processing for large datasets
        
    **Notes:**
        - Only returns active invoice items (is_active = true)
        - Results are automatically sorted alphabetically
        - Date range filtering is applied first, then search is performed within that range
        - **Search Mode Behavior:**
            - Default: Onword search (matches only when word starts with search term)
            - Toggle: Substring search (matches anywhere in string) - enabled via `substring_search: true`
            - Quotes: Exact match (case-sensitive) - overrides toggle
        - Search whitespace is automatically trimmed
        - Empty search returns all values (no error)
        - Special characters (`%`, `_`) in search terms are automatically escaped for SQL safety
        - Cache is managed automatically for optimal performance
        - Maximum limit is 100 items per page for performance reasons
        - comparison_filters must include date range for proper filtering
        - **Color Filter Feature**: When color_filters is provided, the endpoint filters items based on price increase percentages:
            - Green: Items with price increase > 10%
            - Orange: Items with price increase between 4-9%
            - Both: Items with price increase > 4%
            - Color filtering combines with existing date and search filters
            - Returns distinct values from the specified column for items matching color criteria
    """
    # CRITICAL SECURITY: Validate column access BEFORE executing query
    validate_column_access(column_name, current_user.role)

    start_time = time.time()

    try:
        # Extract and validate parameters from payload
        page = payload.get("page", 1)
        limit = min(payload.get("limit", 20), 100)
        search = payload.get("search", "").strip() if payload.get("search") else ""
        substring_search = payload.get("substring_search", False)
        raw_comparison_filters = payload.get("comparison_filters", [])
        filter_context = payload.get("filter_context", {}) or {}
        raw_color_filters = payload.get("color_filters")
        raw_price_change_filter = payload.get("price_change_filter")
        compare_all_supplier = payload.get("compare_all_supplier", False)

        # Avoid self-filtering on the same column to expand choices
        if column_name in filter_context:
            filter_context = {
                k: v for k, v in filter_context.items()
                if k != column_name
            }

        # Validate column_name
        if not column_name:
            return create_optimized_response({
                "error": "column_name query parameter is required",
                "data": [],
                "page": page,
                "limit": limit,
                "total_records": 0,
                "total_pages": 0
            })

        # Convert color_filters to Pydantic object for validation
        color_filters = None
        if raw_color_filters and raw_color_filters.get("colors"):
            color_filters = ColorFilter(colors=raw_color_filters["colors"])
            
        # Convert price_change_filter to Pydantic object for validation
        price_change_filter = None
        if raw_price_change_filter:
            try:
                price_change_filter = PriceChangeFilter.from_request(raw_price_change_filter)
            except Exception as e:
                logger.warning(f"Invalid price_change_filter in by-column-paginated: {e}")

        # Create cache key (include filter hashes for consistency)
        s_hash = hashlib.md5(search.encode()).hexdigest()[:8]
        ss_hash = "1" if substring_search else "0"
        fc_hash = hashlib.md5(str(filter_context).encode()).hexdigest()[:8]
        cf_hash = hashlib.md5(str(raw_comparison_filters).encode()).hexdigest()[:8]
        color_hash = hashlib.md5(str(color_filters.dict() if color_filters else {}).encode()).hexdigest()[:8]
        price_change_hash = hashlib.md5(str(price_change_filter.dict() if price_change_filter else {}).encode()).hexdigest()[:8]
        c_a_hash = "1" if compare_all_supplier else "0"
        cache_key = f"col_pag_v7_{column_name}_{page}_{limit}_{s_hash}_{ss_hash}_{fc_hash}_{cf_hash}_{color_hash}_{price_change_hash}_{c_a_hash}"

        # Check cache first for instant response
        cached_result = _get_cached_response(cache_key)
        if cached_result is not None:
            logger.info(f"INSTANT cache hit: {column_name} page {page} "
                       f"({len(cached_result.get('data', []))} items)")
            return create_optimized_response(cached_result)

        # Create controller with current_user for feature flags (same pattern as main filter endpoint)
        controller = InvoiceItemController(db, current_user=current_user)

        # Pass raw dicts - controller will convert to Pydantic objects
        result = controller.get_data_by_column_name_paginated(
            column_name=column_name,
            page=page,
            limit=limit,
            search=search,
            filter_context=filter_context,
            comparison_filters=raw_comparison_filters,
            color_filters=color_filters,
            price_change_filter=price_change_filter,
            substring_search=substring_search,
            compare_all_supplier=compare_all_supplier
        )

        # Cache the result aggressively for repeated requests
        _set_cached_response(cache_key, result)
        
        execution_time = time.time() - start_time
        total_items = result.get('total_records', 0)
        returned_items = len(result.get('data', []))
        
        # Log performance metrics
        if execution_time > 1.0:
            logger.warning(
                f"SLOW query: {column_name} page {page} took "
                f"{execution_time:.3f}s"
            )
        else:
            logger.info(
                f"ULTRA-FAST: {column_name} page {page} took "
                f"{execution_time:.3f}s, "
                f"{returned_items}/{total_items} items"
            )
        
        return create_optimized_response(result)
        
    except Exception as e:
        logger.error(f"Error in paginated by-column endpoint: {e}")
        # Return structured error response
        page = payload.get("page", 1)
        limit = min(payload.get("limit", 20), 100)
        return create_optimized_response({
            "error": str(e),
            "data": [],
            "page": page,
            "limit": limit,
            "total_records": 0,
            "total_pages": 0
        })


@router.post("/invoice-items")  # Response model applied dynamically based on role
async def filter_invoice_items(
    request: FilterRequest,
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=1000, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    OPTIMIZED: Filter invoice items with resource-aware execution and efficient pagination
    """
    start_time = time.time()
    
    # Generate cache key for performance (include role for security)
    cache_key = f"filter_{hashlib.md5(str(request.dict()).encode()).hexdigest()}_{page}_{page_size}_{current_user.role}"
    
    try:
        # OPTIMIZED: Use efficient pagination with offset
        offset = (page - 1) * page_size
        
        # ULTRA-FAST: Direct raw SQL execution for maximum performance
        
        # Build optimized raw SQL query with JOINs
        base_sql = """
        SELECT 
            ii.id,
            ii.item,
            ii.description,
            ii.qty,
            ii.cost,
            ii.amount,
            ii.date,
            ii.customer_job,
            ii.vendor,
            ii.class_,
            ii.account,
            ii.is_active,
            ii.export_status,
            i.invoice_date,
            i.supplier_id,
            s.name as supplier_name
        FROM invoice_items ii
        LEFT JOIN invoices i ON ii.invoice_id = i.id
        LEFT JOIN suppliers s ON i.supplier_id = s.id
        WHERE ii.is_active = true
        """
        
        # Build WHERE clause dynamically
        where_conditions = []
        params = {}
        
        if request.start_date and request.end_date:
            where_conditions.append("ii.date BETWEEN :start_date AND :end_date")
            params['start_date'] = request.start_date
            params['end_date'] = request.end_date
        
        if request.supplier_id:
            where_conditions.append("i.supplier_id = :supplier_id")
            params['supplier_id'] = request.supplier_id
        
        if request.customer_job:
            where_conditions.append("ii.customer_job = :customer_job")
            params['customer_job'] = request.customer_job
        
        if request.item_code:
            where_conditions.append("ii.item = :item_code")
            params['item_code'] = request.item_code
        
        if request.min_cost is not None:
            # SQL INJECTION SAFE: Validate numeric input
            try:
                min_cost = float(request.min_cost)
                if min_cost >= 0:  # Non-negative cost
                    where_conditions.append("ii.cost >= :min_cost")
                    params['min_cost'] = min_cost
                else:
                    logger.warning(f"Invalid min_cost: {request.min_cost}")
            except (ValueError, TypeError):
                logger.warning(f"Invalid min_cost type: {type(request.min_cost)}")
        
        if request.max_cost is not None:
            # SQL INJECTION SAFE: Validate numeric input
            try:
                max_cost = float(request.max_cost)
                if max_cost >= 0:  # Non-negative cost
                    where_conditions.append("ii.cost <= :max_cost")
                    params['max_cost'] = max_cost
                else:
                    logger.warning(f"Invalid max_cost: {request.max_cost}")
            except (ValueError, TypeError):
                logger.warning(f"Invalid max_cost type: {type(request.max_cost)}")
        
        # Add WHERE clause if conditions exist
        if where_conditions:
            base_sql += " AND " + " AND ".join(where_conditions)
        
        # Count query for total
        count_sql = f"SELECT COUNT(*) FROM ({base_sql}) as count_query"
        
        # Main query with pagination and ordering
        main_sql = f"""
        {base_sql}
        ORDER BY ii.date DESC, ii.id DESC
        LIMIT :page_size OFFSET :offset
        """
        
        # Add pagination parameters - SQL INJECTION SAFE
        # Validate and sanitize pagination values
        try:
            page_size_int = int(page_size)
            offset_int = int(offset)
            
            # Ensure reasonable limits
            if page_size_int > 0 and page_size_int <= 1000:
                params['page_size'] = page_size_int
            else:
                logger.warning(f"Invalid page_size: {page_size_int}, using default 50")
                params['page_size'] = 50
            
            if offset_int >= 0:
                params['offset'] = offset_int
            else:
                logger.warning(f"Invalid offset: {offset_int}, using default 0")
                params['offset'] = 0
                
        except (ValueError, TypeError):
            logger.warning(f"Invalid pagination parameters: page_size={page_size}, offset={offset}")
            params['page_size'] = 50
            params['offset'] = 0
        
        # Execute count query
        count_result = db.execute(text(count_sql), params)
        total_count = count_result.scalar()
        
        # Execute main query
        main_result = db.execute(text(main_sql), params)
        
        # Convert to response models with role-based filtering
        ItemSchema = get_invoice_item_schema(current_user)
        results = []
        for row in main_result:
            item_dict = {
                'id': row.id,
                'item': row.item,
                'description': row.description,
                'qty': row.qty,
                'cost': row.cost,
                'amount': row.amount,
                'date': row.date,
                'customer_job': row.customer_job,
                'vendor': row.vendor,
                'class_': row.class_,
                'account': row.account,  # Included in dict, filtered by schema
                'is_active': row.is_active,
                'export_status': row.export_status,
                'invoice_date': row.invoice_date,
                'supplier_id': row.supplier_id,
                'supplier_name': row.supplier_name
            }
            # Parse with role-specific schema (auto-excludes restricted fields)
            results.append(ItemSchema(**item_dict))

        # Calculate pagination info
        total_pages = ceil(total_count / page_size) if total_count > 0 else 0
        
        # Build response
        response = PaginatedInvoiceItemsResponse(
            items=results,
            total=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1
        )
        
        # Cache the result for future use
        _set_cached_response(cache_key, response)
        
        # Log performance
        duration = time.time() - start_time
        if duration > 1.0:  # Log slow operations
            logger.warning(f"Slow filter operation: {duration:.2f}s")
        
        return response
        
    except Exception as e:
        logger.error(f"Error in filter_invoice_items: {e}")
        # Return cached result if available, even if expired
        cached_result = _get_cached_response(cache_key)
        if cached_result:
            logger.info("Returning cached result due to error")
            return cached_result
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/invoice-items/stream")
async def filter_invoice_items_stream(
    request: FilterRequest,
    page_size: int = Query(100, ge=1, le=1000, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    OPTIMIZED: Stream filtered invoice items for large datasets
    Uses efficient cursor-based pagination to avoid memory issues
    """
    try:
        # Use optimal page size for performance
        page_size = min(page_size, 200)  # Optimal page size for streaming
        
        # Use streaming response for large datasets
        from fastapi.responses import StreamingResponse
        import json
        
        def generate_stream():
            """Generate streaming response with memory management"""
            try:
                offset = 0
                while True:
                    # Get batch of results using direct SQL for maximum performance
                    # Build optimized raw SQL query with JOINs
                    base_sql = """
                    SELECT 
                        ii.id,
                        ii.item,
                        ii.description,
                        ii.qty,
                        ii.cost,
                        ii.amount,
                        ii.date,
                        ii.customer_job,
                        ii.vendor,
                        ii.class_,
                        ii.account,
                        ii.is_active,
                        ii.export_status,
                        i.invoice_date,
                        i.supplier_id,
                        s.name as supplier_name
                    FROM invoice_items ii
                    LEFT JOIN invoices i ON ii.invoice_id = i.id
                    LEFT JOIN suppliers s ON i.supplier_id = s.id
                    WHERE ii.is_active = true
                    """
                    
                    # Build WHERE clause dynamically
                    where_conditions = []
                    params = {}
                    
                    if request.start_date and request.end_date:
                        where_conditions.append("ii.date BETWEEN :start_date AND :end_date")
                        params['start_date'] = request.start_date
                        params['end_date'] = request.end_date
                    
                    if request.supplier_id:
                        where_conditions.append("i.supplier_id = :supplier_id")
                        params['supplier_id'] = request.supplier_id
                    
                    if request.customer_job:
                        where_conditions.append("ii.customer_job = :customer_job")
                        params['customer_job'] = request.customer_job
                    
                    if request.item_code:
                        where_conditions.append("ii.item = :item_code")
                        params['item_code'] = request.item_code
                    
                    if request.min_cost is not None:
                        where_conditions.append("ii.cost >= :min_cost")
                        params['min_cost'] = request.min_cost
                    
                    if request.max_cost is not None:
                        where_conditions.append("ii.cost <= :max_cost")
                        params['max_cost'] = request.max_cost
                    
                    # Add WHERE clause if conditions exist
                    if where_conditions:
                        base_sql += " AND " + " AND ".join(where_conditions)
                    
                    # Main query with pagination and ordering
                    main_sql = f"""
                    {base_sql}
                    ORDER BY ii.date DESC, ii.id DESC
                    LIMIT :page_size OFFSET :offset
                    """
                    
                    # Add pagination parameters
                    params['page_size'] = page_size
                    params['offset'] = offset
                    
                    # Execute main query
                    main_result = db.execute(text(main_sql), params)
                    
                    # Convert to response models
                    results = []
                    for row in main_result:
                        item_dict = {
                            'id': row.id,
                            'item': row.item,
                            'description': row.description,
                            'qty': row.qty,
                            'cost': row.cost,
                            'amount': row.amount,
                            'date': row.date,
                            'customer_job': row.customer_job,
                            'vendor': row.vendor,
                            'class_': row.class_,
                            'account': row.account,
                            'is_active': row.is_active,
                            'export_status': row.export_status,
                            'invoice_date': row.invoice_date,
                            'supplier_id': row.supplier_id,
                            'supplier_name': row.supplier_name
                        }
                        results.append(item_dict)
                    
                    # Get total count for first batch only
                    if offset == 0:
                        count_sql = f"SELECT COUNT(*) FROM ({base_sql}) as count_query"
                        count_result = db.execute(count_sql, {k: v for k, v in params.items() if k not in ['page_size', 'offset']})
                        total_count = count_result.scalar()
                    else:
                        total_count = 0  # Not needed for subsequent batches
                    
                    if not results:
                        break
                    
                    # Yield results as JSON lines
                    for item in results:
                        yield json.dumps(item.dict()) + "\n"
                    
                    offset += page_size
                    
                    # Memory cleanup after each batch
                    if offset % (page_size * 5) == 0:  # Every 5 batches
                        gc.collect()
                        
            except Exception as e:
                logger.error(f"Error in stream generation: {e}")
                yield json.dumps({"error": str(e)}) + "\n"
        
        # Performance monitoring disabled for maximum speed
        
        return StreamingResponse(
            generate_stream(),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=filtered_items.jsonl"}
        )
        
    except Exception as e:
        logger.error(f"Error in filter_invoice_items_stream: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("")  # Response model applied dynamically based on role
def filter_data(
    request: FilterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10),
    total_hint: Optional[int] = Query(None)
):
    """
    Filter and paginate invoice items with advanced search capabilities.
    
    **Summary:**
        Main filtering endpoint that allows complex queries on invoice items
        with support for multiple filter types, comparison filters, and pagination.
        This is the primary endpoint for searching and filtering invoice data.
        
    **Request Body:**
        - **request** (`FilterRequest`): Complex filter request object containing:
            - **filters** (`List[Filter]`, optional): Array of filter conditions
            - **comparison_filters** (`List[ComparisonFilter]`, optional): Array of comparison filters
            - **color_filters** (`ColorFilter`, optional): Color-based price comparison filter containing:
                - **colors** (`List[str]`): Array of color codes to filter by:
                    - **"green"**: Items with price increase > 10%
                    - **"orange"**: Items with price increase 4-9%
                    - **"both"**: Items with price increase > 4%
            - **order_by** (`List[OrderByFilter]`, optional): Array of ordering criteria
            
    **Query Parameters:**
        - **page** (`int`, default=1): Page number for pagination (1-based)
        - **size** (`int`, default=10): Number of items per page
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **PaginatedInvoiceItemsResponse**: Paginated response containing:
            - **items** (`List[InvoiceItem]`): Array of filtered invoice items
            - **total** (`int`): Total number of items matching filters
            - **page** (`int`): Current page number
            - **size** (`int`): Items per page
            - **total_pages** (`int`): Total number of pages
            - **has_next** (`bool`): Whether there are more pages
            - **has_prev** (`bool`): Whether there are previous pages
            - **performance_metrics** (`Dict`): Performance statistics
            
    **Response Example:**
    ```json
    {
        "items": [
            {
                "id": 123,
                "item": "ABC123",
                "description": "Pipe Fitting",
                "cost": 15.50,
                "amount": 155.00,
                "vendor": "Supplier A",
                "date": "2024-01-15",
                "percentage_increase": 12.5,
                "previous_cost": 10.00,
                "price_difference": 5.50
            }
        ],
        "total": 150,
        "page": 1,
        "size": 10,
        "total_pages": 15,
        "has_next": true,
        "has_prev": false,
        "performance_metrics": {
            "execution_time_seconds": 0.045,
            "total_records": 150,
            "returned_records": 10,
            "cache_hit": false,
            "optimization_level": "ULTRA"
        }
    }
    ```
    
    **Performance Features:**
        - Aggressive caching for simple requests
        - Ultra-fast database queries with optimization
        - Performance metrics included in response
        - Fallback error handling with structured responses
        
    **Filter Types:**
        - **Standard Filters**: Exact matches, ranges, contains, etc.
        - **Comparison Filters**: Compare values between columns
        - **Date Filters**: Date range filtering
        - **Numeric Filters**: Amount, cost, quantity ranges
        - **Color Filters**: Price increase percentage filtering (Green >10%, Orange 4-9%, Both >4%)
        
    **Notes:**
        - Only returns active invoice items (is_active = true)
        - Supports complex nested filter conditions
        - Cache is automatically managed for optimal performance
        - Returns structured error responses on failures
        - **Color Filter Feature**: When color_filters is provided, items are filtered based on price increase percentages and percentage_increase is added to each item in the response
    """
    start_time = time.time()
    
    try:
        # Ultra-aggressive caching for common requests (include role for security)
        color_hash = hashlib.md5(
            str(request.color_filters.dict() if request.color_filters else {}).encode()
        ).hexdigest()[:8] if request.color_filters else "no_color"
        request_fingerprint = f"filter_v4_{hash(str(request.dict()))}_{page}_{size}_{color_hash}_{current_user.role}"
        
        # Check for instant cache hit
        if not request.filters and not request.comparison_filters and not request.color_filters:
            cached_result = _get_cached_response(request_fingerprint)
            if cached_result is not None:
                logger.info(f"INSTANT cache hit: filter page {page}")
                return create_optimized_response(cached_result)

        # Use ultra-optimized controller with current user for feature flags
        controller = InvoiceItemController(db, current_user=current_user)
        filtered_data = controller.apply_filters(request, page, size, total_hint=total_hint)

        # Apply role-based schema filtering
        ItemSchema = get_invoice_item_schema(current_user)
        if 'items' in filtered_data and filtered_data['items']:
            # Parse each item with role-specific schema (auto-excludes restricted fields)
            filtered_data['items'] = [
                ItemSchema.model_validate(item) if hasattr(item, '__dict__')
                else ItemSchema(**item) if isinstance(item, dict)
                else ItemSchema.model_validate(item.dict())
                for item in filtered_data['items']
            ]

        # Cache simple requests aggressively
        if not request.filters and not request.comparison_filters and not request.color_filters and size <= 50:
            _set_cached_response(request_fingerprint, filtered_data)
        
        execution_time = time.time() - start_time
        total_items = filtered_data.get("total", 0)
        returned_items = len(filtered_data.get("items", []))
        
        logger.info(f"ULTRA-FAST filter: {execution_time:.3f}s, "
                   f"{returned_items}/{total_items} items")
        
        # Add performance metrics (same structure maintained)
        if isinstance(filtered_data, dict):
            filtered_data["performance_metrics"] = {
                "execution_time_seconds": round(execution_time, 3),
                "total_records": total_items,
                "returned_records": returned_items,
                "cache_hit": False,
                "optimization_level": "ULTRA"
            }
        
        return create_optimized_response(filtered_data)
        
    except Exception as e:
        logger.exception(f"Error in filter endpoint")
        # Return structured error response
        error_response = {
            "items": [],
            "total": 0,
            "page": page,
            "size": size,
            "total_pages": 0,
            "has_next": False,
            "has_prev": False,
            "error": str(e)
        }
        return create_optimized_response(error_response, 500)


@router.post("/export-pdfs")
def export_filtered_pdfs(
        request: FilterRequest,
        background_tasks: BackgroundTasks,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Download PDFs for all filtered invoice items as a single ZIP file.

    **Summary:**
        Identifies all unique invoices associated with the filtered items,
        downloads their PDFs from S3, creates a ZIP archive, and uploads it
        back to S3 for the user to download.
    """
    logger.info(f"Initiating PDF export for filtered items")
    try:
        # Generate a unique export ID
        export_id = str(uuid.uuid4())
        export_status_file = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/status_{export_id}.json'

        # Create status file indicating processing
        os.makedirs(f'{INVOICE_DOWNLOAD_FOLDER}/Exports/', exist_ok=True)
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'processing',
                'export_id': export_id,
                'requested_by_user_id': str(current_user.id),
                'started_at': datetime.now().isoformat(),
                'message': 'Preparing PDF export task...'
            }, f)

        # Add background task
        controller = InvoiceItemController(db, current_user=current_user)
        background_tasks.add_task(
            controller.process_pdf_export_in_background,
            export_id=export_id,
            request=request,
            export_status_file=export_status_file
        )

        # Return immediately with export ID
        return {
            "export_id": export_id,
            "status": "processing",
            "message": "PDF export is being processed in the background. Use the export_id to check status.",
            "status_endpoint": f"/invoice-items/export-status/{export_id}"
        }

    except Exception as e:
        logger.error(f"PDF export initiation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to initiate PDF export.")


@router.post("/price-difference")
def get_price_difference(request: FilterRequest, db: Session = Depends(get_db),
                         # token: str = Depends(JWTBearer()),
                page: int = Query(1, ge=1),
                size: int = Query(10),
                total_hint: Optional[int] = Query(None)):
    """
    Calculate price differences for filtered invoice items.
    
    **Summary:**
        Analyzes price changes for items by comparing each purchase with the most recent 
        previous purchase of the same item from the same supplier. This provides a more 
        realistic view of price trends by showing immediate price changes between consecutive purchases.
        
    **Request Body:**
        - **request** (`FilterRequest`): Filter criteria to select items for analysis
        
    **Query Parameters:**
        - **page** (`int`, default=1): Page number for pagination (1-based)
        - **size** (`int`, default=10): Number of items per page
        
    **Authentication:**
        - Currently disabled (commented out JWT token requirement)
        
    **Returns:**
        - **List[Dict]**: Array of price difference calculations containing:
            - **item** (`str`): Item code with supplier suffix
            - **id** (`int`): Invoice item ID
            - **percentage_increase** (`float`): Price increase percentage from previous purchase
            
    **Response Example:**
    ```json
    [
        {
            "item": "ABC123-B",
            "id": 123,
            "percentage_increase": 15.5
        },
        {
            "item": "XYZ789-F", 
            "id": 456,
            "percentage_increase": -5.2
        }
    ]
    ```
    
    **Performance Features:**
        - Caching for repeated requests with 5-minute TTL
        - Supplier-specific price comparison calculations
        - Optimized database queries for large datasets
        
    **Calculation Method:**
        - Current Price: Price of the current purchase
        - Previous Price: Price of the most recent previous purchase of the same item from the same supplier
        - Formula: ((current_price - previous_price) / previous_price) * 100
        - First purchase of an item shows "N/A" (no previous purchase to compare)
        - Uses supplier-specific comparison for accuracy (same item, same supplier)
        - Handles items with no previous purchase data gracefully (returns "N/A")
        
    **Notes:**
        - Positive percentage indicates price increased from the previous purchase
        - Negative percentage indicates price decreased from the previous purchase
        - Shows immediate price change between consecutive purchases
        - Items without previous purchase data show "N/A"
        - Cache key is based on request parameters and pagination
        - Returns empty array if no items found or calculation fails
    """
    import time
    start_time = time.time()
    
    # Create a cache key based on the request parameters
    cache_key_data = {
        "request_filters": request.dict() if hasattr(request, 'dict') else str(request),
        "page": page,
        "size": size
    }
    cache_key = f"price_diff_{hashlib.md5(str(cache_key_data).encode()).hexdigest()}"
    
    # Check cache first
    cached_result = _get_cached_response(cache_key)
    if cached_result is not None:
        logger.info(f"Returning cached price difference result for page {page}")
        return cached_result
    
    logger.info(f"Computing price difference for page {page}, size {size}")
    
    try:
        # Get filtered data
        filtered_data = InvoiceItemController(db).apply_filters(request, page, size, total_hint=total_hint)
        controller = InvoiceItemController(db)
        
        # Extract item codes and vendor info for supplier-specific monthly comparison
        item_vendor_id_pairs = []
        
        for invoice_item in filtered_data["items"]:
            item = invoice_item.item
            vendor = invoice_item.vendor
            item_id = invoice_item.id
            
            item_vendor_id_pairs.append((item, vendor, item_id))

        if not item_vendor_id_pairs:
            result = []
        else:
            # Calculate price increase with supplier-specific method
            price_increase = controller.calculate_price_increase(
                item_numbers=None, 
                item_vendor_pairs=item_vendor_id_pairs
            )

            result = []
            for i, (item, percentage) in enumerate(price_increase):
                if i < len(item_vendor_id_pairs):
                    item_code, vendor, item_id = item_vendor_id_pairs[i]
                    result.append({
                        "item": item_code,
                        "id": item_id,
                        "percentage_increase": percentage
                    })
        
        # Cache the result for future requests
        _set_cached_response(cache_key, result)
        
        processing_time = time.time() - start_time
        logger.info(f"Price difference calculation completed in {processing_time:.2f}s for {len(result)} items")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in price difference calculation: {str(e)}")
        # Return empty result instead of raising exception for better UX
        return []


@router.post("/price-history", response_model=List[PriceHistoryResponse])
def get_price_history(
    request: PriceHistoryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get price history for a specific item and vendor.
    
    **Summary:**
        Retrieves historical price data for a specific item from a specific vendor.
        This helps track price changes over time and identify pricing trends.
        
    **Request Body:**
        - **request** (`PriceHistoryRequest`): Object containing:
            - **item_number** (`str`, required): The item code to get history for
            - **vendor** (`str`, required): The vendor/supplier name
            - **description** (`str`, optional): Item description for context
            
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **List[PriceHistoryResponse]**: Array of price history records containing:
            - **date** (`str`): Date of the price record
            - **price** (`float`): Price at that date
            - **quantity** (`int`): Quantity purchased
            - **amount** (`float`): Total amount for that transaction
            
    **Response Example:**
    ```json
    [
        {
            "date": "2024-01-15",
            "price": 15.50,
            "quantity": 10,
            "amount": 155.00
        },
        {
            "date": "2024-02-20", 
            "price": 16.25,
            "quantity": 5,
            "amount": 81.25
        }
    ]
    ```
    
    **Validation:**
        - Both item_number and vendor are required and cannot be empty
        - Returns 400 error for invalid input parameters
        - Returns empty array if no price history found
        
    **Error Codes:**
        - **400**: Invalid input parameters (missing or empty item_number/vendor)
        - **500**: Internal server error during data retrieval
        
    **Notes:**
        - Results are sorted by date (oldest first)
        - Only returns records for the exact item_number and vendor combination
        - Returns empty array instead of 404 for better frontend handling
        - Logs detailed information for debugging purposes
    """
    try:
        item_label = request.item_number or request.mpi_item
        logger.info(f"Price history request - Item: {item_label}, Vendor: {request.vendor}")

        # Get price history from controller
        price_history = InvoiceItemController(db).get_price_history(request)

        # Log result for debugging
        logger.info(f"Price history response - Found {len(price_history)} records")

        if not price_history:
            logger.warning(f"No price history found for item: {item_label}, vendor: {request.vendor}")
            return []

        return price_history

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error in price history endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve price history: {str(e)}"
        )

@router.post("/download-price-history")
def download_price_history(
    request: PriceHistoryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Export price history to Excel file and return download URL.
    
    **Summary:**
        Retrieves price history for a specific item and vendor, exports it to
        an Excel file, uploads it to S3, and returns a presigned download URL.
        
    **Request Body:**
        - **request** (`PriceHistoryRequest`): Object containing:
            - **item_number** (`str`, required): The item code to get history for
            - **vendor** (`str`, required): The vendor/supplier name
            - **description** (`str`, optional): Item description for context
            
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **str**: Presigned S3 URL for downloading the Excel file
        
    **Response Example:**
    ```json
    "https://s3.amazonaws.com/bucket/Exports/price_history_ABC123_SupplierA_2024-12-19.xlsx?AWSAccessKeyId=..."
    ```
    
    **Excel File Contents:**
        The Excel file will contain the following columns:
        - Date
        - Price
        - Quantity
        - Amount
        - Item Number
        - Vendor
        - Description
        
    **Process Flow:**
        1. Retrieves price history data from database
        2. Exports data to Excel format
        3. Uploads file to S3 bucket
        4. Generates presigned download URL
        5. Returns URL for immediate download
        
    **Notes:**
        - File is stored in S3 with timestamp for uniqueness
        - Presigned URL has limited expiration time
        - Excel file includes all price history records for the item/vendor
        - File is automatically cleaned up by S3 lifecycle policies
    """
    price_history = InvoiceItemController(db).get_price_history(request)

    try:
        exported_file_path = export_price_history_to_excel(price_history)
        return upload_export_and_get_url(exported_file_path)
    except Exception as exc:
        logger.exception("Failed to generate or upload price history export")
        raise HTTPException(
            status_code=500,
            detail="Failed to upload price history export",
        ) from exc


@router.post("/get_aggregates")
def get_aggregates(
    request: FilterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get aggregated statistics for filtered invoice items.

    **Summary:**
        Calculates summary statistics (totals, averages, counts) for invoice items
        that match the specified filter criteria. This provides quick insights into
        the filtered dataset without loading all individual records.

    **Request Body:**
        - **request** (`FilterRequest`): Filter criteria to select items for aggregation

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **Dict**: Aggregated statistics containing:
            - **total_amount** (`float`): Sum of all amounts
            - **total_qty** (`int`): Sum of all quantities
            - **average_cost** (`float`): Average cost per item
            TODO: Confirm that we return these (or if we should):
            - **item_count** (`int`): Number of unique items
            - **invoice_count** (`int`): Number of invoices
            - **supplier_count** (`int`): Number of unique suppliers

    **Response Example:**
    ```json
    {
        "total_amount": 125000.50,
        "total_quantity": 1500,
        "average_cost": 83.33,
        "item_count": 45,
        "invoice_count": 25,
        "supplier_count": 8
    }
    ```

    **Performance Features:**
        - Caching for repeated requests with 5-minute TTL
        - Optimized database queries using aggregation functions
        - Performance monitoring and logging

    **Aggregation Types:**
        - **Sum**: Total amounts, quantities
        - **Average**: Cost per item
        - **Count**: Unique items, invoices, suppliers
        - **Min/Max**: Price ranges, date ranges

    **Notes:**
        - Only includes active invoice items (is_active = true)
        - Cache key is based on request hash for optimal performance
        - Returns structured error responses on calculation failures
        - Performance metrics are logged for monitoring
    """
    start_time = time.time()

    try:
        # NOTE: Removed Caching cause for voided items for same filter Aggregation result is different
        # Cache key for aggregates
        # request_hash = hashlib.md5(request.json().encode()).hexdigest()
        # cache_key = f"aggregates_{request_hash}"
        #
        # # Check cache
        # cached_result = _get_cached_response(cache_key)
        # if cached_result is not None:
        #     logger.info("Returning cached aggregates")
        #     return create_optimized_response(cached_result)

        controller = InvoiceItemController(db, current_user=current_user)
        aggregates = controller.get_aggregates(request)

        # Cache the result
        # _set_cached_response(cache_key, aggregates)

        logger.info(f"get_aggregates took {time.time() - start_time:.2f}s")
        return create_optimized_response(aggregates)

    except Exception as _:
        logger.exception("Error in get_aggregates")
        raise HTTPException( status_code=500, detail="Aggregates calculation failed")


@router.post("/aggregates-by-address-and-sheet")
def get_aggregates_by_address_and_sheet(
    address: Optional[str] = Query(None, description="Optional customer_job address to filter by"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get aggregated costs by address (customer_job) and sheet_name category with comparisons to averages.

    **Summary:**
        Calculates cost aggregations grouped by customer job address and sheet_name category.
        - When NO address parameter is provided: Returns only global statistics (category averages and grand total)
        - When address parameter IS provided: Returns detailed breakdown for that specific address plus global statistics

        Global statistics always calculated across ALL addresses:
        - Average amount per address for each category
        - Grand total across all addresses

    **Query Parameters:**
        - **address** (`str`, optional): Customer job address to filter by. If provided, returns
          detailed data for only that address. If omitted, returns only global statistics.

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        Response structure varies based on whether address parameter is provided:  

        **When address is NOT provided:**  
        ```json
        {
            "category_averages": {
                "Sheet A": "153.47",
                "Sheet B": "421.85"
            },
            "grand_total": "149,859.38"
        }
        ```

        **When address IS provided:**
        ```json
        {
            "data": {
                "Project Alpha": {
                    "address": "Project Alpha",
                    "categories": {
                        "Sheet A": {
                            "sheet_name": "Sheet A",
                            "total_amount": "368.00",
                            "category_average": "153.47",
                            "difference_from_average": "214.53",
                            "percentage_difference": 139.79
                        }
                    },
                    "address_total": "1,587.61"
                }
            },
            "category_averages": {
                "Sheet A": "153.47",
                "Sheet B": "421.85"
            },
            "grand_total": "149,859.38"
        }
        ```

    **Response Fields:**
        - **category_averages** (`Dict[str, str]`): Average amount per address for each sheet_name (always global, across ALL addresses)
        - **grand_total** (`str`): Total sum across ALL addresses (always global)
        - **data** (`Dict[str, AddressAggregate]`, only when address provided): Detailed breakdown for the specified address containing:
            - **address** (`str`): The address name
            - **categories** (`Dict[str, SheetCategoryAggregate]`): Breakdown by sheet_name with comparisons
            - **address_total** (`str`): Total for this address across all categories

    **Request Examples:**

    1. **Global statistics only** (no address parameter):
    ```bash
    POST /filter/aggregates-by-address-and-sheet
    ```
    Returns: category_averages and grand_total only

    2. **Specific address details** (with address parameter):
    ```bash
    POST /filter/aggregates-by-address-and-sheet?address=Project%20Alpha
    {
        "filters": {},
        "comparison_filters": []
    }
    ```
    Returns: data (for that address), category_averages, and grand_total

    **Performance Features:**
        - Caching for repeated requests with 5-minute TTL (cache key includes address param)
        - Single optimized database query for per-address category totals
        - Python-level aggregation for category averages (sum of per-address totals / count of addresses)
        - Optimized amount string-to-float conversion with validation
        - Performance monitoring and logging

    **Calculation Details:**
        - **Category Average**: (Sum of per-address totals for category) / (Number of addresses with that category)
        - **Total Amount**: Sum of all invoice item amounts for (address, sheet_name) pair
        - **Difference**: (address total) - (global category average per address)
        - **Percentage**: ((difference) / (global category average)) × 100
        - **Grand Total**: Sum of all amounts across ALL addresses (always global)

    **Notes:**
        - Only includes active invoice items (is_active = true)
        - Address parameter is optional - omit to get ONLY global statistics
        - Category averages represent average per address (not total across all addresses)
        - Category averages and grand_total are ALWAYS calculated across ALL addresses for comparison
        - Null or empty sheet_names are grouped as "(No Sheet Name)"
        - Difference values: no sign = positive, minus sign = negative
        - Supports optional filtering by date ranges, vendors, etc.
        - Returns structured error responses on calculation failures
    """
    start_time = time.time()

    try:
        # Cache key for aggregates by address and sheet (include address param)
        address_param = address or "all"
        cache_key = f"aggregates_by_address_sheet_{address_param}"

        # Check cache
        cached_result = _get_cached_response(cache_key)
        if cached_result is not None:
            address_msg = f"for '{address}'" if address else "for all addresses"
            logger.info(f"Returning cached aggregates by address and sheet {address_msg}")
            return create_optimized_response(cached_result)

        controller = InvoiceItemController(db)
        aggregates = controller.get_aggregates_by_address_and_sheet(address=address)

        # Cache the result
        _set_cached_response(cache_key, aggregates)

        execution_time = time.time() - start_time
        address_msg = f"for '{address}'" if address else "for all addresses"
        logger.info(f"get_aggregates_by_address_and_sheet took {execution_time:.2f}s {address_msg}")

        return create_optimized_response(aggregates)

    except Exception as e:
        logger.error(f"Error in get_aggregates_by_address_and_sheet: {e}")
        # TODO: Add error codes so we know what type of error happened
        raise HTTPException(status_code=500, detail=f"Aggregates by address and sheet calculation failed")


@router.post("/unmapped-items", response_model=PaginatedUnmappedItemsResponse)
def get_unmapped_items(
    request: UnmappedItemsFilterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page")
):
    """
    Retrieve unique unmapped or temporary items with advanced filtering, search, and ordering.

    **Summary:**
        Returns a paginated, de-duplicated list of invoice items based on the specified filter type, with support for search and flexible ordering. Items are grouped by supplier + item code, with full item codes including supplier suffixes for distinction (e.g., ABC-B for BMW, ABC-F for Flow Mark).

    **Request Body:**

    - **item_type** (`str`, required):
        - "temporary": Items with `sheet_name` and either `mpi_item_id` or `mpi_description` is "No Match" or starts with "UIDI"
        - "unmapped": ALL items with either `mpi_item_id` or `mpi_description` is "No Match" or starts with "UIDI" (regardless of sheet_name)
        - "no_temporary": Items with NO `sheet_name` and either `mpi_item_id` or `mpi_description` is "No Match" or starts with "UIDI"
    - **date_from** (`str`, optional): Start date filter (YYYY-MM-DD)
    - **date_to** (`str`, optional): End date filter (YYYY-MM-DD)
    - **date_history** (`str`, optional): Date added filter (YYYY-MM-DD). Matches COALESCE(date_added, date) - i.e. the date the item first entered the system, not the invoice date.
    - **supplier_names** (`List[str]`, optional): List of supplier names to filter by
    - **search** (`str`, optional): Search term for item code or description
    - **order_by** (`List[dict]`, optional): List of ordering criteria, e.g. `[{"column": "amount", "order": "desc"}]`. If not provided, defaults to descending order by `amount` (highest amounts first).

    **Query Parameters:**

    - **page** (`int`, default=1): Page number (1-based)
    - **size** (`int`, default=10): Number of items per page

    **Request Example:**

    ```json
    {
      "item_type": "unmapped",
      "date_from": "2024-01-01",
      "date_to": "2024-12-31",
      "supplier_names": ["BMW Plumbing Supplies"],
      "search": "006-ST4",
      "order_by": [
        {"column": "amount", "order": "desc"},
        {"column": "supplier", "order": "asc"}
      ]
    }
    ```

    **Response Example:**

    ```json
    {
      "items": [
        {
          "original_item_id": "006-ST4-B",
          "original_description": "Pipe Fitting 3/4 inch",
          "cost": "15.50",
          "amount": "155.00",
          "quantity": 10,
          "sheet_name": "Sheet X",
          "supplier": "BMW Plumbing Supplies"
        }
      ],
      "total_count": 1,
      "page": 1,
      "size": 10,
      "pages": 1
    }
    ```

    **Response Fields:**

    - **items** (`List[object]`): List of unique items per supplier based on filter type
        - **original_item_id** (`str`): Item code with supplier suffix (e.g., "ABC-123-B")
        - **original_description** (`str`): Original item description
        - **cost** (`str`): Unit cost of the item (formatted as string)
        - **amount** (`str`): Total amount calculated as cost × quantity (formatted as string)
        - **quantity** (`int`): Quantity of the item
        - **sheet_name** (`str`): Google sheet name (null/empty for unmapped)
        - **supplier** (`str`): Supplier/vendor name
    - **total_count** (`int`): Total number of unique items found
    - **page** (`int`): Current page number
    - **size** (`int`): Items per page
    - **pages** (`int`): Total number of pages

    **Filter Type Details:**
    - **temporary**: Items with sheet_name AND (No Match or UIDI) - for items being processed
    - **unmapped**: ALL items with (No Match or UIDI) regardless of sheet_name - comprehensive view
    - **no_temporary**: Items with NO sheet_name AND (No Match or UIDI) - truly unmapped items

    **Notes:**
    - Items are grouped by supplier + cleaned item code (same item from different suppliers are treated as separate items)
            - Full item codes with supplier suffixes are used to distinguish items: -B (BMW), -F (Flow Mark), -W (World Wide), etc.
    - Search is case-insensitive and matches both item code and description
    - Ordering supports multiple columns; default is descending by `amount` (highest amounts first)
    - Only unique items per supplier are returned in the response
    - Amount is calculated as cost × quantity for each item (rounded to 3 decimal places)
    - If `order_by` is not provided, items are sorted by `amount` in descending order
    """

    logger.info("Calling unmaped controller")
    
    # Initialize controller
    controller = UnmappedItemsController(db)
    
    # Get all unmapped items first (we'll filter by cleaned item_ids)
    # Use "unmapped" to get all items regardless of sheet_name status
    all_items_result = controller.get_unmapped_items(
        item_type=request.item_type,  # Get all unmapped items regardless of sheet_name
        date_from=request.date_from,
        date_to=request.date_to,
        date_history=request.date_history,
        supplier_names=request.supplier_names,
        search=request.search,
        order_by=request.order_by,
        page=page,
        size=size,
        group_by=request.group_by
    )

    return all_items_result


@router.post("/unmapped-items/isolate")
def isolate_unmapped_items(
    request: MappingsReviewItemRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Isolate unmapped item for review by adding it to the MappingsReviewItem table.

    **Summary:**
        Takes a list of items and their proposed mappings/reasons and stores them
        in a separate table for review.

    **Request Body:**
        - **item** (`MappingsReviewItemRequest`): Item to isolate, containing:
            - **vendor** (`str`): Vendor/Supplier name
            - **item_id** (`str`): Original item ID from the supplier
            - **reason** (`str`): Reason for review
            - **map_to_item** (`str`): Proposed MPI item code

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **Dict**: Success status

    **Response Example:**
    ```json
    {
      "success": true,
      "message": "Successfully isolated item-id for review.",
    }
    ```

    **Notes:**
        - Items are associated with the current user who requested the isolation
        - The `created_at` timestamp is automatically set to the current UTC time
        - Useful for workflow management between standard users and reviewers
    """
    logger.info(f"Isolating item: {request.item_id} for review (User: {current_user.id})")
    
    try:
        controller = MappingsReviewController(db)
        result = controller.isolate_items(request, current_user)
        return create_optimized_response(result)
    except Exception as e:
        logger.error(f"Failed to isolate items: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error"
        )


@router.get("/unmapped-items/isolate", response_model=PaginatedIsolatedItemsResponse)
def get_isolated_unmapped_items(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1),
    status: str = Query("all", description="Filter by status: 'all', 'pending', or 'done'"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve paginated list of items isolated for review.

    **Summary:**
        Returns items previously flagged for review. Each item is joined with the
        latest metadata from the analytics mart (mapping_type, cost, amount) to 
        ensure the review page displays the most current information.

    **Query Parameters:**
        - **page** (`int`): Page number (default: 1)
        - **size** (`int`): Number of items per page (default: 10)

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **PaginatedIsolatedItemsResponse**: List of isolated items with pagination metadata

    **Notes:**
        - Results are sorted by isolation date (newest first)
        - Metadata like `mapping_type` and `amount` are fetched dynamically from the mart
    """
    logger.info(f"Retrieving isolated items (Page: {page}, Size: {size}) for user {current_user.id}")

    try:
        controller = MappingsReviewController(db)
        result = controller.get_isolated_items(page, size, status)
        return create_optimized_response(result)
    except Exception as e:
        logger.error(f"Failed to retrieve isolated items: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error"
        )
        

@router.get("/unmapped-items/isolate/total")
def get_isolated_unmapped_items_total(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get aggregate sum of total amount for all isolated items.

    **Summary:**
        Returns the total summed amount for all items currently isolated for review.
        The amount is calculated by joining with the latest analytics mart data.

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **Dict**: Object containing:
            - **success** (`bool`): Success status
            - **total_amount** (`float`): Aggregate sum of amounts

    **Response Example:**
    ```json
    {
      "success": true,
      "total_amount": 15420.50
    }
    ```
    """
    try:
        controller = MappingsReviewController(db)
        result = controller.get_isolated_total_amount()
        return create_optimized_response(result)
    except Exception as e:
        logger.error(f"Failed to retrieve isolated total: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error"
        )


@router.delete("/unmapped-items/isolate")
def remove_isolated_unmapped_item(
    item_id: str = Query(..., description="ID of the records to remove"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Remove an item from mappings_review_items by ID.

    **Summary:**
        Removes a specific item from the review queue using its unique ID.
        This is typically used when an item has been processed or the review
        is no longer needed.

    **Query Parameters:**
        - **id** (`str`): The unique ID of the isolated item record to remove

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **Dict**: Success status and message

    **Response Example:**
    ```json
    {
      "success": true,
      "message": "Successfully removed item with ID 550e8400-e29b-41d4-a716-446655440000 from review."
    }
    ```
    """
    try:
        controller = MappingsReviewController(db)
        result = controller.remove_isolated_item(item_id)
        return create_optimized_response(result)
    except ValueError as e:
        raise HTTPException(status_code=status_code.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to remove isolated item: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error"
        )


@router.patch("/unmapped-items/isolate/status")
def update_isolated_unmapped_item_status(
    item_id: str = Query(..., description="ID of the records to update"),
    status: str = Query("done", description="New status for the item"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update the status of an isolated review item.

    **Summary:**
        Updates the review status for a specific item (e.g., from 'pending' to 'done').
        This is used to track the progress of reviews.

    **Query Parameters:**
        - **item_id** (`str`): The unique ID of the isolated item record to update
        - **status** (`str`): The new status (default: 'done')

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **Dict**: Success status and message
    """
    try:
        controller = MappingsReviewController(db)
        result = controller.update_item_status(item_id, status)
        return create_optimized_response(result)
    except ValueError as e:
        raise HTTPException(status_code=status_code.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update isolated item status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error"
        )


@router.post("/unmapped-items/graph-stats")
def get_unmapped_items_graph_stats(
    request: UnmappedItemsFilterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get date-based statistics for unmapped items chart (no pagination).

    **Summary:**
        Returns aggregated counts of unmapped items grouped by date and mapping type.
        This endpoint is optimized for chart/graph visualizations and respects all
        filters (item_type, supplier, search) without pagination.

    **Request Body:**
        - **item_type** (`str`, required): Type of items - 'temporary', 'no_match', 'permanent', or 'all'
        - **date_from** (`str`, optional): Start date filter (YYYY-MM-DD)
        - **date_to** (`str`, optional): End date filter (YYYY-MM-DD)
        - **date_history** (`str`, optional): Date added filter (YYYY-MM-DD). Matches COALESCE(date_added, date).
        - **supplier_names** (`List[str]`, optional): List of supplier names to filter by
        - **search** (`str`, optional): Search term for item code or description

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **Dict**: Object containing:
            - **date_stats** (`List[object]`): Array of date-based statistics
                - **date** (`str`): Date in YYYY-MM-DD format
                - **permanent_count** (`int`): Count of permanent mappings
                - **temporary_count** (`int`): Count of temporary mappings
                - **no_match_count** (`int`): Count of no match items
                - **total_count** (`int`): Total count for that date
            - **totals** (`object`): Overall totals
                - **permanent** (`int`): Total permanent count
                - **temporary** (`int`): Total temporary count
                - **no_match** (`int`): Total no match count
                - **total** (`int`): Grand total

    **Request Example:**
    ```json
    {
      "item_type": "all",
      "supplier_names": ["BMW Plumbing Supplies"],
      "search": "pipe"
    }
    ```

    **Response Example:**
    ```json
    {
      "date_stats": [
        {
          "date": "2024-12-19",
          "permanent_count": 15,
          "temporary_count": 8,
          "no_match_count": 25,
          "total_count": 48
        },
        {
          "date": "2024-12-18",
          "permanent_count": 12,
          "temporary_count": 5,
          "no_match_count": 20,
          "total_count": 37
        }
      ],
      "totals": {
        "permanent": 27,
        "temporary": 13,
        "no_match": 45,
        "total": 85
      }
    }
    ```

    **Performance Features:**
        - Caching for repeated requests with 5-minute TTL
        - Optimized SQL aggregation query
        - Returns last 30 dates by default

    **Notes:**
        - Results are sorted by date in descending order (most recent first)
        - Dates with no items are not included in the response
        - Respects all filters including item_type, supplier, and search
    """
    start_time = time.time()

    try:
        # Create cache key based on request params
        cache_key_data = {
            "item_type": request.item_type,
            "date_from": request.date_from,
            "date_to": request.date_to,
            "date_history": request.date_history,
            "supplier_names": request.supplier_names,
            "search": request.search,
        }
        cache_key = f"graph_stats_{hashlib.md5(str(cache_key_data).encode()).hexdigest()}"

        # Check cache first
        cached_result = _get_cached_response(cache_key)
        if cached_result is not None:
            logger.info("Returning cached graph stats")
            return create_optimized_response(cached_result)

        # Initialize controller
        controller = UnmappedItemsController(db)

        # Get graph stats
        result = controller.get_unmapped_items_graph_stats(
            item_type=request.item_type,
            db=db,
            date_from=request.date_from,
            date_to=request.date_to,
            date_history=request.date_history,
            supplier_names=request.supplier_names,
            search=request.search,
        )

        # Cache the result
        _set_cached_response(cache_key, result)

        execution_time = time.time() - start_time
        logger.info(f"Graph stats took {execution_time:.3f}s, {len(result.get('date_stats', []))} date groups")

        return create_optimized_response(result)

    except Exception as e:
        logger.exception(f"Error in graph stats endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve graph statistics"
        )


@router.post("/unmapped-items/available-dates", response_model=AvailableDatesResponse)
def get_unmapped_items_available_dates_endpoint(
    request: UnmappedItemsFilterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return unique invoice dates present in the dataset for the given filters.

    **Summary:**
        Returns a sorted (newest → oldest) list of distinct invoice dates from
        `analytics.mart__invoice_items_map`. The frontend uses this list to
        populate the "Date History" dropdown filter.

    **Request Body:**
        - **item_type** (`str`, required): Mapping type filter — same values as
          the main `/unmapped-items` endpoint (`'temporary'`, `'no_match'`,
          `'permanent'`, `'all'`).
        - **supplier_names** (`List[str]`, optional): Restrict dates to invoices
          from these specific suppliers.

    **Response Example:**
    ```json
    {
      "dates": ["04/11/2023", "03/11/2023", "11/05/2023", "11/02/2023"],
      "total": 4
    }
    ```

    **Response Fields:**
        - **dates** (`List[str]`): ISO-8601 date strings (YYYY-MM-DD), newest first.
        - **total** (`int`): Number of distinct dates returned.

    **Notes:**
        - Only non-null invoice dates are included.
        - Dates are deduplicated — each calendar date appears at most once.
        - Results reflect the current state of `mart__invoice_items_map`
          (refreshed on every dbt run).
    """
    start_time = time.time()

    try:
        dates = get_unmapped_items_available_dates(
            db=db,
            item_type=request.item_type,
            supplier_names=request.supplier_names,
        )

        execution_time = time.time() - start_time
        logger.info(
            f"Available dates endpoint: {execution_time:.3f}s, {len(dates)} dates"
        )

        return AvailableDatesResponse(dates=dates, total=len(dates))

    except Exception as e:
        logger.exception(f"Error in available dates endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve available dates"
        )


@router.post("/unmapped-items/export")
def export_unmapped_items(
    item_type: Optional[str] = Body(None, description="Type of items: 'temporary', 'unmapped', or 'no_temporary'. Used when item_ids is not provided."),
    item_ids: Optional[List[str]] = Body(None, description="Specific item IDs to export. If provided, exports only these items (ignores filters)."),
    date_from: Optional[str] = Body(None, description="Start date filter (YYYY-MM-DD). Used when item_ids is not provided."),
    date_to: Optional[str] = Body(None, description="End date filter (YYYY-MM-DD). Used when item_ids is not provided."),
    date_history: Optional[str] = Body(None, description="Date added filter (YYYY-MM-DD). Matches COALESCE(date_added, date). Used when item_ids is not provided."),
    supplier_names: Optional[List[str]] = Body(None, description="List of supplier names to filter by. Used when item_ids is not provided."),
    excluded_items: Optional[List[str]] = Body(None, description="List of item IDs to exclude from export. Used when item_ids is not provided."),
    order_by: Optional[List[Dict[str, str]]] = Body(None, description="Ordering criteria, e.g. [{'column': 'amount', 'order': 'desc'}]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Unified endpoint to export unmapped items to Excel file and return S3 download URL.

    This endpoint consolidates the functionality of both export-all and export-selected
    endpoints, supporting two distinct operation modes:

    SELECTION MODE (when item_ids is provided):
        Exports specific items identified by their IDs. All filter parameters
        (item_type, date_from, date_to, supplier_names, excluded_items) are ignored.
        Uses optimized DAO path for better performance.

    FILTER MODE (when item_ids is NOT provided):
        Exports items based on filter criteria. Supports filtering by item type,
        date range, supplier names, and exclusions.

    Parameters:
        item_ids: Specific item IDs to export. If provided, operates in SELECTION MODE.
                 Example: ["ABC123-B", "XYZ789-F"]

        item_type: Type of items to export (used only in FILTER MODE).
                  Valid values: 'temporary', 'unmapped', or 'no_temporary'
                  Default: "unmapped"

        date_from: Start date filter in YYYY-MM-DD format (used only in FILTER MODE).

        date_to: End date filter in YYYY-MM-DD format (used only in FILTER MODE).

        date_history: Date added filter (used only in FILTER MODE). Matches COALESCE(date_added, date).

        supplier_names: List of supplier names to filter by (used only in FILTER MODE).
                       Example: ["BMW Plumbing Supplies", "Ferguson"]

        excluded_items: List of item IDs to exclude from export (used only in FILTER MODE).
                       Example: ["ABC123-B", "XYZ789-F"]

        order_by: Ordering criteria.
                 Default: [{"column": "amount", "order": "desc"}]
                 Example: [{"column": "cost", "order": "asc"}]

    Response:
        {
            "download_url": "https://s3.amazonaws.com/bucket/Exports/unmapped_items_2024-12-11_14-30-25.xlsx?..."
        }

    Excel File Contents:
        - Original Item ID (with supplier suffix)
        - Original Description
        - Cost
        - Amount (calculated as cost × quantity)
        - Quantity
        - Sheet Name
        - Supplier

    Request Examples:

    1. SELECTION MODE - Export specific items by ID:
    {
        "item_ids": ["ABC123-B", "XYZ789-F", "DEF456-G"],
        "order_by": [{"column": "amount", "order": "desc"}]
    }

    2. FILTER MODE - Export all unmapped items:
    {
        "item_type": "unmapped"
    }

    3. FILTER MODE - Export with date range and supplier filter:
    {
        "item_type": "unmapped",
        "date_from": "2024-01-01",
        "date_to": "2024-12-31",
        "supplier_names": ["BMW Plumbing Supplies"]
    }

    4. FILTER MODE - Export with exclusions:
    {
        "item_type": "unmapped",
        "excluded_items": ["ABC123-B", "XYZ789-F"],
        "order_by": [{"column": "amount", "order": "desc"}]
    }

    Notes:
        - In SELECTION MODE, uses optimized DAO query for better performance
        - In FILTER MODE, if no filters provided, exports ALL items of specified type
        - Default ordering is descending by amount (highest amounts first)
        - Filename includes timestamp for uniqueness
        - The presigned download URL is valid for a limited time period

    Error Responses:
        - 400: Invalid parameters (empty item_ids, invalid item_type, invalid date format)
        - 404: No items found matching criteria
        - 500: Export operation failed
    """
    start_time = time.time()
    # Initialize controller and validate request params
    controller = UnmappedItemsController(db)

    try:
        logger.info(type(item_type))
        valid_request = controller.validate_request_params(db, item_type, date_from, date_to,date_history, order_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid parameters")

    items = []

    # A default error message which we could update depending on the mode (selection or filter)
    error_message = f"No {item_type} items found matching criteria"

    # Selection mode (specific item_ids provided)
    if item_ids:
        logger.info(f"Export SELECTION MODE: {len(item_ids)} item IDs")

        # Use DAO to get items by IDs
        items = get_unmapped_items_by_ids(db, item_ids, order_by, item_type)

        if not items:
            error_message = "None of the specified item IDs were found"

    # Filter mode (no specific item_ids)
    else:
        logger.info(f"Export FILTER MODE: item_type={item_type}")

        # Get items using controller (which uses DAO internally)
        result = controller.get_unmapped_items(
            item_type=valid_request['item_type'],
            db=db,
            date_from=valid_request.get('date_from'),
            date_to=valid_request.get('date_to'),
            date_history=date_history,
            supplier_names=supplier_names,
            search=None,
            order_by=valid_request.get('order_by', order_by),
            page=1,
            size=0  # Get all items
        )

        items = result['items']

    if not items:
        raise HTTPException(status_code=404, detail=error_message)


    # Use export_items_generic for DAO results
    unmapped_columns = [
        "Original Item ID", "Original Description",
        "Cost", "Amount", "Quantity", "Times Bought", "Sheet Name", "Supplier"
    ]
    download_url = export_items_generic(items, columns=unmapped_columns)

    processing_time = time.time() - start_time
    logger.info(f"Export completed (SELECTION MODE) in {processing_time:.2f}s for {len(items)} items")

    return {"download_url": download_url}


@router.post("/unmapped-items/export-all", deprecated=True)
def export_all_unmapped_items(
    item_type: str = Body(..., description="Type of items: 'temporary', 'unmapped', or 'no_temporary'"),
    date_from: Optional[str] = Body(None, description="Start date filter (YYYY-MM-DD)"),
    date_to: Optional[str] = Body(None, description="End date filter (YYYY-MM-DD)"),
    date_history: Optional[str] = Body(None, description="Date added filter (YYYY-MM-DD). Matches COALESCE(date_added, date)."),
    supplier_names: Optional[List[str]] = Body(None, description="List of supplier names to filter by"),
    excluded_items: Optional[List[str]] = Body(None, description="List of item IDs to exclude from export"),
    order_by: Optional[List[Dict[str, str]]] = Body(None, description="Optional ordering criteria"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    DEPRECATED: Use POST /unmapped-items/export instead.

    This endpoint will be removed in a future version.
    Please migrate to the new unified endpoint: POST /unmapped-items/export

    Export unmapped items to Excel file with optional filters and exclusions, return S3 download URL.

    Summary:
        Exports unmapped items of the specified type to an Excel file and uploads it to S3.
        Supports optional date range, supplier filtering, and item exclusions.
        Returns a presigned URL for downloading the file.

    Request Body:
        - item_type (str, required): 'temporary', 'unmapped', or 'no_temporary'
        - date_from (str, optional): Start date filter (YYYY-MM-DD)
        - date_to (str, optional): End date filter (YYYY-MM-DD)
        - date_history (str, optional): Date added filter (YYYY-MM-DD). Matches COALESCE(date_added, date).
        - supplier_names (List[str], optional): List of supplier names to filter by
        - excluded_items (List[str], optional): List of item IDs to exclude from export
        - order_by (List[dict], optional): Ordering criteria, e.g. [{"column": "amount", "order": "desc"}]

    Response:
        - download_url (str): Presigned S3 URL for downloading the Excel file

    Excel File Contents:
        The Excel file will contain the following columns:
        - Original Item ID (with supplier suffix)
        - Original Description
        - Cost
        - Amount (calculated as cost × quantity)
        - Quantity
        - Sheet Name
        - Supplier

    Request Examples:

    1. Export ALL unmapped items (no filters):
    {
      "item_type": "unmapped"
    }

    2. Export with date range and supplier filter:
    ```json
    {
      "item_type": "unmapped",
      "date_from": "2024-01-01",
      "date_to": "2024-12-31",
      "supplier_names": ["BMW Plumbing Supplies"]
    }
    ```
    
    3. Export with exclusions:
    ```json
    {
      "item_type": "unmapped",
      "excluded_items": ["ABC123-B", "XYZ789-F"],
      "order_by": [{"column": "amount", "order": "desc"}]
    }
    ```
    
    **Response Example:**
    ```json
    {
      "download_url": "https://s3.amazonaws.com/bucket/Exports/unmapped_items_2024-12-19_14-30-25.xlsx?AWSAccessKeyId=..."
    }
    ```
    
    **Notes:**
    - If no filters are provided, exports ALL items of the specified type
    - Date range and supplier filters are optional
    - Excluded items are removed from the final export
    - Default ordering is descending by amount if no order_by is provided
    - Filename includes timestamp for uniqueness
    """
    logger.warning("DEPRECATED: /unmapped-items/export-all called. Use /unmapped-items/export instead.")
    # Delegate to new unified endpoint
    return export_unmapped_items(
        item_ids=None,
        item_type=item_type,
        date_from=date_from,
        date_to=date_to,
        date_history=date_history,
        supplier_names=supplier_names,
        excluded_items=excluded_items,
        order_by=order_by,
        current_user=current_user,
        db=db
    )


@router.post("/unmapped-items/export-selected", deprecated=True)
def export_selected_unmapped_items(
    item_ids: List[str] = Body(..., description="List of item IDs to export"),
    order_by: Optional[List[Dict[str, str]]] = Body(None, description="Optional ordering criteria"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    DEPRECATED: Use POST /unmapped-items/export with item_ids parameter instead.

    This endpoint will be removed in a future version.
    Please migrate to the new unified endpoint: POST /unmapped-items/export

    Export specific unmapped items by their IDs to Excel file and return S3 download URL.

    Summary:
        Exports specific unmapped items identified by their item IDs to an Excel file and uploads it to S3.
        The system uses full item codes with suffixes for both searching and Excel output.
        Returns a presigned URL for downloading the file.

    Request Body:
        - item_ids (List[str], required): List of item IDs to export (e.g., ["ABC123-B", "XYZ789-F"])
        - order_by (List[dict], optional): Ordering criteria, e.g. [{"column": "amount", "order": "desc"}]

    Response:
        - download_url (str): Presigned S3 URL for downloading the Excel file

    Excel File Contents:
        The Excel file will contain the following columns:
        - Original Item ID (with supplier suffix)
        - Original Description
        - Cost
        - Amount (calculated as cost × quantity)
        - Quantity
        - Sheet Name
        - Supplier

    Request Example:
    {
      "item_ids": ["ABC123-B", "XYZ789-F", "DEF456-G"],
      "order_by": [{"column": "amount", "order": "desc"}]
    }

    Response Example:
    {
      "download_url": "https://s3.amazonaws.com/bucket/Exports/selected_unmapped_items_2024-12-19_14-30-25.xlsx?AWSAccessKeyId=..."
    }

    Notes:
    - Item IDs should include supplier suffixes (e.g., "ABC123-B" for BMW items)
    - The system uses full item codes with suffixes for both searching and Excel output
    - Only items that exist in the unmapped items list will be exported
    - If some item IDs are not found, a warning will be logged but the export will proceed with found items
    - Ordering supports multiple columns; default is descending by amount (highest amounts first)
    - Amount is calculated as cost × quantity for each item (rounded to 3 decimal places)
    """
    logger.warning("DEPRECATED: /unmapped-items/export-selected called. Use /unmapped-items/export instead.")
    # Delegate to new unified endpoint
    return export_unmapped_items(
        item_ids=item_ids,
        item_type=None,
        date_from=None,
        date_to=None,
        supplier_names=None,
        excluded_items=None,
        order_by=order_by,
        current_user=current_user,
        db=db
    )


@router.post("/supplier-report/export")
def export_supplier_report(
    request: SupplierReportRequest,
    background_tasks: BackgroundTasks,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate consolidated supplier report for multiple Job Addresses and Suppliers.

    **Summary:**
        Filters invoice items by Job Addresses (customer_jobs) and optionally Supplier Names (vendor),
        then groups by Invoice Number (ref_no) and sums amounts for duplicate invoices.
        Returns an Excel file with consolidated invoice totals.

    **Request Body:**
        - **customer_jobs** (`List[str]`, required): Array of Job Addresses to filter by (at least 1 required)
        - **supplier_names** (`List[str]`, optional): Array of Supplier Names to filter by (required if all_suppliers=False)
        - **all_suppliers** (`bool`, optional, default=False): If True, export all suppliers for the given jobs

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **str**: Presigned S3 URL for downloading the Excel file

    **Excel File Format:**
        The exported file contains the following columns:
        - **Date** (MM/DD/YYYY format): Invoice date
        - **Ref NO.**: Invoice reference number
        - **Customer Job**: Job Address
        - **Vendor**: Supplier Name
        - **Amount**: Sum of all amounts for that invoice number

    **Functional Logic:**
        1. Filters invoice items matching the Job Addresses and (optionally) Supplier Names
        2. Groups records by Invoice Number (ref_no), Customer Job, and Vendor
        3. Sums amounts for duplicate invoice numbers into a single total
        4. Maintains the associated date for each invoice
        5. Exports only one row per Invoice Number per Job/Vendor combination

    **Example:**
        If Invoice #652470 appears twice ($100 and $50), the report will show:
        - One row for #652470 with a total of $150

    **Request Examples:**
        ```json
        // Single job, all suppliers
        {
            "customer_jobs": ["123 Main Street"],
            "all_suppliers": true
        }

        // Single job, specific suppliers
        {
            "customer_jobs": ["123 Main Street"],
            "supplier_names": ["BMW Plumbing Supplies", "ABC Supply"]
        }

        // Multiple jobs, all suppliers
        {
            "customer_jobs": ["123 Main Street", "456 Oak Ave"],
            "all_suppliers": true
        }

        // Multiple jobs, specific suppliers
        {
            "customer_jobs": ["123 Main Street", "456 Oak Ave"],
            "supplier_names": ["BMW Plumbing Supplies"]
        }
        ```

    **Response Example:**
        ```
        "https://s3.amazonaws.com/bucket/Exports/SupplierReport_2024-12-19_14-30-25.xlsx?AWSAccessKeyId=..."
        ```

    **Error Codes:**
        - **400**: Invalid request parameters (empty customer_jobs or missing supplier_names when all_suppliers=False)
        - **404**: No invoice items found matching criteria
        - **500**: Export processing error

    **Notes:**
        - Only includes active invoice items (is_active = True)
        - Amounts are automatically summed for duplicate invoice numbers
        - Date is formatted as MM/DD/YYYY in the export
        - If an invoice has multiple dates, the earliest date is used
        - Null or missing ref_no values are handled gracefully
        - Results are ordered by customer_job, vendor, ref_no
    """
    try:
        # Initialize controller with dependency injection
        controller = SupplierReportController(db)

        # Generate report using controller (SQL-level aggregation)
        return controller.generate_report(background_tasks, request)

    except HTTPException:
        # Re-raise HTTP exceptions (400, 404) as-is for proper error handling
        raise
    except Exception as e:
        # Log full exception details for debugging
        # logger.exception() automatically captures exception and traceback
        jobs_str = ", ".join(request.customer_jobs)
        if request.all_suppliers:
            supplier_str = "all suppliers"
        else:
            supplier_str = ", ".join(request.supplier_names) if request.supplier_names else "none"
        logger.exception(
            f"Supplier report export error for jobs=[{jobs_str}] / suppliers=[{supplier_str}]"
        )
        # Preserve exception chain for proper traceback context (prevents B904 lint warning)
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {str(e)}"
        ) from e
