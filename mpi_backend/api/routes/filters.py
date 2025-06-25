from fastapi import APIRouter, Depends, HTTPException,Query, Body
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.schemas import FilterRequest, PaginatedInvoiceItemsResponse, PriceHistoryRequest, PriceHistoryResponse
from mpi_backend.database.schemas import InvoiceItems
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.pdf_to_excel.formatting_util import export_price_history_to_excel
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
import os
import logging

router = APIRouter(prefix="/filter",tags=["Filtering Data"])

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


@router.post("/by-column") # for dropdown population
def column_mappings(db: Session = Depends(get_db),
                    token: str = Depends(JWTBearer()),
                    column_name: str = Query(None, description="Name of Column for which data is required"),
                    payload: Optional[Dict] = Body(None, description="Previous selections of filters & their values as json.")):
    if column_name is None:
        return {"data": "Invalid Column Name Specified"}

    if payload: filter_context = payload["filter_context"]
    else: filter_context = None

    if payload: comparison_filters = payload['comparison_filters']
    else: comparison_filters = None

    distinct_values = InvoiceItemController(db).get_data_by_column_name(column_name, filter_context, comparison_filters)
    return distinct_values


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
    controller = InvoiceItemController(db)
    
    # Extract item codes and clean suffixes for database search
    item_id_pairs = []
    invoice_items = []
    
    for invoice_item in filtered_data["items"]:
        # The item from apply_filters has suffix for display
        suffixed_item = invoice_item.item
        # Remove suffix to get original database item code for search
        original_item = controller._remove_suffix_from_item_code(suffixed_item)
        
        item_id_pairs.append((suffixed_item, invoice_item.id))  # Keep suffixed for response
        invoice_items.append(original_item)  # Use original for database search
    
    price_increase = controller.calculate_price_increase(item_numbers=invoice_items)

    result = []
    for i, (item, percentage) in enumerate(price_increase):
        suffixed_item, item_id = item_id_pairs[i]
        result.append({
            "item": suffixed_item,  # Return suffixed item for UI consistency
            "id": item_id,
            "percentage_increase": percentage
        })
    return result


@router.post("/price-history",response_model=List[PriceHistoryResponse])
def get_price_history(request: PriceHistoryRequest, db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    """
    Get price history for a specific item and vendor.
    
    Args:
        request: PriceHistoryRequest containing item_number, vendor, and description
        
    Returns:
        List[PriceHistoryResponse]: List of price history records sorted by date
        
    Raises:
        HTTPException: If validation fails or no data found
    """
    try:
        # Validate input parameters
        if not request.item_number or not request.item_number.strip():
            raise HTTPException(
                status_code=400,
                detail="item_number is required and cannot be empty"
            )
        
        if not request.vendor or not request.vendor.strip():
            raise HTTPException(
                status_code=400,
                detail="vendor is required and cannot be empty"
            )
        
        logger.info(f"Price history request - Item: {request.item_number}, Vendor: {request.vendor}")
        
        # Get price history from controller
        price_history = InvoiceItemController(db).get_price_history(request)
        
        # Log result for debugging
        logger.info(f"Price history response - Found {len(price_history)} records")
        
        if not price_history:
            logger.warning(f"No price history found for item: {request.item_number}, vendor: {request.vendor}")
            # Return empty list instead of 404 to allow frontend to handle gracefully
            return []
        
        return price_history
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error in price history endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve price history: {str(e)}"
        )

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

