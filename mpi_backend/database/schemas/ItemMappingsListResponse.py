from pydantic import BaseModel
from typing import List,Dict
from mpi_backend.database.models import ItemsMapping


class ItemMappingsResponse(BaseModel):
    supplier_id: str
    supplier_item_ids: str
    mpi_code: str
    description: str
    google_sheet_name: str

