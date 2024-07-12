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
    invoice_id: Optional[UUID]
    class Config:
        from_attributes = True


class UpdateInvoiceItemRequest(BaseModel):
    ref_no: str
    sheet_name: Optional[str] = Field(None)
    item: Optional[str] = Field(None)
    description: Optional[str] = Field(None)
    qty: Optional[int] = Field(None)
    cost: Optional[float] = Field(None)
    amount: Optional[str] = Field(None)
    date: Optional[str] = Field(None)
    po_number: Optional[str] = Field(None)
    customer_job: Optional[str] = Field(None)
    bill: Optional[str] = Field(None)
    vendor: Optional[str] = Field(None)
    class_: Optional[str] = Field(None)
    memo: Optional[str] = Field(None)
    buyer: Optional[str] = Field(None)
