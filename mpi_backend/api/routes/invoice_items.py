from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from datetime import datetime
from fastapi_pagination import Page, paginate
from datetime import date
import os
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.database.controllers import InvoiceItemController, InvoiceController
from mpi_backend.database.schemas import InvoiceItems, UpdateInvoiceItemRequest, PaginatedInvoiceItemsResponse, ExportToExcelFilterRequest
from mpi_backend.database.schemas.Filters import OrderByFilter
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.export_utils import convert_items_to_dataframe
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
from mpi_backend.database.schemas.InvoiceItems import ToggleVisibilityRequest
router = APIRouter(prefix="/invoice-items",tags=["Invoice Items"])


@router.get("/all", response_model=Page[InvoiceItems])
def get_invoices(
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer())
):
    try:
        invoice_items = InvoiceItemController(db).get_invoice_items()

        return paginate(invoice_items)

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No Records Found!")


@router.get("/id", response_model=Page[InvoiceItems])
def get_invoices(
        db: Session = Depends(get_db),
        invoice_id: Optional[UUID] = Query(None, description="Filter by invoice_id"),
        token: str = Depends(JWTBearer())
):
    try:
        invoice_items = InvoiceItemController(db).get_invoice_items(invoice_id=invoice_id)
        return paginate(invoice_items)

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No Records Found!")


@router.get("/supplier-date", response_model=PaginatedInvoiceItemsResponse)
def get_invoices(
        db: Session = Depends(get_db),
        supplier_name: List[str] = Query(None),
        from_date: date = Query(None),
        to_date: date = Query(None),
        job_location: str = Query(None),
        export_status: str = Query(None),
        page: int = Query(1, ge=1),
        size: int = Query(10),
        token: str = Depends(JWTBearer())
):
    try:
        invoice_items = InvoiceItemController(db).get_invoice_items_by_filters(supplier=supplier_name,
                                                                               from_date=from_date,
                                                                               to_date=to_date,
                                                                               job_location=job_location,
                                                                               export_status=export_status,
                                                                               page=page, page_size=size)
        return invoice_items

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No Records Found!")


