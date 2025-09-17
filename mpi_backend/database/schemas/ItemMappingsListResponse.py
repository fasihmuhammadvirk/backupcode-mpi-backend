from pydantic import BaseModel
from typing import List


class ItemMappingsResponse(BaseModel):
    supplier_id: str
    supplier_item_ids: str
    mpi_code: str
    description: str
    type: str


class ItemMappingsByMpiType(BaseModel):
    mpi_description: str
    type: str


class UpdateMappingRequest(BaseModel):
    supplier_id: str
    mapping: List[dict]
