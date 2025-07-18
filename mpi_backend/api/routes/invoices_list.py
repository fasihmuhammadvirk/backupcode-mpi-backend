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
import logging
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.database.controllers.Invoice import InvoiceController
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_convertor import convert_single_invoice
from mpi_backend.database.schemas import Invoice, PaginatedInvoiceResponse
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.s3_utils import get_presigned_url, upload_file

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
    logger.info(f"GET /invoice - Fetching invoices with filters: supplier_id={supplier_id}, status={status}, page={page}, size={size}")
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
        # Safely log the number of invoices
        try:
            if isinstance(invoices, dict) and 'items' in invoices:
                invoice_count = len(invoices['items'])
            elif hasattr(invoices, 'items') and not callable(invoices.items):
                invoice_count = len(invoices.items)
            elif hasattr(invoices, '__len__'):
                invoice_count = len(invoices)
            else:
                invoice_count = 'unknown'
            logger.info(f"GET /invoice - Successfully fetched {invoice_count} invoices")
        except Exception as log_error:
            logger.info(f"GET /invoice - Successfully fetched invoices (count unavailable: {str(log_error)})")
        return invoices

    except Exception as e:
        logger.error(f"GET /invoice - Error fetching invoices: {str(e)}")
        raise HTTPException(status_code=404, detail="No Records Found!")


@router.get("/all")
def get_all_invoices(
    db: Session = Depends(get_db), 
    token: str = Depends(JWTBearer())
):
    logger.info("GET /invoice/all - Fetching all invoices")
    try:
        invoices = InvoiceController(db).get_all_invoices(db=db)
        # Safely log the number of invoices
        try:
            if invoices is not None:
                invoice_count = len(invoices)
            else:
                invoice_count = 0
            logger.info(f"GET /invoice/all - Successfully fetched {invoice_count} invoices")
        except Exception as log_error:
            logger.info(f"GET /invoice/all - Successfully fetched invoices (count unavailable: {str(log_error)})")
        return invoices
    except Exception as e:
        logger.error(f'GET /invoice/all - Error occurred while fetching all invoices: {e}')
        raise HTTPException(
            status_code=500, 
            detail="An Error occurred while fetching invoices."
        )


@router.get("/download")
def download_invoice(
    db: Session = Depends(get_db), 
    invoice_id: str = Query(None)
):
    logger.info(f"GET /invoice/download - Downloading invoice: {invoice_id}")
    try:
        invoice = InvoiceController(db).get_invoice_by_invoiceID(
            invoice_id, db
        )
        supplier_name = SupplierController(db).get_supplier_by_id(
            invoice.supplier_id
        )
        url = get_presigned_url(file_key=f'{supplier_name}/{invoice_id}')
        logger.info(f"GET /invoice/download - Successfully generated download URL for invoice: {invoice_id}")
        return {"link": url}
    except Exception as e:
        logger.error(f"GET /invoice/download - Error downloading invoice {invoice_id}: {str(e)}")
        raise HTTPException(
            status_code=404, 
            detail="Couldn't fetch requested file"
        )


@router.post("/upload")
async def upload_and_process_invoice(
    supplier_id: int, 
    file: UploadFile = File(...), 
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """Upload and process invoice synchronously"""
    logger.info(f"POST /invoice/upload - Uploading invoice for supplier_id: {supplier_id}, filename: {file.filename}")
    try:
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            logger.warning(f"POST /invoice/upload - Invalid file type: {file.filename}")
            raise HTTPException(
                status_code=400, 
                detail="Only PDF files are allowed."
            )

        # Get supplier info
        supplier = SupplierController(db).get_supplier_by_id(supplier_id)
        if not supplier:
            logger.error(f"POST /invoice/upload - Supplier not found: {supplier_id}")
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
            logger.error(f"POST /invoice/upload - Failed to convert invoice: {failed_files}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to convert invoice: {failed_files}"
            )

        # Process extracted data
        process_extracted_data(converted_files, failed_files)

        # Get the created invoice for S3 upload
        from mpi_backend.database.models.Invoice import Invoice
        created_invoice = db.query(Invoice).filter_by(
            filename=file.filename, 
            supplier_id=supplier_id
        ).order_by(Invoice.id.desc()).first()
        
        if not created_invoice:
            logger.error(f"POST /invoice/upload - Failed to retrieve created invoice record for: {file.filename}")
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

        logger.info(f"POST /invoice/upload - Successfully uploaded and processed invoice: {file.filename}")
        return {
            "status": "success",
            "message": f"Invoice '{file.filename}' uploaded and processed successfully.",
            "filename": file.filename,
            "supplier": supplier
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /invoice/upload - Error in upload endpoint: {str(e)}")
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
    logger.info(f"POST /invoice/process - Reprocessing invoice: {invoice_id}")
    try:
        # Get invoice and supplier info
        invoice = InvoiceController(db).get_invoice_by_invoiceID(
            invoice_id, db
        )
        if not invoice:
            logger.error(f"POST /invoice/process - Invoice not found: {invoice_id}")
            raise HTTPException(
                status_code=404, 
                detail=f"Invoice with ID {invoice_id} not found"
            )

        supplier = SupplierController(db).get_supplier_by_id(
            invoice.supplier_id
        )
        if not supplier:
            logger.error(f"POST /invoice/process - Supplier for invoice {invoice_id} not found: {invoice.supplier_id}")
            raise HTTPException(
                status_code=404, 
                detail=f"Supplier for invoice {invoice_id} not found"
            )

        # Download invoice from S3
        invoice_url = get_presigned_url(file_key=f'{supplier}/{invoice_id}')
        if not invoice_url:
            logger.error(f"POST /invoice/process - Couldn't fetch requested Invoice URL for: {invoice_id}")
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
            logger.error(f"POST /invoice/process - Failed to download invoice from URL: {invoice_url}, status: {response.status_code}, detail: {response.text}")
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
            logger.error(f"POST /invoice/process - Failed to convert invoice: {failed_files}")
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

        logger.info(f"POST /invoice/process - Successfully reprocessed invoice: {invoice.filename}")
        return {
            "status": f"Success Invoice '{invoice.filename}' reprocessed successfully.",
            "invoice_id": invoice_id,
            "filename": invoice.filename
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /invoice/process - Error in reprocess endpoint: {str(e)}")
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


