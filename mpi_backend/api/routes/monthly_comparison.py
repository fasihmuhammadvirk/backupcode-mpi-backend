from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Union
from sqlalchemy import or_

from mpi_backend.database import get_async_db
from mpi_backend.database.schemas.MonthlyComparison import (
    ItemInfo, 
    ItemPriceResponse, 
    PaginatedItemInfoResponse,
    SupplierPriceInfo,
    MonthlyComparisonDateRange,
    ItemSearchRequest,
    SupplierCheapestItemsResponse,
    EnrichedItemPriceResponse,
    PaginatedEnrichedItemResponse,
    DateRangeWithExclusions
)
from mpi_backend.database.controllers.MonthlyComparisonController import (
    MonthlyComparisonController
)
from mpi_backend.utils.auth.auth_bearer import JWTBearer


router = APIRouter(
    prefix="/price-comparison",
    tags=["Monthly Comparison"]
)


# Removed search-items endpoint


@router.post("/dropdown-items", response_model=PaginatedItemInfoResponse)
async def get_dropdown_items(
    date_range: MonthlyComparisonDateRange,
    query: Optional[str] = Query(None, description="Optional search term for filtering items"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    db: AsyncSession = Depends(get_async_db),
    token: str = Depends(JWTBearer())
):
    """
    Get paginated distinct items for dropdown population within a date range.
    
    **Summary:**
        Retrieves distinct items that were used within a specified date range,
        with optional search functionality. This endpoint is designed for populating
        dropdown menus in the frontend with items available for price comparison.
        
    **Request Body:**
        - **date_range** (`MonthlyComparisonDateRange`, required): Date range object containing:
            - **from_date** (`date`): Start date for the range (YYYY-MM-DD)
            - **to_date** (`date`): End date for the range (YYYY-MM-DD)
            
    **Query Parameters:**
        - **query** (`str`, optional): Search term for filtering items
        - **page** (`int`, default=1): Page number for pagination (1-based)
        - **size** (`int`, default=10): Number of items per page (1-100)
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **PaginatedItemInfoResponse**: Paginated response containing:
            - **items** (`List[ItemInfo]`): Array of distinct item information
            - **total** (`int`): Total number of items matching criteria
            - **page** (`int`): Current page number
            - **size** (`int`): Items per page
            - **pages** (`int`): Total number of pages
            
    **Response Example:**
    ```json
    {
        "items": [
            {
                "item": "ABC123",
                "description": "Pipe Fitting 3/4 inch",
                "mpi_item": "MPI001",
                "mpi_description": "Pipe Fittings"
            }
        ],
        "total": 150,
        "page": 1,
        "size": 10,
        "pages": 15
    }
    ```
    
    **Functionality:**
        - **With Query**: Performs search using the same logic as search-items endpoint
        - **Without Query**: Returns all distinct items within the date range
        
    **Search Behavior:**
        - Case-insensitive search across item codes and descriptions
        - Matches partial strings in item codes and descriptions
        - Returns items that contain the search term
        
    **Date Range Filtering:**
        - Only returns items that were used within the specified date range
        - Date range is inclusive (includes both from_date and to_date)
        - Items are distinct (no duplicates)
        
    **Error Codes:**
        - **500**: Internal server error during data retrieval
        
    **Notes:**
        - Designed for dropdown population in frontend
        - Returns distinct items only (no duplicates)
        - Pagination supports up to 100 items per page
        - Date range filtering ensures relevance of items
        - Search functionality provides quick item discovery
    """
    try:
        controller = MonthlyComparisonController(db)
        
        # If query parameter is provided, use search functionality
        if query:
            return await controller.search_mpi_items(
                search_term=query,
                from_date=date_range.from_date,
                to_date=date_range.to_date,
                page=page,
                size=size
            )
        
        # Otherwise, use the original functionality
        return await controller.get_items_in_date_range(
            from_date=date_range.from_date,
            to_date=date_range.to_date,
            page=page,
            size=size
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/selected-items", response_model=PaginatedEnrichedItemResponse)
async def get_selected_items_prices(
    items: List[ItemInfo],
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    db: AsyncSession = Depends(get_async_db),
    token: str = Depends(JWTBearer())
):
    """
    Get price comparison data for selected items with supplier information.
    
    **Summary:**
        Retrieves the most recent prices for specified items with comprehensive
        supplier information. This endpoint provides price comparison data including
        the cheapest price and all available supplier options for each item.
        
    **Request Body:**
        - **items** (`List[ItemInfo]`, required): Array of items to get price data for:
            - **item** (`str`): Item code
            - **description** (`str`): Item description
            - **mpi_item** (`str`): MPI item code
            - **mpi_description** (`str`): MPI description
            
    **Query Parameters:**
        - **page** (`int`, default=1): Page number for pagination (1-based)
        - **size** (`int`, default=10): Number of items per page (1-100)
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **PaginatedEnrichedItemResponse**: Paginated response containing:
            - **items** (`List[EnrichedItemPriceResponse]`): Array of items with price data
            - **total** (`int`): Total number of items
            - **page** (`int`): Current page number
            - **size** (`int`): Items per page
            - **pages** (`int`): Total number of pages
            
    **Response Example:**
    ```json
    {
        "items": [
            {
                "item": "ABC123",
                "description": "Pipe Fitting 3/4 inch",
                "mpi_item": "MPI001",
                "mpi_description": "Pipe Fittings",
                "cheapest_price": 12.50,
                "cheapest_supplier": "BMW Plumbing",
                "suppliers": [
                    {
                        "supplier_name": "BMW Plumbing",
                        "price": 12.50,
                        "last_purchase_date": "2024-01-15"
                    },
                    {
                        "supplier_name": "Flow Mark",
                        "price": 13.75,
                        "last_purchase_date": "2024-01-20"
                    }
                ]
            }
        ],
        "total": 25,
        "page": 1,
        "size": 10,
        "pages": 3
    }
    ```
    
    **Price Data:**
        - **Cheapest Price**: Lowest unit price available for each item
        - **Cheapest Supplier**: Supplier offering the lowest price
        - **All Suppliers**: Complete list of suppliers with their prices
        - **Last Purchase Date**: Most recent purchase date for each supplier
        
    **Supplier Information:**
        - All available suppliers for each item
        - Current pricing from each supplier
        - Historical purchase data
        - Price comparison across suppliers
        
    **Error Codes:**
        - **500**: Internal server error during data retrieval
        
    **Notes:**
        - Returns most recent price data for each item
        - Includes comprehensive supplier comparison
        - Pagination supports up to 100 items per page
        - Useful for price analysis and supplier selection
        - Data is enriched with supplier details and pricing
    """
    try:
        controller = MonthlyComparisonController(db)
        
        # Always use the enriched response with supplier information and pagination
        return await controller.get_enriched_items_with_suppliers(
            items=items,
            page=page,
            size=size
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Removed supplier-cheapest-items endpoint


@router.post("/selected-items-by-date-range", response_model=PaginatedEnrichedItemResponse)
async def get_items_by_date_range(
    request: DateRangeWithExclusions,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    db: AsyncSession = Depends(get_async_db),
    token: str = Depends(JWTBearer())
):
    """
    Get items within a date range with supplier information and optional exclusions.
    
    **Summary:**
        Retrieves all items within a specified date range with comprehensive
        supplier information and price comparison data. This endpoint allows
        excluding specific items from the results and provides enriched data
        for price analysis.
        
    **Request Body:**
        - **request** (`DateRangeWithExclusions`, required): Object containing:
            - **from_date** (`date`): Start date for the range (YYYY-MM-DD)
            - **to_date** (`date`): End date for the range (YYYY-MM-DD)
            - **unselected_items** (`List[str]`, optional): Array of item codes to exclude
            
    **Query Parameters:**
        - **page** (`int`, default=1): Page number for pagination (1-based)
        - **size** (`int`, default=10): Number of items per page (1-100)
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **PaginatedEnrichedItemResponse**: Paginated response containing:
            - **items** (`List[EnrichedItemPriceResponse]`): Array of items with price data
            - **total** (`int`): Total number of items
            - **page** (`int`): Current page number
            - **size** (`int`): Items per page
            - **pages** (`int`): Total number of pages
            
    **Response Example:**
    ```json
    {
        "items": [
            {
                "item": "ABC123",
                "description": "Pipe Fitting 3/4 inch",
                "mpi_item": "MPI001",
                "mpi_description": "Pipe Fittings",
                "cheapest_price": 12.50,
                "cheapest_supplier": "BMW Plumbing",
                "suppliers": [
                    {
                        "supplier_name": "BMW Plumbing",
                        "price": 12.50,
                        "last_purchase_date": "2024-01-15"
                    }
                ]
            }
        ],
        "total": 150,
        "page": 1,
        "size": 10,
        "pages": 15
    }
    ```
    
    **Request Example:**
    ```json
    {
        "from_date": "2025-01-01",
        "to_date": "2025-12-31",
        "unselected_items": ["ITEM001", "ITEM002"]
    }
    ```
    
    **Date Range Filtering:**
        - Returns items used within the specified date range
        - Date range is inclusive (includes both from_date and to_date)
        - Only items with activity in the date range are included
        
    **Exclusion Functionality:**
        - **unselected_items**: Array of item codes to exclude from results
        - Excluded items are completely removed from the response
        - Useful for removing specific items from comparison analysis
        
    **Price Data:**
        - **Cheapest Price**: Lowest unit price available for each item
        - **Cheapest Supplier**: Supplier offering the lowest price
        - **All Suppliers**: Complete list of suppliers with their prices
        - **Last Purchase Date**: Most recent purchase date for each supplier
        
    **Error Codes:**
        - **500**: Internal server error during data retrieval
        
    **Notes:**
        - Returns most recent price data for each item
        - Includes comprehensive supplier comparison
        - Pagination supports up to 100 items per page
        - Excluded items are completely filtered out
        - Useful for bulk price analysis and supplier comparison
        - Date range filtering ensures relevance of data
    """
    try:
        controller = MonthlyComparisonController(db)
        return await controller.get_items_by_date_range_with_suppliers(
            from_date=request.from_date,
            to_date=request.to_date,
            unselected_items=request.unselected_items,
            page=page,
            size=size
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