@router.put("/update")
def update_invoice_items(items: List[UpdateInvoiceItemRequest],background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    controller = InvoiceItemController(db)
    controller.update_invoice_items([item.dict() for item in items], background_tasks)
    return {"status": "invoices updated successfully"}


@router.put("/toggle-visibility", status_code=200)
def toggle_visibility(
    request: ToggleVisibilityRequest,
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    controller = InvoiceItemController(db)
    updated_count = controller.toggle_visibility(request.ids, request.make_visible)
    return {"status": f"Updated visibility for {updated_count} items"}


@router.get("/hidden-items", response_model=Page[InvoiceItems])
def get_hidden_items(
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    controller = InvoiceItemController(db)
    return paginate(controller.get_hidden_items())

@router.get("/count")
def count_invoice_items(db: Session = Depends(get_db), token: str = Depends(JWTBearer())):
    no_of_line_items = InvoiceItemController(db).count_line_items()
    return {"count": no_of_line_items}

@router.get("/sort", response_model=Page[InvoiceItems])
def sort_invoices( db: Session = Depends(get_db), column_name:str = Query(None),
                   sort_order:str = Query('ascending',description="Sort By (ascending, descending)")):
    column_mapping = {
        "File Name": "filename",
        "Sheet Name": "sheet_name",
        "Item": "item",
        "Description": "description",
        "Quantity": "qty",
        "Cost": "cost",
        "Amount": "amount",
        "Date": "date",
        "Ref No": "ref_no",
        "PO #": "po_number",
        "Customer Job": "customer_job",
        "Bill": "bill",
        "Vendor": "vendor",
        "Class": "class_",
        "Memo": "memo",
        "Buyer": "buyer",
        "Date Added": "date_added",
        "Original Item": "mpi_item", # will be removed adding beacuse of incorect naming on frontend
        "Original Description": "mpi_description", # will be removed adding beacuse of incorect naming on frontend
        "Date Added": "date_added",
        "MPI Item": "mpi_item",
        "MPI Description": "mpi_description",
    }

    if column_name not in column_mapping:
        raise HTTPException(status_code=400, detail="Invalid column name")

    column = column_mapping.get(column_name, 'date')

    invoice_items = InvoiceItemController(db).sort(db,column, sort_order)
    return paginate(invoice_items)

@router.post("/export")
def export_invoices(
        ids: List[int],
        columns: Optional[List[str]] = None,
        order_by: Optional[List[OrderByFilter]] = None,
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer()),
):
    """
    Export invoice items to Excel with automatic performance optimization.
    Automatically chooses the best export method based on data size and configuration.
    """
    try:
        from mpi_backend.config import (
            EXPORT_MAX_RECORDS_BEFORE_BATCH, 
            EXPORT_USE_OPTIMIZED,
            EXPORT_BATCH_SIZE
        )
        import time
        
        start_time = time.time()
        record_count = len(ids)
        
        # Handle column name mapping
        if columns:
            columns = [col.replace('class_', 'Class') for col in columns]
        
        # Choose export method based on record count and configuration
        if EXPORT_USE_OPTIMIZED and record_count > 100:
            print(f"Using optimized export for {record_count} records")
            
            if record_count > EXPORT_MAX_RECORDS_BEFORE_BATCH:
                # Use batch processing for very large exports
                from mpi_backend.utils.export_utils import convert_items_to_dataframe_batch
                items_df = convert_items_to_dataframe_batch(
                    db_session=db,
                    ids=ids,
                    columns=columns,
                    order_by=order_by,
                    use_suffix=True,
                    batch_size=EXPORT_BATCH_SIZE
                )
                method_used = "batch_optimized"
            else:
                # Use standard optimized method
                from mpi_backend.utils.export_utils import convert_items_to_dataframe_optimized
                items_df = convert_items_to_dataframe_optimized(
                    db_session=db,
                    ids=ids,
                    columns=columns,
                    order_by=order_by,
                    use_suffix=True
                )
                method_used = "optimized"
        else:
            # Use standard method for small exports or when optimization is disabled
            print(f"Using standard export for {record_count} records")
            controller = InvoiceItemController(db)
            items = controller.get_invoice_items_by_ids(ids, order_by=order_by)
            items_df = convert_items_to_dataframe(items)
            method_used = "standard"
        
        if items_df.empty:
            raise HTTPException(status_code=404, detail="No data found for export")
        
        # Handle column selection
        if columns and not items_df.empty:
            available_columns = [col for col in columns if col in items_df.columns]
            if available_columns:
                items_df = items_df[available_columns]
        else:
            # Default columns
            default_columns = ["Item","Description","Qty","Cost","Amount","Date","Ref NO","PO #","Customer Job","Bill","Vendor","Class","Memo"]
            available_columns = [col for col in default_columns if col in items_df.columns]
            items_df = items_df[available_columns]
        
        # Prepare file paths
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
        filename = f'{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.xlsx'
        file_path = f'{upload_folder}{filename}'
        
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        # Choose Excel export method based on optimization level
        if method_used in ["optimized", "batch_optimized"]:
            from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data_fast
            save_final_data_fast(items_df, file_path)
        else:
            save_final_data(final_df=items_df, supplier='', output_path=file_path)
        
        processing_time = time.time() - start_time
        print(f"Export completed using {method_used} method in {processing_time:.2f} seconds for {len(items_df)} items")
        
        # Upload to S3 and get download URL
        upload_file(file_path, file_key=f'Exports/{filename}', is_invoice=False)
        download_url = get_presigned_url(file_key=f'Exports/{filename}', is_invoice=False)
        
        return download_url
        
    except Exception as e:
        print(f"Export error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.post("/export-all")
def export_all_invoices(request: ExportToExcelFilterRequest,
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer()),
):
    """
    Export all filtered invoice items to Excel with automatic performance optimization.
    Automatically chooses the best export method based on data size and configuration.
    """
    try:
        import time
        start_time = time.time()
        
        # Get filtered IDs efficiently
        ids = InvoiceItemController(db).apply_filters(request, page=1, size=0, col_param='id')
        
        if request.excluded_rows_ids:
            ids = list(set(ids) - set(request.excluded_rows_ids))
        
        if not ids:
            raise HTTPException(status_code=404, detail="No items found matching the filters")
        
        filter_time = time.time() - start_time
        print(f"Filter processing took {filter_time:.2f} seconds, found {len(ids)} items")
        
        # Use the optimized export function
        result = export_invoices(
            ids=ids,
            columns=request.columns,
            order_by=request.order_by,
            db=db,
            token=token
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Export-all error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
