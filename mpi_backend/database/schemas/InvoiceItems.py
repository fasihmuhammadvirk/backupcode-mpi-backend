from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from uuid import UUID


class InvoiceItems(BaseModel):
    id: Optional[int]
    filename: Optional[str]
    sheet_name: Optional[str]
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
