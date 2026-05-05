import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import RowMapping

logger = logging.getLogger(__name__)

class POItemResponse(BaseModel):
    """Schema for purchase order item price comparison response."""
    invoice_item_id: Decimal
    filename:Optional[str]
    item_code: str
    item_description: str
    item_cost: Decimal
    item_quantity: float
    purchase_date: date
    supplier_id: Optional[int]
    supplier_name: Optional[str]
    item_mpi_code: Optional[str]
    item_mpi_description: Optional[str]
    is_fallback: bool = False

    @classmethod
    def from_dict(cls, data: RowMapping) -> "POItemResponse":
        """
        Create a POItemResponse instance from a RowMapping.
        Ensures proper type conversion for fields like Decimal.
        """
        logger.debug(f"Creating POItemResponse from data: {data}")
        return cls(
            invoice_item_id=Decimal(data["invoice_items_id"]),
            filename=data["filename"],
            item_code=data["item_code"],
            item_description=data["item_description"],
            item_cost=Decimal(data["item_cost"]) if data["item_cost"] is not None else Decimal("0.00"),
            item_quantity=1.0,
            purchase_date=data["purchase_date"],
            supplier_id=int(data["supplier_id"]) if data["supplier_id"] is not None else None,
            supplier_name=data["supplier_name"],
            item_mpi_code=data["item_mpi_code"],
            item_mpi_description=data["item_mpi_description"],
            is_fallback=data.get("is_fallback", False),
        )

    def to_dict(self) -> dict:
        """Convert the POItemResponse instance to a dictionary."""
        logger.debug(f"Converting POItemResponse to dict: {self}")
        return {
            "original_item_id": str(self.invoice_item_id),
            "filename": self.filename,
            "item": self.item_code,
            "description": self.item_description,
            "cost": str(self.item_cost),
            "qty": str(self.item_quantity),
            "date": self.purchase_date.isoformat(),
            "supplier": self.supplier_name,
            "mpi_item": self.item_mpi_code,
            "mpi_description": self.item_mpi_description,
            "is_fallback": self.is_fallback,
        }

class POBulkImportRequest(BaseModel):
    """Schema for bulk import of purchase order items."""
    item_mpi_codes: Optional[List[str]] = Field(None, description="MPI code for items")
    item_codes: Optional[List[str]] = Field(None, description="Item codes identified from invoice")
    supplier_names: Optional[List[str]] = Field(None, description="Supplier names list")
    from_date: Optional[date] = Field(None, description="Start date for filtering purchase orders (YYYY-MM-DD)")
    to_date: Optional[date] = Field(None, description="End date for filtering purchase orders (YYYY-MM-DD)")

    @model_validator(mode='after')
    def validate_request(self):
        if not self.item_mpi_codes and not self.item_codes:
            raise ValueError("Either item_mpi_codes or item_codes must be provided")
        if self.item_mpi_codes and self.item_codes:
            raise ValueError("Both item_mpi_codes and item_codes are not allowed")

        # Date validation
        if (self.from_date is None) != (self.to_date is None):
            raise ValueError("from_date and to_date must be provided")
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be before or equal to to_date")
        return self


class PODraftItem(BaseModel):
    id: Optional[str]
    mpiCode: Optional[str]
    orgItemCode: Optional[str]
    description: Optional[str]
    qty: float
    internalUnitPrice: float
    bestSupplier: Optional[str]
    supplierPrices: Dict[str, float]
    filename: Optional[str]

class PODraftMetadata(BaseModel):
    fromDate: Optional[date]
    toDate: Optional[date]

class PODraftCreate(BaseModel):
    name: Optional[str] = None
    items: List[PODraftItem]
    metadata: PODraftMetadata

class PODraftSummary(BaseModel):
    id: Optional[uuid.UUID]
    name: Optional[str]
    from_date: Optional[date]
    to_date: Optional[date]
    items_count: Optional[int]
    saved_at: datetime

    class Config:
        from_attributes = True

class PODraftDetail(PODraftSummary):
    data: Dict[str, Any]

class PaginatedPODraftResponse(BaseModel):
    items: List[PODraftSummary]
    total: int
    page: int
    size: int
    pages: int