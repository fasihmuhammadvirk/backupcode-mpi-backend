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
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.export_utils import convert_items_to_dataframe
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url

router = APIRouter(prefix="/invoice-items")


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

@router.post("/export-all")
def export_all_invoices(request: ExportToExcelFilterRequest,
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer()),
):
    filtered_data = InvoiceItemController(db).apply_filters(request, page=1, size=0)
    ids = [item.id for item in filtered_data['items']]

    if request.excluded_rows_ids:  # un selected items from frontend
        ids = [record_id for record_id in ids if record_id not in request.excluded_rows_ids]

    ids = list(set(ids))  # make row ids of items to be exported in list to be unique, no repetition.
    return export_invoices (ids,request.columns,db=db)

@router.post("/export")
def export_invoices(
        ids: List[int],
        columns: Optional[List[str]] = None,
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer()),
):
    columns = [col.replace('class_', 'Class') for col in columns]  # fix to handle column mismatch

    items = InvoiceItemController(db).get_invoice_items_by_ids(ids)
    items_df = convert_items_to_dataframe(items)

    upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
    filename = f'{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.xlsx'
    file_path = f'{upload_folder}{filename}'
    if not os.path.exists(upload_folder):os.makedirs(upload_folder)

    if columns: items_df = items_df[columns]  # only export certain columns
    else:
        columns = ["Item","Description","Qty","Cost","Amount","Date","Ref NO","PO #","Customer Job","Bill","Vendor",
                    "Class","Memo"]
        items_df = items_df[columns]

    save_final_data(final_df=items_df,supplier='', output_path=file_path) # convert to excel

    upload_file(file_path, file_key=f'Exports/{filename}', is_invoice=False) # upload to s3 to be exported
    download_url = get_presigned_url(file_key=f'Exports/{filename}', is_invoice=False)

    # track & manage invoice export status
    InvoiceItemController(db).set_export_status_to_sent(ids) # update line item export status to sent
    invoice_ids = {item.invoice_id for item in items if item.invoice_id} # get all distinct invoice-ids to check & update invoice level export status
    for invoice_id in invoice_ids:
        if InvoiceItemController(db).is_exported(invoice_id):
            InvoiceController(db).set_invoice_is_exported(invoice_id)

    return download_url
