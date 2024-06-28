from pydantic import BaseModel
from typing import List,Dict
from mpi_backend.database.models import ItemsMapping


class ItemMappingsResponse(BaseModel):
    supplier_id: str
    supplier_item_ids: str
    mpi_code: str
    description: str
    type: str


class ItemMappingsByMpiType(BaseModel):
    mpi_description: str
    type: str


class ItemMappingsByMpiTypeResponse(BaseModel):
    __root__: Dict[str, ItemMappingsByMpiType]


class UpdateMappingRequest(BaseModel):
    supplier_id: str
    mapping: List[dict]
