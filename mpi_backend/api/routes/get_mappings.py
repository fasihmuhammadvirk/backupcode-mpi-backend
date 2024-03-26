from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from mpi_backend.database.controllers import ItemsMappingController
from mpi_backend.database.schemas import ItemMappingsResponse,ItemMappingsByMpiTypeResponse

router = APIRouter(prefix="/mapping")


@router.get("/mpi_types", response_model=ItemMappingsByMpiTypeResponse)
def get_mapping_by_mpi_type(db: Session = Depends(get_db)):
    try:
        mappings = ItemsMappingController(db).get_items_mappings_by_mpi_type()
        return mappings
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch item mapping by MPI type: {e}")


@router.get("/{supplier_id}", response_model=List[ItemMappingsResponse])
def get_mapping_by_supplier_id(supplier_id: int, db: Session = Depends(get_db)):
    try:
        mappings = ItemsMappingController(db).get_items_mappings_by_supplier_id(supplier_id)
        return mappings
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch item mapping by supplier id: {e}")
