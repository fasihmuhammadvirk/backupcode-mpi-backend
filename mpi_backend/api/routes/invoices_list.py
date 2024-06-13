from fastapi import APIRouter, Depends, HTTPException, Query,UploadFile, File
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from datetime import datetime
from fastapi_pagination import Page, paginate
from datetime import date
import os
import logging
logger = logging.getLogger(__name__)
import requests
from mpi_backend.database.controllers import SupplierController, InvoiceController, InvoiceItemController
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_convertor import convert_invoice
from mpi_backend.database.schemas import Invoice
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.s3_utils import get_presigned_url

router = APIRouter(prefix="/invoice")


@router.get("", response_model=Page[Invoice])
def get_invoices(
        db: Session = Depends(get_db),
        supplier_id: int = Query(None),
        from_date: date = Query(None),
        to_date: date = Query(None),
        status: str = Query('all', description="Status (all, processed, unprocessed)"),
        page: int = Query(1),
        size: int = Query(10),
        token: str = Depends(JWTBearer())
):
    try:
        invoices = InvoiceController(db).get_invoices(
            db=db,
            supplier_id=supplier_id,
            from_date=from_date,
            to_date=to_date,
            status=status,
        )

        return paginate(invoices)

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No Records Found!")


@router.get("/all")
def get_invoices(db: Session = Depends(get_db),token: str = Depends(JWTBearer())):
    try:
        invoices = InvoiceController(db).get_all_invoices(db=db)

        return invoices
    except Exception as e:
        logger.error(f'Error occured while fetching all invoices -> {e}')
        raise HTTPException(status_code=500, detail=f"An Error occured while fetching invoices.")


@router.get("/download")
def download_invoice( db: Session = Depends(get_db), invoice_id:str = Query(None)):
    try:
        matched_invoice = InvoiceController(db).get_invoice_by_invoiceID(invoice_id,db)
        supplier_name = SupplierController(db).get_supplier_by_id(matched_invoice.supplier_id)
        url = get_presigned_url(file_key=f'{supplier_name}/{invoice_id}')
    except Exception as e:
        raise HTTPException(status_code=404, detail="Couldn't fetch requested file") # Handle 'No Key Error' on Client Side

    return { "link": url}


@router.post("/upload")
async def upload_and_process_invoice(supplier_id : int, file: UploadFile = File(...), db: Session = Depends(get_db),
                                     token: str = Depends(JWTBearer())):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    supplier= SupplierController(db).get_supplier_by_id(supplier_id)

    upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{supplier}' # every supplier will have it own folder at root of storage dir
    if not os.path.exists(upload_folder): os.makedirs(upload_folder)

    with open(os.path.join(upload_folder, file.filename), "wb") as buffer:
        buffer.write(await file.read())

    converted_files, failed_files = convert_invoice(supplier)
    process_extracted_data(converted_files, failed_files)

    [os.remove(os.path.join(upload_folder, filename)) for filename in os.listdir(upload_folder)] # delete files after it's processed

    return {"status": "Uploaded Invoice processed successfully."}


@router.post("/process")
async def process_again(invoice_id : str, db: Session = Depends(get_db),
                                    token: str = Depends(JWTBearer())):

    invoice = InvoiceController(db).get_invoice_by_invoiceID(invoice_id,db)
    supplier= SupplierController(db).get_supplier_by_id(invoice.supplier_id)
    invoice_url = get_presigned_url(file_key=f'{supplier}/{invoice_id}')

    upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{supplier}' # every supplier will have it own folder at root of storage dir
    if not os.path.exists(upload_folder): os.makedirs(upload_folder)

    if not invoice_url:
        raise HTTPException(status_code=404, detail="Couldn't fetch requested Invoice")

    response = requests.get(invoice_url)
    if response.status_code == 200:
        with open(os.path.join(upload_folder, invoice.filename), 'wb') as file:
            file.write(response.content)
    else:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    InvoiceItemController(db).delete_invoice_items(invoice_id,db) # delete previous ingested invoice items
    InvoiceController(db).delete_invoice(invoice_id,db)

    converted_files, failed_files = convert_invoice(supplier)
    process_extracted_data(converted_files, failed_files)

    [os.remove(os.path.join(upload_folder, filename)) for filename in os.listdir(upload_folder)] # delete files after it's processed
    return {"status": "Invoice reprocessing successful."}


@router.get("/sort", response_model=Page[Invoice])
def sort_invoices( db: Session = Depends(get_db), column_name:str = Query(None),
                   sort_order:str = Query('ascending',description="Sort By (ascending, descending)")):

    column_mapping= {"Date":"date",
                     "File Name":"filename",
                     "Status":"status"}

    if column_name not in column_mapping and column_name != 'Supplier':
        raise HTTPException(status_code=400, detail="Invalid column name")

    column = column_mapping.get(column_name, 'date')

    invoices = InvoiceController(db).sort(db,column, sort_order)
    return paginate(invoices)
