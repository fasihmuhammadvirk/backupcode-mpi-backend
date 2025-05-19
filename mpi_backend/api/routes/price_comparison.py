from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from mpi_backend.database import get_db
from mpi_backend.database.schemas.PriceComparison import (
    PriceComparisonDateRange, ItemInfo, ItemPriceInfo
)
from mpi_backend.database.controllers.PriceComparisonController import (
    PriceComparisonController
)


router = APIRouter(
    prefix="/price-comparison",
    tags=["price-comparison"]
)


@router.post("/dropdown-items", response_model=List[ItemInfo])
async def get_dropdown_items(
    date_range: PriceComparisonDateRange,
    db: Session = Depends(get_db)
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


@router.post("/selected-items", response_model=List[ItemPriceInfo])
async def get_selected_items_prices(
    items: List[ItemInfo],
    db: Session = Depends(get_db)
):
    """
    Get the most recent prices for the specified items.
    """
    try:
        controller = PriceComparisonController(db)
        return controller.get_items_prices(items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 