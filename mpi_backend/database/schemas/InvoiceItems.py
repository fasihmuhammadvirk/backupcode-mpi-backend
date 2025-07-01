from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import date
from uuid import UUID


class InvoiceItems(BaseModel):
    id: Optional[int]
    filename: Optional[str]
    sheet_name: Optional[str]
    mpi_item: Optional[str]
    mpi_description: Optional[str]
    item: Optional[str]
    description: Optional[str]
    qty: Optional[int]
    cost: Optional[float]
    amount: Optional[str]
    date: Optional[str]
    ref_no: Optional[str]
    po_number: Optional[str]
    customer_job: Optional[str]
    bill: Optional[str]
    vendor: Optional[str]
    class_: Optional[str]  # 'class' is reserved in Python
    memo: Optional[str]
    buyer: Optional[str]
    date_added: Optional[str]
    invoice_id: Optional[UUID]
    is_active: Optional[bool]
    
    class Config:
        from_attributes = True

    @validator('date', 'date_added', pre=True)
    def format_date(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                parsed_date = date.fromisoformat(value)
                return parsed_date.strftime("%m/%d/%Y")
            except ValueError:
                return value  # already is US format, or is invalid
        if isinstance(value, date):
            return value.strftime("%m/%d/%Y")
        return value


class PaginatedInvoiceItemsResponse(BaseModel):
    items: List[InvoiceItems]
    total: int
    page: int
    size: int
    pages: int


class UpdateInvoiceItemRequest(BaseModel):
    id: int
    filename: str = None
    sheet_name: str = None
    mpi_item: str = None
    mpi_description: str = None
    item: str = None
    description: str = None
    qty: int = None
    cost: float = None
    amount: str = None
    date: str = None
    ref_no: str = None
    po_number: str = None
    customer_job: str = None
    bill: str = None
    vendor: str = None
    class_: str = None
    memo: str = None
    buyer: str = None
    date_added: str = None
    invoice_id: str = None
    is_active: bool = None


class ToggleVisibilityRequest(BaseModel):
    ids: List[int]
    make_visible: bool = False


# New schemas for unmapped items endpoint
class UnmappedItemResponse(BaseModel):
    """Response model for individual unmapped item"""
    original_item_id: str
    mpi_item_id: Optional[str]
    mpi_description: Optional[str]
    sheet_name: Optional[str]
    supplier: Optional[str]

    class Config:
        from_attributes = True


class UnmappedItemsFilterRequest(BaseModel):
    """Request model for filtering unmapped items"""
    item_type: str = Field(
        ..., description="Type of items to retrieve: 'temporary' or 'unmapped'"
    )
    date_from: Optional[date] = Field(None, description="Start date filter")
    date_to: Optional[date] = Field(None, description="End date filter")
    supplier_names: Optional[List[str]] = Field(
        None, description="List of supplier names to filter by"
    )
    search: Optional[str] = Field(
        None, description="Search term to filter items by item code"
    )
    order_by: Optional[List[dict]] = Field(
        None, description="List of order criteria with column and order fields"
    )


class PaginatedUnmappedItemsResponse(BaseModel):
    """Paginated response for unmapped items"""
    items: List[UnmappedItemResponse]
    total_count: int
    page: int
    size: int
    pages: int

    class Config:
        from_attributes = True
