from fastapi import APIRouter, Depends, HTTPException
from typing import List
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.controllers import SupplierController, InvoiceItemController
from mpi_backend.utils.auth.auth_bearer import JWTBearer

router = APIRouter(prefix="/filter")


@router.get("/get-locations", response_model=List[str])
def customer_job_filter(db: Session = Depends(get_db),  token: str = Depends(JWTBearer())):
    try:
        customer_jobs = InvoiceItemController(db).get_customer_jobs(db)
        supplier_dict = {records.customer_job for records in customer_jobs if records.customer_job}
        return supplier_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch customer-job address: {e}")
