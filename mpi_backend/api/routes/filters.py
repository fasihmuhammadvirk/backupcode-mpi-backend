from fastapi import APIRouter, Depends, HTTPException,Query, Body
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from mpi_backend.database.controllers import SupplierController, InvoiceItemController
from mpi_backend.database.schemas import FilterRequest, PaginatedInvoiceItemsResponse, PriceHistoryRequest, PriceHistoryResponse
from mpi_backend.database.schemas import InvoiceItems
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.pdf_to_excel.formatting_util import export_price_history_to_excel
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
import os
import logging

router = APIRouter(prefix="/filter")
logger = logging.getLogger(__name__)

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


@router.post("/by-column")  # for dropdown population
def column_mappings(
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer()),
    column_name: str = Query(None, description="Name of Column for which data is required"),
    payload: Optional[Dict] = Body(None, description="Previous selections of filters & their values as json.")
):
    logger.info(f"Received request for column_mappings with column_name: {column_name}, payload: {payload}")

    if column_name is None:
        logger.warning("Invalid Column Name Specified")
        return {"data": "Invalid Column Name Specified"}

    try:
        filter_context = payload["filter_context"] if payload else None
        logger.debug(f"Filter context: {filter_context}")

        invoice_item_controller = InvoiceItemController(db)
        distinct_values = invoice_item_controller.get_data_by_column_name(column_name, filter_context)

        logger.info(f"Fetched distinct values for column '{column_name}': {distinct_values}")

        return distinct_values
    except Exception as e:
        logger.error(f"Error occurred in column_mappings: {str(e)}", exc_info=True)
        return {"error": "Internal Server Error"}


@router.post("",response_model=PaginatedInvoiceItemsResponse)
def filter_data(request: FilterRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer()),
                page: int = Query(1, ge=1),
                size: int = Query(10)):
    filtered_data = InvoiceItemController(db).apply_filters(request, page,size)
    return filtered_data


@router.post("/price-difference")
def get_price_difference(request: FilterRequest, db: Session = Depends(get_db),
                         # token: str = Depends(JWTBearer()),
                page: int = Query(1, ge=1),
                size: int = Query(10)):
    filtered_data = InvoiceItemController(db).apply_filters(request, page,size)
    item_id_pairs = [(invoice_item.item, invoice_item.id) for invoice_item in filtered_data["items"]]
    invoice_items = [invoice_item.item for invoice_item in filtered_data["items"]]
    price_increase = InvoiceItemController(db).calculate_price_increase(item_numbers=invoice_items)

    result = []
    for i, (item, percentage) in enumerate(price_increase):
        _, item_id = item_id_pairs[i]
        result.append({
            "item": item,
            "id": item_id,
            "percentage_increase": percentage
        })
    return result


@router.post("/price-history",response_model=List[PriceHistoryResponse])
def get_price_history(request: PriceHistoryRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    price_history = InvoiceItemController(db).get_price_history(request)
    return price_history

@router.post("/download-price-history")
def get_price_history(request: PriceHistoryRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    price_history = InvoiceItemController(db).get_price_history(request)

    exported_file_path = export_price_history_to_excel(price_history)
    file_name = os.path.basename(exported_file_path)
    upload_file(exported_file_path, file_key=f'Exports/{file_name}', is_invoice=False)  # upload to s3 to be exported
    download_url = get_presigned_url(file_key=f'Exports/{file_name}', is_invoice=False)
    return download_url


@router.post("/get_aggregates")
def get_aggregates(request: FilterRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    aggregates = InvoiceItemController(db).get_aggregates(request)
    return aggregates

