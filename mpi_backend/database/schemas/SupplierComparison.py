import json
from datetime import date
from decimal import Decimal
from typing import List, Optional, ClassVar, Dict
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import RowMapping

class SupplierComparisonRequest(BaseModel):
    SORT_MAP: ClassVar[Dict[str, str]] = {
        "potential_savings": "potential_savings",
        "quotes": "quotes_count",
        "item_description": "item_description",
        "best_price": "best_price"
    }

    from_date: Optional[date] = Field(None, description="Start date for filtering (YYYY-MM-DD)")
    to_date: Optional[date] = Field(None, description="End date for filtering (YYYY-MM-DD)")
    supplier_name: Optional[str] = Field(None, description="Filter items that have at least one record from this supplier")
    item_mpi_codes: Optional[List[str]] = Field(None, description="Exact MPI item codes to filter by")
    search: Optional[str] = Field(None, description="Search by item code or reference number")
    page: Optional[int] = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=300)
    sort_by: Optional[str] = Field("potential_savings", description="Field to sort by")
    sort_order: Optional[str] = Field("desc", description="Sort order (asc, desc)")

    @model_validator(mode='after')
    def validate_request(self) -> "SupplierComparisonRequest":
        #sort_by validation
        if self.sort_by and self.sort_by not in self.SORT_MAP:
            raise ValueError("Invalid sort_by value.")

        # Date validation
        if self.from_date is not None and self.to_date is not None:
            if self.from_date > self.to_date:
                raise ValueError("from_date must be before or equal to to_date")
        return self

    @property
    def sort_column(self) -> str:
        """Map sort_by to actual database column name."""
        return self.SORT_MAP.get(self.sort_by or "potential_savings", "potential_savings")

    @property
    def sort_dir(self) -> str:
        """Return SQL sort direction."""
        return "ASC" if self.sort_order and self.sort_order.lower() == "asc" else "DESC"


class SupplierComparisonSummary(BaseModel):
    total_missed_savings: Decimal
    item_count: int
    highest_priced_supplier: Optional[str]
    highest_priced_excess_amount: Decimal = Field(default=Decimal(0))
    highest_impact_item_codes: List[str] = Field(default_factory=list)
    highest_priced_loss_rate: float
    top_value_supplier: Optional[str]
    top_value_saved_amount: Decimal = Field(default=Decimal(0))
    top_value_win_rate: float
    top_value_item_codes: List[str] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: RowMapping) -> "SupplierComparisonSummary":
        return cls(
            total_missed_savings=Decimal(str(data["total_missed_savings"] or 0)),
            item_count=data["item_count"] or 0,
            highest_priced_supplier=data["highest_priced_supplier"],
            highest_priced_excess_amount=Decimal(str(data["highest_excess"] or 0)),
            highest_priced_loss_rate=float(data["highest_loss_rate"] or 0),
            highest_impact_item_codes=data["highest_impact_item_codes"] or [],
            top_value_supplier=data["top_value_supplier"],
            top_value_saved_amount=Decimal(str(data["top_saved"] or 0)),
            top_value_win_rate=float(data["top_win_rate"] or 0),
            top_value_item_codes=data["top_value_item_codes"] or []
        )

class ItemVendorComparisonDetail(BaseModel):
    supplier_name: str
    purchase_date: str
    ref_no: Optional[str]
    filename : Optional[str]
    quantity: float
    unit_price: Decimal
    variance_amount: Decimal
    variance_percentage: float
    is_best_value: bool
    is_worst_quote: bool = False
    is_price_rerated : bool = False
    original_current_qty: Optional[float]
    original_current_price: Decimal

    @classmethod
    def from_dict(cls, d: dict) -> "ItemVendorComparisonDetail":
        return cls(
            supplier_name=d["supplier_name"],
            purchase_date=d["purchase_date"],
            ref_no=d["ref_no"],
            filename=d["filename"],
            quantity=float(d["quantity"]) if d["quantity"] is not None else 0.0,
            unit_price=Decimal(str(d["unit_price"] or 0)),
            variance_amount=Decimal(str(d["variance_amount"] or 0)),
            variance_percentage=float(d["variance_percentage"] or 0),
            is_best_value=bool(d["is_best_value"]),
            is_worst_quote=bool(d.get("is_worst_quote", False)),
            is_price_rerated=bool(d.get("is_price_rerated", False)),
            original_current_qty=float(d["original_current_qty"]) if d.get("original_current_qty") is not None else None,
            original_current_price=Decimal(str(d["original_current_price"] or 0))
        )

class SupplierComparisonTableItem(BaseModel):
    item_mpi_code: str
    item_description: str
    quotes_count: int
    best_price: Decimal
    potential_savings: Decimal
    vendor_details: List[ItemVendorComparisonDetail]

    @classmethod
    def from_dict(cls, data: RowMapping) -> "SupplierComparisonTableItem":
        details_raw = data["vendor_details"]
        if isinstance(details_raw, str):
            details_raw = json.loads(details_raw)
        
        vendor_details = [ItemVendorComparisonDetail.from_dict(d) for d in details_raw] if details_raw else []
        
        return cls(
            item_mpi_code=data["item_mpi_code"],
            item_description=data["item_description"] or "",
            quotes_count=data["quotes_count"],
            best_price=Decimal(str(data["best_price"] or 0)),
            potential_savings=Decimal(str(data["potential_savings"] or 0)),
            vendor_details=vendor_details
        )

class SupplierComparisonResponse(BaseModel):
    items: List[SupplierComparisonTableItem]
    total_count: int
    page: int
    page_size: int
