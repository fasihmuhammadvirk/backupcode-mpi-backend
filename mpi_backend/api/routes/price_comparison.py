from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session
from typing import List, Optional
from sqlalchemy import or_

from mpi_backend.database import get_db
from mpi_backend.database.schemas.PriceComparison import (
    ItemInfo, 
    ItemPriceResponse, 
    PaginatedItemInfoResponse,
    SupplierPriceInfo,
    PriceComparisonDateRange,
    ItemSearchRequest,
    SupplierCheapestItemsResponse
)
from mpi_backend.database.controllers.PriceComparisonController import (
    PriceComparisonController
)
from mpi_backend.utils.auth.auth_bearer import JWTBearer


router = APIRouter(
    prefix="/price-comparison",
    tags=["Price Comparison"]
)


@router.post("/search-items", response_model=PaginatedItemInfoResponse)
async def search_mpi_items(
    search_request: ItemSearchRequest,
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Search for MPI items by item code with optional date range filtering.
    Returns items starting with the search term first, then items containing the term.
    
    Example request body:
    {
        "query": "C",
        "from_date": "2025-01-01",
        "to_date": "2025-12-31",
        "page": 1,
        "size": 10
    }
    """
    try:
        controller = PriceComparisonController(db)
        return controller.search_mpi_items(
            search_term=search_request.query,
            from_date=search_request.from_date,
            to_date=search_request.to_date,
            page=search_request.page,
            size=search_request.size
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dropdown-items", response_model=PaginatedItemInfoResponse)
async def get_dropdown_items(
    date_range: PriceComparisonDateRange,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Get paginated distinct items that were used within the specified date range.
    """
    try:
        controller = PriceComparisonController(db)
        return controller.get_items_in_date_range(
            from_date=date_range.from_date,
            to_date=date_range.to_date,
            page=page,
            size=size
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/selected-items", response_model=List[ItemPriceResponse])
async def get_selected_items_prices(
    items: List[ItemInfo],
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Get the most recent prices for the specified items.
    """
    try:
        controller = PriceComparisonController(db)
        return controller.get_items_prices(items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/supplier-cheapest-items", response_model=List[SupplierCheapestItemsResponse])
async def get_supplier_cheapest_items(
    items: List[ItemInfo],
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Get the lowest unit price per supplier for each item.
    
    Returns a list of items with their suppliers and the lowest price
    offered by each supplier for that item.
    """
    try:
        controller = PriceComparisonController(db)
        result = controller.get_cheapest_prices_per_supplier(items)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch supplier prices: {str(e)}"
        )
