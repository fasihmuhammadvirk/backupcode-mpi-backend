from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import JSONResponse
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.controllers.UnmappedItems import (
    UnmappedItemsController
)
from mpi_backend.database.schemas import (
    FilterRequest, PaginatedInvoiceItemsResponse, 
    PriceHistoryRequest, PriceHistoryResponse
)
from mpi_backend.database.schemas.InvoiceItems import (
    UnmappedItemsFilterRequest,
    PaginatedUnmappedItemsResponse
)
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.pdf_to_excel.formatting_util import (
    export_price_history_to_excel
)
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
import os
import logging
import time
from functools import lru_cache
import hashlib
import json
import gzip
from datetime import datetime, date
from sqlalchemy.sql import text

router = APIRouter(prefix="/filter", tags=["Filtering Data"])

logger = logging.getLogger(__name__)

# Enhanced caching with ultra-aggressive optimization
_cache_store = {}
_cache_timestamps = {}
_response_cache = {}  # Pre-computed responses
CACHE_TTL = 300  # 5 minutes

# Pre-computed static responses for ultra-fast delivery
_static_responses = {
    "column_mappings": None,
    "empty_filter_result": None
}


def _is_cache_valid(key: str) -> bool:
    """Check if cache entry is still valid"""
    if key not in _cache_timestamps:
        return False
    return (time.time() - _cache_timestamps[key]) < CACHE_TTL


def _get_cached_response(key: str):
    """Get cached response if valid - ultra-fast lookup"""
    if key in _response_cache and _is_cache_valid(key):
        return _response_cache[key]
    return _cache_store.get(key) if _is_cache_valid(key) else None


def _set_cached_response(key: str, value):
    """Cache response with aggressive optimization"""
    _cache_store[key] = value
    _response_cache[key] = value  # Dual cache for speed
    _cache_timestamps[key] = time.time()
    
    # Aggressive cache cleanup - keep only most recent
    if len(_cache_store) > 50:  # Reduced from 100 for speed
        oldest_keys = sorted(_cache_timestamps.keys(), 
                           key=lambda k: _cache_timestamps[k])[:20]
        for old_key in oldest_keys:
            _cache_store.pop(old_key, None)
            _response_cache.pop(old_key, None)
            _cache_timestamps.pop(old_key, None)


def _warmup_cache():
    """Pre-warm frequently used responses"""
    try:
        # Pre-compute column mappings
        if not _static_responses["column_mappings"]:
            _static_responses["column_mappings"] = {
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
        "memo": "Memo",
        "buyer": "Buyer",
        "date_added": "Date Added"
    }


@router.get("/get-locations", response_model=List[str])
def customer_job_filter(db: Session = Depends(get_db), 
                       token: str = Depends(JWTBearer())):
    """ULTRA-FAST customer job locations with aggressive caching."""
    
    cache_key = "customer_job_locations_v2"
    cached_result = _get_cached_response(cache_key)
    if cached_result is not None:
        logger.info(f"INSTANT cache hit: customer locations ({len(cached_result)} items)")
        return create_optimized_response(cached_result)
    
    try:
        start_time = time.time()
        
        # Ultra-fast raw SQL query
        raw_query = text("""
            SELECT DISTINCT customer_job 
            FROM invoice_items 
            WHERE is_active = true 
                AND customer_job IS NOT NULL 
                AND customer_job != ''
            ORDER BY customer_job
            LIMIT 200
        """)
        
        result = db.execute(raw_query)
        locations = [row[0] for row in result.fetchall()]
        
        # Aggressive caching
        _set_cached_response(cache_key, locations)
        
        execution_time = time.time() - start_time
        logger.info(f"ULTRA-FAST locations: {execution_time:.3f}s, {len(locations)} items")
        
        return create_optimized_response(locations)
        
    except Exception as e:
        logger.error(f"Failed to fetch customer-job address: {e}")
        # Return cached fallback if available
        fallback = _cache_store.get("customer_job_locations_fallback", [])
        return create_optimized_response(fallback)


