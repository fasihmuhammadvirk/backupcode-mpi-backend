from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from mpi_backend.database.controllers import ItemsMappingController
from mpi_backend.database.schemas import ItemMappingsResponse

router = APIRouter(prefix="/mapping")


@router.get("/{supplier_id}", response_model=List[ItemMappingsResponse])
def get_mapping_by_supplier_id(supplier_id: int, db: Session = Depends(get_db)):
    try:
        mappings = ItemsMappingController(db).get_items_mappings_by_supplier_id(supplier_id)
        return mappings
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch item mapping by supplier id: {e}")

