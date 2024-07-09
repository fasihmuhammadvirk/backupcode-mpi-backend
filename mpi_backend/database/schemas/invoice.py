from pydantic import BaseModel
from typing import List, Optional
from datetime import date


class Invoice(BaseModel):
    date: date
    filename: str
    supplier_id: int
    status: str
    invoice_id: str
    ref_no: str
    customer_job: str

    class Config:
        from_attributes = True
