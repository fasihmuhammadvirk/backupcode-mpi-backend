from pydantic import BaseModel, Field, field_validator, validator
from typing import List, Any

from sqlalchemy import RowMapping

from mpi_backend.utils.number_formatter import format_currency


class MappingsReviewItemRequest(BaseModel):
    """Schema for a single mapping review item"""
    vendor: str = Field(..., description="Vendor/Supplier name")
    item_id: str = Field(..., description="Original item ID from the supplier")
    reason: str = Field(..., description="Reason for isolation/review")
    map_to_item: str = Field(..., description="The MPI item code it should map to")

    @field_validator('vendor', 'item_id', 'reason', 'map_to_item')
    @classmethod
    def not_empty(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError('Must not be empty or whitespace only.')
        return v.strip()


class IsolatedItemResponse(BaseModel):
    """Response schema for a single isolated item with metadata joined from analytics mart"""
    id: str = Field(..., description="Primary key of the isolated item record")
    vendor: str = Field(..., description="Vendor/Supplier name")
    item_id: str = Field(..., description="Original item ID from the supplier")
    description: str = Field(..., description="Item description (from mart joined with isolated snapshot)")
    reason: str = Field(..., description="Reason provided during isolation")
    map_to_item: str = Field(..., description="Proposed MPI item code to map to")
    mapping_type: str = Field(..., description="Current mapping type status (from mart join)")
    status: str = Field(..., description="Review status of the item (pending, done)")
    amount: str = Field(..., description="Total amount value (formatted)")
    isolated_at: str = Field(..., description="When the item was isolated for review")

    @classmethod
    def from_dict(cls, data: dict[str,Any]) -> "IsolatedItemResponse":
        """Create an IsolatedItemResponse instance from a RowMapping."""
        return cls(
            id=str(data.get("id")),
            vendor=data.get("vendor"),
            item_id=data.get("item_id"),
            description=data.get("original_description", ""),
            reason=data.get("reason"),
            map_to_item=data.get("map_to_item"),
            mapping_type=data.get("mapping_type", "no_match"),
            status=data.get("status", "pending"),
            amount=format_currency(data.get("amount") or 0.0),
            isolated_at=data.get("created_at").strftime("%Y-%m-%d %H:%M:%S") if data.get("created_at") else ""
        )

class PaginatedIsolatedItemsResponse(BaseModel):
    """Paginated response for listed isolated items"""
    items: List[IsolatedItemResponse]
    total_count: int
    page: int
    size: int
    pages: int
