from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.controllers import SupplierController

router = APIRouter(prefix="/supplier")


@router.get("")
def get_supplier_list(db: Session = Depends(get_db)):
    try:
        suppliers = SupplierController(db).get_all_suppliers()
        supplier_dict = {str(supplier.id): supplier.supplier_name for supplier in suppliers}
        return supplier_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch suppliers: {e}")
