from fastapi import APIRouter, Depends, HTTPException,Query
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


@router.get("/column-mapping")
def column_mappings(token: str = Depends(JWTBearer())):
    # backend to frontend mappings of columns
    column_mapping = {
        "filename": "Filename",
        "sheet_name": "Sheet Name",
        "mpi_item": "MPI Item Code",
        "mpi_description": "MPI Description",
        "item": "Item",
        "description": "Description",
        "qty": "Quantity",
        "cost": "Cost",
        "amount": "Amount",
        "date": "Date",
        "ref_no": "Reference Number",
        "po_number": "PO Number",
        "customer_job": "Customer Job",
        "bill": "Bill",
        "vendor": "Vendor",
        "class_": "Class",
        "memo": "Memo",
        "buyer": "Buyer",
        "date_added": "Date Added"
    }
    return column_mapping


@router.get("/by-column")
def column_mappings(db: Session = Depends(get_db), token: str = Depends(JWTBearer()),
                    column_name: str = Query(None, description="Name of Column for which data is required")
                    ):
    if column_name is None:
        return {"data": "Invalid Column Name Specified"}

    distinct_values = InvoiceItemController(db).get_data_by_column_name(column_name)
    return distinct_values
