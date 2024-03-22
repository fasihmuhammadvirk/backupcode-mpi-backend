from pydantic import BaseModel
from typing import List, Optional
from datetime import date


class Invoice(BaseModel):
    date: date
    filename: str
    supplier: str
    status: str
    class Config:
        from_attributes = True
