from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from mpi_backend.database import get_db
from mpi_backend.database.schemas.PriceComparison import (
    PriceComparisonDateRange, ItemInfo, ItemPriceResponse, SupplierCheapestItemsResponse
)
from mpi_backend.database.controllers.PriceComparisonController import (
    PriceComparisonController
)
from mpi_backend.utils.auth.auth_bearer import JWTBearer


router = APIRouter(
    prefix="/price-comparison",
    tags=["Price Comparison"]
)


@router.post("/dropdown-items", response_model=List[ItemInfo])
async def get_dropdown_items(
    date_range: PriceComparisonDateRange,
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Get distinct items that were used within the specified date range.
    """
    try:
        controller = PriceComparisonController(db)
        return controller.get_items_in_date_range(
            from_date=date_range.from_date,
            to_date=date_range.to_date
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
