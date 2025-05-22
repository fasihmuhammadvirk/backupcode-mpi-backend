from pydantic import BaseModel, Field, validator
from datetime import date, datetime
from typing import Optional, List, Dict, Any, Union


class PriceComparisonDateRange(BaseModel):
    """Schema for date range input in price comparison endpoints."""
    from_date: date = Field(..., description="Start date for price comparison (YYYY-MM-DD)")
    to_date: date = Field(..., description="End date for price comparison (YYYY-MM-DD)")


class ItemInfo(BaseModel):
    """Schema for basic item information."""
    id: int = Field(..., description="Unique identifier for the item")
    mpi_item: str = Field(..., description="MPI item code")
    original_item: str = Field(..., description="Original item code")
    mpi_description: str = Field(..., description="MPI item description")


class ItemPriceResponse(ItemInfo):
    """Simplified response schema for item prices with lowest unit price."""
    unit_price: float = Field(..., description="Lowest unit price from any supplier")

class SupplierPriceInfo(BaseModel):
    """Schema for supplier price information."""
    id: int = Field(..., description="Supplier ID")
    name: str = Field(..., description="Supplier name")
    unit_price: float = Field(..., description="Lowest unit price from this supplier")

class SupplierCheapestItemsResponse(ItemInfo):
    """Response schema for getting cheapest items per supplier."""
    suppliers: List[SupplierPriceInfo] = Field(
        ..., 
        description="List of suppliers with their lowest prices for this item"
    )
