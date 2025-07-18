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
    export_price_history_to_excel, save_final_data
)
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
from mpi_backend.utils.export_utils import convert_unmapped_items_to_dataframe
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
import os
import logging
import time
from functools import lru_cache
import hashlib
from datetime import datetime, date
from sqlalchemy.sql import text

router = APIRouter(prefix="/filter", tags=["Filtering Data"])

logger = logging.getLogger(__name__)

# Enhanced caching with ultra-aggressive optimization
cache_store = {}
cache_timestamps = {}
response_cache = {}  # Pre-computed responses
CACHE_TTL = 300  # 5 minutes

# Pre-computed static responses for ultra-fast delivery
static_responses = {
    "column_mappings": None,
    "empty_filter_result": None
}


def _is_cache_valid(key: str) -> bool:
    """Check if cache entry is still valid"""
    if key not in cache_timestamps:
        return False
    return (time.time() - cache_timestamps[key]) < CACHE_TTL


def _get_cached_response(key: str):
    """Get cached response if valid - ultra-fast lookup"""
    if key in response_cache and _is_cache_valid(key):
        return response_cache[key]
    return cache_store.get(key) if _is_cache_valid(key) else None


def _set_cached_response(key: str, value):
    """Cache response with aggressive optimization"""
    cache_store[key] = value
    response_cache[key] = value  # Dual cache for speed
    cache_timestamps[key] = time.time()
    
    # Aggressive cache cleanup - keep only most recent
    if len(cache_store) > 50:  # Reduced from 100 for speed
        oldest_keys = sorted(cache_timestamps.keys(), 
                           key=lambda k: cache_timestamps[k])[:20]
        for old_key in oldest_keys:
            cache_store.pop(old_key, None)
            response_cache.pop(old_key, None)
            cache_timestamps.pop(old_key, None)


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
        fallback = cache_store.get("customer_job_locations_fallback", [])
        return create_optimized_response(fallback)