@router.get("/column-mapping")
def column_mappings(token: str = Depends(JWTBearer())):
    """INSTANT column mappings - pre-computed response."""
    # Return pre-computed static response (microsecond speed)
    return create_optimized_response(_static_responses["column_mappings"])


@router.post("/by-column")
def get_column_data(
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer()),
    column_name: str = Query(None, description="Column name for data"),
    payload: Optional[Dict] = Body(None, description="Filter context")
):
    """
    ULTRA-FAST dropdown population - millisecond response times.
    Same structure, lightning speed.
    """
    start_time = time.time()
    
    if column_name is None:
        return create_optimized_response({"data": "Invalid Column Name Specified"})

    try:
        # Ultra-aggressive cache key
        cache_key = f"column_v3_{column_name}"
        cached_result = _get_cached_response(cache_key)
        if cached_result is not None:
            logger.info(f"INSTANT cache hit: {column_name} ({len(cached_result)} items)")
            return create_optimized_response(cached_result)

        # Use ultra-optimized controller method
        controller = InvoiceItemController(db)
        distinct_values = controller.get_data_by_column_name(column_name, None, [])
        
        # Aggressive caching with pre-computation
        _set_cached_response(cache_key, distinct_values)
        
        execution_time = time.time() - start_time
        logger.info(f"ULTRA-FAST column '{column_name}': {execution_time:.3f}s")
        
        return create_optimized_response(distinct_values)
        
    except Exception as e:
        logger.error(f"Error in by-column endpoint: {e}")
        # Return empty array to maintain structure
        return create_optimized_response([])


@router.post("", response_model=PaginatedInvoiceItemsResponse)
def filter_data(
    request: FilterRequest, 
    db: Session = Depends(get_db), 
    token: str = Depends(JWTBearer()),
    page: int = Query(1, ge=1),
    size: int = Query(10)
):
    """
    ULTRA-FAST main filter - same structure, millisecond speed.
    """
    start_time = time.time()
    
    try:
        # Ultra-aggressive caching for common requests
        request_fingerprint = f"filter_v3_{hash(str(request.dict()))}_{page}_{size}"
        
        # Check for instant cache hit
        if not request.filters and not request.comparison_filters:
            cached_result = _get_cached_response(request_fingerprint)
            if cached_result is not None:
                logger.info(f"INSTANT cache hit: filter page {page}")
                return create_optimized_response(cached_result)

        # Use ultra-optimized controller
        controller = InvoiceItemController(db)
        filtered_data = controller.apply_filters(request, page, size)
        
        # Cache simple requests aggressively
        if not request.filters and not request.comparison_filters and size <= 50:
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
        logger.error(f"Error in filter endpoint: {e}")
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


