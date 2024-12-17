from pydantic import BaseModel
from typing import List, Dict, Any, Union,Optional
from datetime import date


class PriceHistoryRequest(BaseModel):
    item_number: str
    description: str
    vendor: str


class PriceHistoryResponse(BaseModel):
    ref_no: str
    date: date
    cost: float
    qty:int