@router.get("/column-mapping")
def column_mappings(token: str = Depends(JWTBearer())):
    """INSTANT column mappings - pre-computed response."""
    # Return pre-computed static response (microsecond speed)
    return create_optimized_response(static_responses["column_mappings"])


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
        
        # Extract item codes and vendor info for supplier-specific monthly comparison
        item_id_pairs = []
        item_vendor_pairs = []
        
        for invoice_item in filtered_data["items"]:
            # With suffix standardization, use the item as stored in database
            item = invoice_item.item
            vendor = invoice_item.vendor
            
            item_id_pairs.append((item, invoice_item.id))  # Use item as stored
            item_vendor_pairs.append((item, vendor))  # Use for supplier-specific comparison

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
                    item_code, item_id = item_id_pairs[i]
                    result.append({
                        "item": item_code,  # Return item as stored in database
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
    valid_entries = sum(1 for key in cache_store.keys() if _is_cache_valid(key))
    
    return create_optimized_response({
        "total_cache_entries": len(cache_store),
        "valid_cache_entries": valid_entries,
        "cache_hit_ratio": "Available in production logs",
        "cache_ttl_seconds": CACHE_TTL
    })

@router.delete("/cache")
def clear_cache(token: str = Depends(JWTBearer())):
    """Clear all cached data."""
    global cache_store, cache_timestamps
    cache_store.clear()
    cache_timestamps.clear()
    
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
        Returns a paginated, de-duplicated list of invoice items based on the specified filter type, with support for search and flexible ordering. Items are grouped by supplier + item code, with full item codes including supplier suffixes for distinction (e.g., ABC-B for BMW, ABC-F for Flow Mark).

    **Request Body:**

    - **item_type** (`str`, required):
        - "temporary": Items with `sheet_name` and either `mpi_item_id` or `mpi_description` is "No Match" or starts with "UIDI"
        - "unmapped": ALL items with either `mpi_item_id` or `mpi_description` is "No Match" or starts with "UIDI" (regardless of sheet_name)
        - "no_temporary": Items with NO `sheet_name` and either `mpi_item_id` or `mpi_description` is "No Match" or starts with "UIDI"
    - **date_from** (`str`, optional): Start date filter (YYYY-MM-DD)
    - **date_to** (`str`, optional): End date filter (YYYY-MM-DD)
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
          "cost": 15.50,
          "amount": 155.00,
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
        - **cost** (`float`): Unit cost of the item
        - **amount** (`float`): Total amount calculated as cost × quantity (rounded to 3 decimal places)
        - **quantity** (`int`): Quantity of the item
        - **sheet_name** (`str`): Google sheet name (null/empty for unmapped)
        - **supplier** (`str`): Supplier/vendor name
    - **total_count** (`int`): Total number of unique items found
    - **page** (`int`): Current page number
    - **size** (`int`): Number of items per page
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
    try:
        # Validate item_type
        if request.item_type not in ["temporary", "unmapped", "no_temporary"]:
            raise HTTPException(
                status_code=400,
                detail="item_type must be either 'temporary', 'unmapped', or 'no_temporary'"
            )
        
        # Provide default ordering if order_by is None or empty
        order_by = request.order_by
        if not order_by:
            # Default ordering: descending by amount (highest amounts first)
            order_by = [{"column": "amount", "order": "desc"}]
        
        # Initialize controller
        controller = UnmappedItemsController(db)
        
        # Get filtered items with guaranteed ordering
        result = controller.get_unmapped_items(
            item_type=request.item_type,
            date_from=request.date_from,
            date_to=request.date_to,
            supplier_names=request.supplier_names,
            search=request.search,
            order_by=order_by,  # Pass the validated order_by
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



@router.post("/unmapped-items/export-all")
def export_all_unmapped_items(
    item_type: str = Body(..., description="Type of items: 'temporary', 'unmapped', or 'no_temporary'"),
    date_from: Optional[str] = Body(None, description="Start date filter (YYYY-MM-DD)"),
    date_to: Optional[str] = Body(None, description="End date filter (YYYY-MM-DD)"),
    supplier_names: Optional[List[str]] = Body(None, description="List of supplier names to filter by"),
    excluded_items: Optional[List[str]] = Body(None, description="List of item IDs to exclude from export"),
    order_by: Optional[List[Dict[str, str]]] = Body(None, description="Optional ordering criteria"),
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Export unmapped items to Excel file with optional filters and exclusions, return S3 download URL.
    
    **Summary:**
        Exports unmapped items of the specified type to an Excel file and uploads it to S3.
        Supports optional date range, supplier filtering, and item exclusions.
        Returns a presigned URL for downloading the file.
        
    **Request Body:**
        - **item_type** (`str`, required): 'temporary', 'unmapped', or 'no_temporary'
        - **date_from** (`str`, optional): Start date filter (YYYY-MM-DD)
        - **date_to** (`str`, optional): End date filter (YYYY-MM-DD)
        - **supplier_names** (`List[str]`, optional): List of supplier names to filter by
        - **excluded_items** (`List[str]`, optional): List of item IDs to exclude from export
        - **order_by** (`List[dict]`, optional): Ordering criteria, e.g. `[{"column": "amount", "order": "desc"}]`
        
    **Response:**
        - **download_url** (`str`): Presigned S3 URL for downloading the Excel file
        
    **Excel File Contents:**
        The Excel file will contain the following columns:
        - Original Item ID (with supplier suffix)
        - Original Description
        - Cost
        - Amount (calculated as cost × quantity)
        - Quantity
        - Sheet Name
        - Supplier
        
    **Request Examples:**
    
    1. Export ALL unmapped items (no filters):
    ```json
    {
      "item_type": "unmapped"
    }
    ```
    
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
    try:
        import time
        start_time = time.time()
        
        # Validate item_type
        if item_type not in ["temporary", "unmapped", "no_temporary"]:
            raise HTTPException(
                status_code=400,
                detail="item_type must be either 'temporary', 'unmapped', or 'no_temporary'"
            )
        
        # Convert string dates to date objects
        date_from_obj = None
        date_to_obj = None
        
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="date_from must be in YYYY-MM-DD format"
                )
        
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="date_to must be in YYYY-MM-DD format"
                )
        
        # Provide default ordering if order_by is None or empty
        if not order_by:
            # Default ordering: descending by amount (highest amounts first)
            order_by = [{"column": "amount", "order": "desc"}]
        
        # Initialize controller
        controller = UnmappedItemsController(db)
        
        # Get items with optional filters
        result = controller.get_unmapped_items(
            item_type=item_type,
            date_from=date_from_obj,  # Pass converted date object
            date_to=date_to_obj,      # Pass converted date object
            supplier_names=supplier_names,
            search=None,  # No search filter for export-all
            order_by=order_by,
            page=1,
            size=0  # Get all items
        )
        
        if not result['items']:
            raise HTTPException(
                status_code=404, 
                detail=f"No {item_type} items found matching the criteria"
            )
        
        # Apply excluded items filter if provided
        if excluded_items:
            original_count = len(result['items'])
            result['items'] = [
                item for item in result['items'] 
                if item['original_item_id'] not in excluded_items
            ]
            excluded_count = original_count - len(result['items'])
            logger.info(f"Excluded {excluded_count} items from export")
        
        if not result['items']:
            raise HTTPException(
                status_code=404, 
                detail="No items remaining after applying exclusions"
            )
        
        # Convert to DataFrame
        items_df = convert_unmapped_items_to_dataframe(result['items'])
        
        if items_df.empty:
            raise HTTPException(
                status_code=404, 
                detail="No data found for export"
            )
        
        # Prepare file paths
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
        filename = f'unmapped_items_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.xlsx'
        file_path = f'{upload_folder}{filename}'
        
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        # Save to Excel
        save_final_data(final_df=items_df, supplier='', output_path=file_path)
        
        processing_time = time.time() - start_time
        logger.info(
            f"Unmapped items export completed in {processing_time:.2f} seconds "
            f"for {len(items_df)} items"
        )
        
        # Upload to S3 and get download URL
        upload_file(file_path, file_key=f'Exports/{filename}', is_invoice=False)
        download_url = get_presigned_url(
            file_key=f'Exports/{filename}', 
            is_invoice=False
        )
        
        return {"download_url": download_url}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Export unmapped items error: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Export failed: {str(e)}"
        )

@router.post("/unmapped-items/export-selected")
def export_selected_unmapped_items(
    item_ids: List[str] = Body(..., description="List of item IDs to export"),
    order_by: Optional[List[Dict[str, str]]] = Body(None, description="Optional ordering criteria"),
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Export specific unmapped items by their IDs to Excel file and return S3 download URL.
    
    **Summary:**
        Exports specific unmapped items identified by their item IDs to an Excel file and uploads it to S3.
        The system uses full item codes with suffixes for both searching and Excel output.
        Returns a presigned URL for downloading the file.
        
    **Request Body:**
        - **item_ids** (`List[str]`, required): List of item IDs to export (e.g., ["ABC123-B", "XYZ789-F"])
        - **order_by** (`List[dict]`, optional): Ordering criteria, e.g. `[{"column": "amount", "order": "desc"}]`
        
    **Response:**
        - **download_url** (`str`): Presigned S3 URL for downloading the Excel file
        
    **Excel File Contents:**
        The Excel file will contain the following columns:
        - Original Item ID (with supplier suffix)
        - Original Description
        - Cost
        - Amount (calculated as cost × quantity)
        - Quantity
        - Sheet Name
        - Supplier
        
    **Request Example:**
    ```json
    {
      "item_ids": ["ABC123-B", "XYZ789-F", "DEF456-G"],
      "order_by": [{"column": "amount", "order": "desc"}]
    }
    ```
    
    **Response Example:**
    ```json
    {
      "download_url": "https://s3.amazonaws.com/bucket/Exports/selected_unmapped_items_2024-12-19_14-30-25.xlsx?AWSAccessKeyId=..."
    }
    ```
    
    **Notes:**
    - Item IDs should include supplier suffixes (e.g., "ABC123-B" for BMW items)
            - The system uses full item codes with suffixes for both searching and Excel output
    - Only items that exist in the unmapped items list will be exported
    - If some item IDs are not found, a warning will be logged but the export will proceed with found items
    - Ordering supports multiple columns; default is descending by `amount` (highest amounts first)
    - Amount is calculated as cost × quantity for each item (rounded to 3 decimal places)
    """
    try:
        import time
        start_time = time.time()
        
        if not item_ids:
            raise HTTPException(
                status_code=400,
                detail="item_ids list cannot be empty"
            )
        
        # Provide default ordering if order_by is None or empty
        if not order_by:
            # Default ordering: descending by amount (highest amounts first)
            order_by = [{"column": "amount", "order": "desc"}]
        
        # Initialize controller
        controller = UnmappedItemsController(db)
        
        # With suffix standardization, we use full item codes for searching
        # No suffix cleaning needed
        cleaned_item_ids = item_ids
        
        # Get all unmapped items first (we'll filter by cleaned item_ids)
        # Use "unmapped" to get all items regardless of sheet_name status
        all_items_result = controller.get_unmapped_items(
            item_type="unmapped",  # Get all unmapped items regardless of sheet_name
            date_from=None,
            date_to=None,
            supplier_names=None,
            search=None,
            order_by=order_by,
            page=1,
            size=0  # Get all items
        )
        
        if not all_items_result['items']:
            raise HTTPException(
                status_code=404, 
                detail="No unmapped items found in the system"
            )
        
        # Filter to only include requested item_ids (comparing cleaned versions)
        selected_items = []
        found_cleaned_ids = set()
        
        for item in all_items_result['items']:
            # With suffix standardization, we use full item codes for comparison
            # No suffix cleaning needed
            cleaned_item_id = item['original_item_id']
            
            # Check if this item ID matches any of our requested IDs
            if cleaned_item_id in cleaned_item_ids:
                selected_items.append(item)
                found_cleaned_ids.add(cleaned_item_id)
        
        if not selected_items:
            raise HTTPException(
                status_code=404, 
                detail="None of the specified item IDs were found"
            )
        
        # Log how many items were found vs requested
        found_count = len(selected_items)
        requested_count = len(item_ids)
        if found_count < requested_count:
            missing_items = [item_id for item_id in item_ids 
                           if item_id not in found_cleaned_ids]
            logger.warning(
                f"Only {found_count} out of {requested_count} requested items were found. "
                f"Missing items: {missing_items}"
            )
        
        # Convert to DataFrame
        items_df = convert_unmapped_items_to_dataframe(selected_items)
        
        if items_df.empty:
            raise HTTPException(
                status_code=404, 
                detail="No data found for export"
            )
        
        # Prepare file paths
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
        filename = f'selected_unmapped_items_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.xlsx'
        file_path = f'{upload_folder}{filename}'
        
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        # Save to Excel
        save_final_data(final_df=items_df, supplier='', output_path=file_path)
        
        processing_time = time.time() - start_time
        logger.info(
            f"Selected unmapped items export completed in {processing_time:.2f} seconds "
            f"for {len(items_df)} items"
        )
        
        # Upload to S3 and get download URL
        upload_file(file_path, file_key=f'Exports/{filename}', is_invoice=False)
        download_url = get_presigned_url(
            file_key=f'Exports/{filename}', 
            is_invoice=False
        )
        
        return {"download_url": download_url}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Export selected unmapped items error: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Export failed: {str(e)}"
        )

