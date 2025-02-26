from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from mpi_backend.database.controllers import SupplierController, InvoiceItemController
from mpi_backend.database.schemas import FilterRequest, PaginatedInvoiceItemsResponse, PriceHistoryRequest, \
    PriceHistoryResponse
from mpi_backend.database.schemas import InvoiceItems
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.pdf_to_excel.formatting_util import convert_download_price_history
router = APIRouter(prefix="/filter")


@router.get("/get-locations", response_model=List[str])
def customer_job_filter(db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
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


@router.post("/by-column")  # for dropdown population
def column_mappings(db: Session = Depends(get_db),
                    token: str = Depends(JWTBearer()),
                    column_name: str = Query(None, description="Name of Column for which data is required"),
                    payload: Optional[Dict] = Body(None,
                                                   description="Previous selections of filters & their values as json.")):
    if column_name is None:
        return {"data": "Invalid Column Name Specified"}

    if payload:
        filter_context = payload["filter_context"]
    else:
        filter_context = None

    distinct_values = InvoiceItemController(db).get_data_by_column_name(column_name, filter_context)
    return distinct_values


@router.post("", response_model=PaginatedInvoiceItemsResponse)
def filter_data(request: FilterRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer()),
                page: int = Query(1, ge=1),
                size: int = Query(10)):
    filtered_data = InvoiceItemController(db).apply_filters(request, page, size)
    return filtered_data


@router.post("/price-history", response_model=List[PriceHistoryResponse])
def get_price_history(request: PriceHistoryRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    price_history = InvoiceItemController(db).get_price_history(request)
    return price_history

@router.post("/download-price-history" )
def download_price_history(request: PriceHistoryRequest, db: Session = Depends(get_db)):
    # Fetch price history data using the existing logic
    data = InvoiceItemController(db).get_price_history(request)
    presigned_url = convert_download_price_history(data)
    return {"download_url": presigned_url}


@router.post("/get_aggregates")
def get_aggregates(request: FilterRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    aggregates = InvoiceItemController(db).get_aggregates(request)
    return aggregates
