from pydantic import BaseModel
from typing import Dict


class SupplierListResponse(BaseModel):
    suppliers: Dict[str, str]
