from pydantic import BaseModel, Field, validator
from datetime import date, datetime
from typing import Optional, List, Dict, Any, Union
from pydantic.generics import GenericModel
from typing import TypeVar, Generic

T = TypeVar('T')

class PaginatedResponse(GenericModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    size: int
    pages: int

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

class DateRangeWithExclusions(PriceComparisonDateRange):
    """Schema for date range with optional list of items to exclude."""
    unselected_items: Optional[List[ItemInfo]] = Field(None, description="Optional list of items to exclude from results")
    
    class Config:
        json_schema_extra = {
            "example": {
                "from_date": "2025-01-01",
                "to_date": "2025-12-31",
                "unselected_items": [
                    {
                        "id": 3656,
                        "mpi_item": "03112",
                        "original_item": "",
                        "mpi_description": ""
                    }
                ]
            }
        }

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

class EnrichedItemPriceResponse(ItemInfo):
    """Combined response schema with both cheapest price and supplier information."""
    cheapest_unit_price: float = Field(..., description="Lowest unit price from any supplier")
    suppliers: List[SupplierPriceInfo] = Field(
        ..., 
        description="List of suppliers with their lowest prices for this item"
    )

class PaginatedEnrichedItemResponse(PaginatedResponse[EnrichedItemPriceResponse]):
    """Paginated response for EnrichedItemPriceResponse."""
    class Config:
        schema_extra = {
            "example": {
                "items": [
                    {
                        "id": 1,
                        "mpi_item": "ITEM001",
                        "original_item": "ORIG001",
                        "mpi_description": "Sample item description",
                        "cheapest_unit_price": 10.99,
                        "suppliers": [
                            {
                                "id": 1,
                                "name": "Supplier A",
                                "unit_price": 10.99
                            },
                            {
                                "id": 2,
                                "name": "Supplier B",
                                "unit_price": 12.99
                            }
                        ]
                    }
                ],
                "total": 1,
                "page": 1,
                "size": 10,
                "pages": 1
            }
        }

class ItemSearchRequest(BaseModel):
    """Schema for MPI item search request."""
    query: str = Field(..., description="Search term for MPI items")
    from_date: Optional[date] = Field(None, description="Start date for filtering (YYYY-MM-DD)")
    to_date: Optional[date] = Field(None, description="End date for filtering (YYYY-MM-DD)")
    page: int = Field(1, ge=1, description="Page number (1-based)")
    size: int = Field(10, ge=1, le=100, description="Number of items per page")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "C",
                "from_date": "2025-01-01",
                "to_date": "2025-12-31",
                "page": 1,
                "size": 10
            }
        }

class PaginatedItemInfoResponse(PaginatedResponse[ItemInfo]):
    """Paginated response for ItemInfo."""
    class Config:
        schema_extra = {
            "example": {
                "items": [
                    {
                        "id": 1,
                        "mpi_item": "ITEM001",
                        "original_item": "ORIG001",
                        "mpi_description": "Sample item description"
                    }
                ],
                "total": 1,
                "page": 1,
                "size": 10,
                "pages": 1
            }
        }
