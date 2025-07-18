from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging

from mpi_backend.database import get_db
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.utils.auth.auth_bearer import JWTBearer

router = APIRouter(prefix="/supplier", tags=["Supplier"])
logger = logging.getLogger(__name__)


@router.get("")
def get_supplier_list(db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    logger.info("GET /supplier - Fetching supplier list")
    try:
        suppliers = SupplierController(db).get_all_suppliers()
        supplier_dict = {str(supplier.id): supplier.supplier_name for supplier in suppliers}
        logger.info(f"GET /supplier - Successfully fetched {len(supplier_dict)} suppliers")
        return supplier_dict
    except Exception as e:
        logger.error(f"GET /supplier - Failed to fetch suppliers: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch suppliers: {e}")