@router.post("/price-difference")
def get_price_difference(request: FilterRequest, db: Session = Depends(get_db),
                         # token: str = Depends(JWTBearer()),
                page: int = Query(1, ge=1),
                size: int = Query(10)):
    """
    Get price difference calculations for filtered invoice items.
    Now includes caching for improved performance on repeated requests.
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
        filtered_data = InvoiceItemController(db).apply_filters(request, page, size)
        controller = InvoiceItemController(db)
        
        # Extract item codes and vendor info for supplier-specific price comparison
        item_id_pairs = []
        item_vendor_pairs = []
        
        for invoice_item in filtered_data["items"]:
            # The item from apply_filters has suffix for display
            suffixed_item = invoice_item.item
            # Remove suffix to get original database item code for search
            original_item = controller._remove_suffix_from_item_code(suffixed_item)
            vendor = invoice_item.vendor
            
            item_id_pairs.append((suffixed_item, invoice_item.id))  # Keep suffixed for response
            item_vendor_pairs.append((original_item, vendor))  # Use for supplier-specific comparison

        if not item_vendor_pairs:
            result = []
        else:
            # Calculate price increase with supplier-specific method
            price_increase = controller.calculate_price_increase(
                item_numbers=None, 
                item_vendor_pairs=item_vendor_pairs
            )

            result = []
            for i, (item, percentage) in enumerate(price_increase):
                if i < len(item_id_pairs):  # Safety check
                    suffixed_item, item_id = item_id_pairs[i]
                    result.append({
                        "item": suffixed_item,  # Return suffixed item for UI consistency
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


@router.post("/price-history",response_model=List[PriceHistoryResponse])
def get_price_history(request: PriceHistoryRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    """
    Get price history for a specific item and vendor.
    
    Args:
        request: PriceHistoryRequest containing item_number, vendor, and description
        
    Returns:
        List[PriceHistoryResponse]: List of price history records sorted by date
        
    Raises:
        HTTPException: If validation fails or no data found
    """
    try:
        # Validate input parameters
        if not request.item_number or not request.item_number.strip():
            raise HTTPException(
                status_code=400,
                detail="item_number is required and cannot be empty"
            )
        
        if not request.vendor or not request.vendor.strip():
            raise HTTPException(
                status_code=400,
                detail="vendor is required and cannot be empty"
            )
        
        logger.info(f"Price history request - Item: {request.item_number}, Vendor: {request.vendor}")
        
        # Get price history from controller
        price_history = InvoiceItemController(db).get_price_history(request)
        
        # Log result for debugging
        logger.info(f"Price history response - Found {len(price_history)} records")
        
        if not price_history:
            logger.warning(f"No price history found for item: {request.item_number}, vendor: {request.vendor}")
            # Return empty list instead of 404 to allow frontend to handle gracefully
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
def get_price_history(request: PriceHistoryRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    price_history = InvoiceItemController(db).get_price_history(request)

    exported_file_path = export_price_history_to_excel(price_history)
    file_name = os.path.basename(exported_file_path)
    upload_file(exported_file_path, file_key=f'Exports/{file_name}', is_invoice=False)  # upload to s3 to be exported
    download_url = get_presigned_url(file_key=f'Exports/{file_name}', is_invoice=False)
    return download_url


@router.post("/get_aggregates")
def get_aggregates(
    request: FilterRequest, 
    db: Session = Depends(get_db), 
    token: str = Depends(JWTBearer())
):
    """Optimized aggregates endpoint with caching and performance monitoring."""
    start_time = time.time()
    
    try:
        # Cache key for aggregates
        request_hash = hashlib.md5(request.json().encode()).hexdigest()
        cache_key = f"aggregates_{request_hash}"
        
        # Check cache
        cached_result = _get_cached_response(cache_key)
        if cached_result is not None:
            logger.info("Returning cached aggregates")
            return create_optimized_response(cached_result)
        
        controller = InvoiceItemController(db)
        aggregates = controller.get_aggregates(request)
        
        # Cache the result
        _set_cached_response(cache_key, aggregates)
        
        logger.info(f"get_aggregates took {time.time() - start_time:.2f}s")
        return create_optimized_response(aggregates)
        
    except Exception as e:
        logger.error(f"Error in get_aggregates: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Aggregates calculation failed: {str(e)}"
        )

# Add cache management endpoint for debugging
@router.get("/cache-stats")
def get_cache_stats(token: str = Depends(JWTBearer())):
    """Get cache statistics for performance monitoring."""
    valid_entries = sum(1 for key in _cache_store.keys() if _is_cache_valid(key))
    
    return create_optimized_response({
        "total_cache_entries": len(_cache_store),
        "valid_cache_entries": valid_entries,
        "cache_hit_ratio": "Available in production logs",
        "cache_ttl_seconds": CACHE_TTL
    })

@router.delete("/cache")
def clear_cache(token: str = Depends(JWTBearer())):
    """Clear all cached data."""
    global _cache_store, _cache_timestamps
    _cache_store.clear()
    _cache_timestamps.clear()
    
    return create_optimized_response({"message": "Cache cleared successfully"})


@router.post("/unmapped-items", response_model=PaginatedUnmappedItemsResponse)
def get_unmapped_items(
    request: UnmappedItemsFilterRequest,
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer()),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(10, ge=1, description="Number of items per page")
):
    """
    Retrieve unique unmapped or temporary items with advanced filtering, search, and ordering.

    **Summary:**
        Returns a paginated, de-duplicated list of invoice items that are either unmapped or temporarily mapped, with support for search and flexible ordering. Items are grouped by cleaned item code (suffixes like -W, -B, -Y, -S, -F are removed).

    **Request Body:**

    - **item_type** (`str`, required):
        - "temporary": Items with `sheet_name` and either `mpi_item_id` or `mpi_description` is "No Match" or starts with "UIDI"
        - "unmapped": Items with `sheet_name` null or empty
    - **date_from** (`str`, optional): Start date filter (YYYY-MM-DD)
    - **date_to** (`str`, optional): End date filter (YYYY-MM-DD)
    - **supplier_names** (`List[str]`, optional): List of supplier names to filter by
    - **search** (`str`, optional): Search term for item code or description
    - **order_by** (`List[dict]`, optional): List of ordering criteria, e.g. `[{"column": "original_item_id", "order": "asc"}]`

    **Query Parameters:**

    - **page** (`int`, default=1): Page number (1-based)
    - **size** (`int`, default=10): Number of items per page

    **Request Example:**

    ```json
    {
      "item_type": "temporary",
      "date_from": "2024-01-01",
      "date_to": "2024-12-31",
      "supplier_names": ["BMW Plumbing Supplies"],
      "search": "006-ST4",
      "order_by": [
        {"column": "original_item_id", "order": "desc"},
        {"column": "supplier", "order": "asc"}
      ]
    }
    ```

    **Response Example:**

    ```json
    {
      "items": [
        {
          "original_item_id": "006-ST4",
          "mpi_item_id": "No Match",
          "mpi_description": "No Match",
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

    - **items** (`List[object]`): List of unique unmapped/temporary items (suffixes removed)
        - **original_item_id** (`str`): Cleaned item code (e.g., "ABC-123")
        - **mpi_item_id** (`str`): MPI item code or "No Match"/"UIDI" for temporary items
        - **mpi_description** (`str`): MPI description or "No Match"
        - **sheet_name** (`str`): Google sheet name (null/empty for unmapped)
        - **supplier** (`str`): Supplier/vendor name
    - **total_count** (`int`): Total number of unique items found
    - **page** (`int`): Current page number
    - **size** (`int`): Number of items per page
    - **pages** (`int`): Total number of pages

    **Notes:**
    - Items are grouped by cleaned item code (suffixes like -W, -B, -Y, -S, -F are removed)
    - Search is case-insensitive and matches both item code and description
    - Ordering supports multiple columns; default is ascending by `original_item_id`
    - Only unique items are returned in the response
    """
    try:
        # Validate item_type
        if request.item_type not in ["temporary", "unmapped"]:
            raise HTTPException(
                status_code=400,
                detail="item_type must be either 'temporary' or 'unmapped'"
            )
        
        # Initialize controller
        controller = UnmappedItemsController(db)
        
        # Get filtered items
        result = controller.get_unmapped_items(
            item_type=request.item_type,
            date_from=request.date_from,
            date_to=request.date_to,
            supplier_names=request.supplier_names,
            search=request.search,
            order_by=request.order_by,
            page=page,
            size=size
        )
        
        logger.info(
            f"Retrieved {len(result['items'])} {request.item_type} items "
            f"(page {page}/{result['pages']}, total: {result['total_count']})"
        )
        
        return PaginatedUnmappedItemsResponse(**result)
        
    except ValueError as e:
        logger.error(f"Invalid request parameters: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error retrieving unmapped items: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while retrieving unmapped items"
        )

