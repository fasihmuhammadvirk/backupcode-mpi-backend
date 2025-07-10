from fastapi import (
    APIRouter, Depends, HTTPException, Query, UploadFile, File
)
from typing import List, Optional
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from fastapi_pagination import Page, paginate
from datetime import date
import os
import requests
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.database.controllers.invoice import InvoiceController
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_convertor import convert_single_invoice
from mpi_backend.database.schemas import Invoice, PaginatedInvoiceResponse
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.s3_utils import get_presigned_url, upload_file
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoice", tags=["Invoices"])


@router.get("", response_model=PaginatedInvoiceResponse)
def get_invoices(
        db: Session = Depends(get_db),
        supplier_id: Optional[List[int]] = Query(None),
        from_date: date = Query(None),
        to_date: date = Query(None),
        status: str = Query(
            'all', 
            description="Status (all, processed, unprocessed)"
        ),
        job_location: str = Query(None),
        export_status: str = Query(None),
        page: int = Query(1, ge=1),
        size: int = Query(10, ge=1, le=100),
        token: str = Depends(JWTBearer())
):
    try:
        invoices = InvoiceController(db).get_invoices(
            db=db,
            supplier_ids=supplier_id,
            from_date=from_date,
            to_date=to_date,
            status=status,
            job_location=job_location,
            export_status=export_status,
            page=page, page_size=size
        )

        return invoices

    except Exception:
        raise HTTPException(status_code=404, detail="No Records Found!")


@router.get("/all")
def get_all_invoices(
    db: Session = Depends(get_db), 
    token: str = Depends(JWTBearer())
):
    try:
        invoices = InvoiceController(db).get_all_invoices(db=db)
        return invoices
    except Exception as e:
        logger.error(f'Error occurred while fetching all invoices -> {e}')
        raise HTTPException(
            status_code=500, 
            detail="An Error occurred while fetching invoices."
        )


@router.get("/download")
def download_invoice(
    db: Session = Depends(get_db), 
    invoice_id: str = Query(None)
):
    try:
        invoice = InvoiceController(db).get_invoice_by_invoiceID(
            invoice_id, db
        )
        supplier_name = SupplierController(db).get_supplier_by_id(
            invoice.supplier_id
        )
        url = get_presigned_url(file_key=f'{supplier_name}/{invoice_id}')
    except Exception:
        raise HTTPException(
            status_code=404, 
            detail="Couldn't fetch requested file"
        )

    return {"link": url}


@router.post("/upload")
async def upload_and_process_invoice(
    supplier_id: int, 
    file: UploadFile = File(...), 
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """Upload and process invoice synchronously"""
    try:
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=400, 
                detail="Only PDF files are allowed."
            )

        # Get supplier info
        supplier = SupplierController(db).get_supplier_by_id(supplier_id)
        if not supplier:
            raise HTTPException(
                status_code=404, 
                detail=f"Supplier with ID {supplier_id} not found"
            )

        # Create upload directory
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{supplier}'
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        # Save uploaded file
        file_path = os.path.join(upload_folder, file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        # Convert and process the invoice
        converted_files, failed_files = convert_single_invoice(
            file_path, supplier
        )
        if failed_files:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to convert invoice: {failed_files}"
            )

        # Process extracted data
        process_extracted_data(converted_files, failed_files)

        # Get the created invoice for S3 upload
        from mpi_backend.database.models.invoice import Invoice
        created_invoice = db.query(Invoice).filter_by(
            filename=file.filename, 
            supplier_id=supplier_id
        ).order_by(Invoice.id.desc()).first()
        
        if not created_invoice:
            raise HTTPException(
                status_code=500, 
                detail="Failed to retrieve created invoice record"
            )

        # Upload to S3
        s3_key = f'{supplier}/{created_invoice.id}'
        upload_file(file_name=file_path, file_key=s3_key)

        # Clean up files after processing
        for filename in os.listdir(upload_folder):
            os.remove(os.path.join(upload_folder, filename))

        return {
            "status": "success",
            "message": f"Invoice '{file.filename}' uploaded and processed successfully.",
            "filename": file.filename,
            "supplier": supplier
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in upload endpoint: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Upload failed: {str(e)}"
        )


@router.post("/process")
async def process_again(
    invoice_id: str, 
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """Reprocess invoice synchronously"""
    try:
        # Get invoice and supplier info
        invoice = InvoiceController(db).get_invoice_by_invoiceID(
            invoice_id, db
        )
        if not invoice:
            raise HTTPException(
                status_code=404, 
                detail=f"Invoice with ID {invoice_id} not found"
            )

        supplier = SupplierController(db).get_supplier_by_id(
            invoice.supplier_id
        )
        if not supplier:
            raise HTTPException(
                status_code=404, 
                detail=f"Supplier for invoice {invoice_id} not found"
            )

        # Download invoice from S3
        invoice_url = get_presigned_url(file_key=f'{supplier}/{invoice_id}')
        if not invoice_url:
            raise HTTPException(
                status_code=404, 
                detail="Couldn't fetch requested Invoice"
            )

        # Create upload directory
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{supplier}'
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        # Download file
        response = requests.get(invoice_url)
        if response.status_code == 200:
            file_path = os.path.join(upload_folder, invoice.filename)
            with open(file_path, 'wb') as file:
                file.write(response.content)
        else:
            raise HTTPException(
                status_code=response.status_code, 
                detail=response.text
            )

        # Delete existing invoice data
        InvoiceItemController(db).delete_invoice_items(invoice_id, db)
        InvoiceController(db).delete_invoice(invoice_id, db)

        # Convert and process the invoice
        converted_files, failed_files = convert_single_invoice(
            file_path, supplier
        )
        if failed_files:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to convert invoice: {failed_files}"
            )

        # Process extracted data with existing invoice ID
        process_extracted_data(
            converted_files, failed_files, existing_invoice_id=invoice_id
        )

        # Clean up files after processing
        for filename in os.listdir(upload_folder):
            os.remove(os.path.join(upload_folder, filename))

        return {
            "status": f"Success Invoice '{invoice.filename}' reprocessed successfully.",
            "invoice_id": invoice_id,
            "filename": invoice.filename
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in reprocess endpoint: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Reprocessing failed: {str(e)}"
        )


@router.get("/sort", response_model=Page[Invoice])
def sort_invoices(
    db: Session = Depends(get_db), 
    column_name: str = Query(None),
    sort_order: str = Query(
        'ascending', 
        description="Sort By (ascending, descending)"
    )
):
    column_mapping = {
        "Date": "date",
        "File Name": "filename",
        "Status": "status",
        "Job Address": "customer_job",
        "Invoice": "ref_no"
    }

    if column_name not in column_mapping and column_name != 'Supplier':
        raise HTTPException(
            status_code=400, 
            detail="Invalid column name"
        )

    column = column_mapping.get(column_name, 'date')

    invoices = InvoiceController(db).sort(db, column, sort_order)
    return paginate(invoices)


@router.delete("/delete")
async def delete_invoice(
    invoice_id: str, 
    db: Session = Depends(get_db), 
    token: str = Depends(JWTBearer())
):
    # Delete from database
    invoice_controller = InvoiceController(db)
    invoice_id = invoice_controller.delete_invoice(invoice_id, db)

    return {
        "status": f"Invoice {invoice_id} and associated file deleted successfully."
    }


