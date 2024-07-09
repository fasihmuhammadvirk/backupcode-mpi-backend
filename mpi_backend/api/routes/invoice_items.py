from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from datetime import datetime
from fastapi_pagination import Page, paginate
from datetime import date
import os
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.database.controllers import InvoiceItemController
from mpi_backend.database.schemas import InvoiceItems, UpdateInvoiceItemRequest
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.export_utils import convert_items_to_dataframe
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data
from mpi_backend.utils.s3_utils import upload_file,get_presigned_url

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


@router.get("/supplier-date", response_model=Page[InvoiceItems])
def get_invoices(
        db: Session = Depends(get_db),
        supplier_name: str = Query(None),
        from_date: date = Query(None),
        to_date: date = Query(None),
        token: str = Depends(JWTBearer())
):
    try:
        invoice_items = InvoiceItemController(db).get_invoice_items_by_filters(supplier=supplier_name,
                                                                    from_date=from_date,
                                                                    to_date=to_date, )
        return paginate(invoice_items)

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No Records Found!")


@router.put("/update")
def update_invoice_items(items: List[UpdateInvoiceItemRequest], db: Session = Depends(get_db)):
    controller = InvoiceItemController(db)
    controller.update_invoice_items([item.dict() for item in items])
    return {"status": "invoices updated successfully"}


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
    }

    if column_name not in column_mapping:
        raise HTTPException(status_code=400, detail="Invalid column name")

    column = column_mapping.get(column_name, 'date')

    invoice_items = InvoiceItemController(db).sort(db,column, sort_order)
    return paginate(invoice_items)


@router.post("/export",)
def get_invoices(
        ids: List[int],
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer()),
):
    items = InvoiceItemController(db).get_invoice_items_by_ids(ids)
    items_df = convert_items_to_dataframe(items)

    upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports'
    filename = f'{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.xlsx'
    if not os.path.exists(upload_folder):os.makedirs(upload_folder)

    save_final_data(final_df=items_df,supplier='', output_path=filename) # convert to excel
    upload_file(filename, file_key=f'Exports/{filename}', is_invoice=False) # upload to s3 to be exported
    download_url = get_presigned_url(file_key=f'Exports/{filename}', is_invoice=False)

    return download_url
