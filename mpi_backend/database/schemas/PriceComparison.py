from pydantic import BaseModel, Field
from datetime import date
from typing import Optional


class PriceComparisonDateRange(BaseModel):
    """Schema for date range input in price comparison endpoints."""
    from_date: date = Field(..., description="Start date for price comparison")
    to_date: date = Field(..., description="End date for price comparison")


class ItemInfo(BaseModel):
    """Schema for basic item information."""
    mpi_item: str = Field(..., description="MPI item code")
    original_item: str = Field(..., description="Original item code")
    mpi_description: str = Field(..., description="MPI item description")


class ItemPriceInfo(ItemInfo):
    """Schema for item information with price."""
    unit_price: Optional[float] = Field(
        None,
        description="Most recent unit price for the item"
    ) 