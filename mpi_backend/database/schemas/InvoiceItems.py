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
    class_: Optional[str]  # 'class' is a reserved word in Python, so appending an underscore
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
                return value # already is US format, or is invalid
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
    is_active:bool = None

class ToggleVisibilityRequest(BaseModel):
    ids: List[int]
    make_visible: bool = False
