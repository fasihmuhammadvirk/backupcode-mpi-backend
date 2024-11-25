from pydantic import BaseModel, Field
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
    item: Optional[str]
    description: Optional[str]
    qty: Optional[int]
    cost: Optional[float]
    amount: Optional[str]
    date: Optional[date]
    ref_no: Optional[str]
    po_number: Optional[str]
    customer_job: Optional[str]
    bill: Optional[str]
    vendor: Optional[str]
    class_: Optional[str]  # 'class' is a reserved word in Python, so appending an underscore
    memo: Optional[str]
    buyer: Optional[str]
    date_added: Optional[date]
    invoice_id: Optional[UUID]
    class Config:
        from_attributes = True

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
