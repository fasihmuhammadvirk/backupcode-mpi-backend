from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session
from typing import List, Optional, Union
from sqlalchemy import or_

from mpi_backend.database import get_db
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
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Get paginated distinct items that were used within the specified date range.
    
    If a query parameter is provided, the endpoint will perform a search using the same
    logic as the search-items endpoint and return filtered results.
    
    If no query parameter is provided, it returns all items within the date range.
    """
    try:
        controller = MonthlyComparisonController(db)
        
        # If query parameter is provided, use search functionality
        if query:
            return controller.search_mpi_items(
                search_term=query,
                from_date=date_range.from_date,
                to_date=date_range.to_date,
                page=page,
                size=size
            )
        
        # Otherwise, use the original functionality
        return controller.get_items_in_date_range(
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
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Get the most recent prices for the specified items with supplier information.
    
    Returns a paginated list of items with their cheapest price and all supplier options.
    Each item includes the lowest unit price and a list of suppliers with their prices.
    """
    try:
        controller = MonthlyComparisonController(db)
        
        # Always use the enriched response with supplier information and pagination
        return controller.get_enriched_items_with_suppliers(
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
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Get items within a date range with supplier information, optionally excluding specific items.
    
    Returns a paginated list of items with their cheapest price and all supplier options.
    Each item includes the lowest unit price and a list of suppliers with their prices.
    
    Example request body:
    {
        "from_date": "2025-01-01",
        "to_date": "2025-12-31",
        "unselected_items": ["ITEM001", "ITEM002"]
    }
    """
    try:
        controller = MonthlyComparisonController(db)
        return controller.get_items_by_date_range_with_suppliers(
            from_date=request.from_date,
            to_date=request.to_date,
            unselected_items=request.unselected_items,
            page=page,
            size=size
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
