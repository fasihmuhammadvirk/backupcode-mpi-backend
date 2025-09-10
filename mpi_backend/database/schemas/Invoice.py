from pydantic import BaseModel
from typing import List, Optional
from datetime import date


class Invoice(BaseModel):
    date: date
    filename: str
    supplier_id: int
    status: str
    invoice_id: str
    is_exported: str

    class Config:
        from_attributes = True

class PaginatedInvoiceResponse(BaseModel):
    items: List[Invoice]
    total: int
    page: int
    size: int
    pages: int