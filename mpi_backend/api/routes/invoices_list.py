from fastapi import (
    APIRouter, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks
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
from mpi_backend.database.schemas import Invoice, PaginatedInvoiceResponse
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.s3_utils import get_presigned_url
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


def process_invoice_background_task(file_path: str, supplier: str, original_filename: str):
    """Background task to process uploaded invoice"""
    try:
        logger.info(f"Starting background processing for {original_filename}")
        
        # Import the single file converter
        from mpi_backend.utils.invoice_convertor import convert_single_invoice
        
        # Convert the single uploaded invoice
        converted_files, failed_files = convert_single_invoice(file_path, supplier)
        logger.info(f"Conversion completed. Success: {len(converted_files)}, Failed: {len(failed_files)}")
        
        # Process extracted data
        process_extracted_data(converted_files, failed_files)
        logger.info(f"Data processing completed for {original_filename}")
        
        # Clean up uploaded file
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{supplier}'
        if os.path.exists(upload_folder):
            for filename in os.listdir(upload_folder):
                file_to_remove = os.path.join(upload_folder, filename)
                try:
                    os.remove(file_to_remove)
                    logger.debug(f"Cleaned up file: {file_to_remove}")
                except OSError as e:
                    logger.warning(f"Could not remove file {file_to_remove}: {e}")
        
        logger.info(f"Background processing completed successfully for {original_filename}")
        
    except Exception as e:
        logger.error(f"Background processing failed for {original_filename}: {str(e)}")
        # Don't raise here as this is a background task


@router.post("/upload")
async def upload_and_process_invoice(
    supplier_id: int, 
    file: UploadFile = File(...), 
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """Upload and process invoice synchronously. Only return success if file is uploaded to S3 and all DB records are saved."""
    temp_file_path = None
    try:
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

        # Get supplier info
        supplier = SupplierController(db).get_supplier_by_id(supplier_id)
        if not supplier:
            raise HTTPException(status_code=404, detail=f"Supplier with ID {supplier_id} not found")

        # Create upload directory
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{supplier}'
        os.makedirs(upload_folder, exist_ok=True)

        # Save uploaded file with size limit
        file_path = os.path.join(upload_folder, file.filename)
        max_file_size = 50 * 1024 * 1024  # 50MB
        file_content = await file.read()
        if len(file_content) > max_file_size:
            raise HTTPException(status_code=413, detail="File too large. Maximum size is 50MB.")
        with open(file_path, "wb") as buffer:
            buffer.write(file_content)

        # Convert the single uploaded invoice
        from mpi_backend.utils.invoice_convertor import convert_single_invoice
        converted_files, failed_files = convert_single_invoice(file_path, supplier)
        if failed_files:
            raise HTTPException(status_code=500, detail=f"Failed to convert invoice: {failed_files}")

        # Process extracted data (synchronously)
        from mpi_backend.utils.extracted_data_processor import process_extracted_data
        try:
            process_extracted_data(converted_files, failed_files)
        except Exception as e:
            # Clean up DB and file if processing fails
            logger.error(f"Error processing extracted data: {str(e)}")
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=500, detail=f"Failed to process invoice: {str(e)}")

        # Get the invoice ID from the processed data for S3 upload
        # We need to query the database to get the invoice ID that was just created
        try:
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
            invoice_id = created_invoice.id
        except Exception as e:
            logger.error(f"Error retrieving created invoice: {str(e)}")
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to retrieve invoice record: {str(e)}"
            )

        # Upload to S3 using invoice_id as key (consistent with reprocess)
        from mpi_backend.utils.s3_utils import upload_file
        s3_key = f'{supplier}/{invoice_id}'
        try:
            upload_file(file_name=file_path, file_key=s3_key)
        except Exception as e:
            logger.error(f"Error uploading file to S3: {str(e)}")
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=500, detail=f"Failed to upload file to S3: {str(e)}")

        # Clean up local file after S3 upload
        if os.path.exists(file_path):
            os.remove(file_path)

        return {
            "status": "success",
            "message": f"Invoice '{file.filename}' uploaded, processed, and saved successfully.",
            "filename": file.filename,
            "supplier": supplier,
            "s3_key": s3_key
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in upload endpoint: {str(e)}")
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


def reprocess_invoice_background_task(invoice_id: str, invoice_filename: str, supplier: str):
    """Background task to reprocess invoice with improved session handling"""
    temp_file_path = None
    db = None
    try:
        logger.info(f"Starting background reprocessing for invoice {invoice_id}")

        # Get fresh database session for background task
        from mpi_backend.database import get_db
        db_gen = get_db()
        db = next(db_gen)

        try:
            # Download invoice from S3 with timeout
            invoice_url = get_presigned_url(file_key=f'{supplier}/{invoice_id}')

            if not invoice_url:
                logger.error(f"Could not get presigned URL for invoice {invoice_id}")
                return

            # Create temporary directory for processing
            upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{supplier}'
            os.makedirs(upload_folder, exist_ok=True)
            temp_file_path = os.path.normpath(os.path.join(upload_folder, invoice_filename))

            # Download with timeout
            try:
                response = requests.get(invoice_url, timeout=30)  # 30 second timeout
                response.raise_for_status()

                with open(temp_file_path, 'wb') as file:
                    file.write(response.content)

                logger.info(f"Downloaded invoice {invoice_id} from S3 ({len(response.content)} bytes)")

            except requests.RequestException as e:
                logger.error(f"Error downloading invoice {invoice_id} from S3: {str(e)}")
                return

            # Delete existing invoice data
            try:
                InvoiceItemController(db).delete_invoice_items(invoice_id, db)
                InvoiceController(db).delete_invoice(invoice_id, db)
                logger.info(f"Deleted existing data for invoice {invoice_id}")
            except Exception as e:
                logger.error(f"Error deleting existing invoice data {invoice_id}: {str(e)}")
                return

            # Import the single file converter
            from mpi_backend.utils.invoice_convertor import convert_single_invoice

            # Process the single invoice
            converted_files, failed_files = convert_single_invoice(temp_file_path, supplier)
            logger.info(f"Reprocessing conversion completed. Success: {len(converted_files)}, Failed: {len(failed_files)}")

            # Process extracted data with the same session, preserving invoice ID
            from mpi_backend.utils.extracted_data_processor import process_extracted_data
            try:
                process_extracted_data(converted_files, failed_files, existing_invoice_id=invoice_id)
                logger.info(f"Reprocessing data processing completed for invoice {invoice_id}")
            except Exception as e:
                logger.error(f"Error in process_extracted_data for invoice {invoice_id}: {str(e)}")
                # Clean up and re-raise
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except OSError:
                        pass
                raise

            # Clean up temporary files
            if os.path.exists(upload_folder):
                for filename in os.listdir(upload_folder):
                    file_to_remove = os.path.join(upload_folder, filename)
                    try:
                        os.remove(file_to_remove)
                        logger.debug(f"Cleaned up file: {file_to_remove}")
                    except OSError as e:
                        logger.warning(f"Could not remove file {file_to_remove}: {e}")

            logger.info(f"Background reprocessing completed successfully for invoice {invoice_id}")

        except Exception as e:
            logger.error(f"Error during reprocessing for invoice {invoice_id}: {str(e)}")
            # Rollback any database changes
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            raise

        finally:
            # Close database session
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"Background reprocessing failed for invoice {invoice_id}: {str(e)}")
        # Clean up temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass


@router.post("/process")
async def process_again(
    invoice_id: str, 
    background_tasks: BackgroundTasks,
    sync: bool = Query(False, description="Process synchronously for immediate feedback"),
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """Reprocess invoice with background or synchronous processing"""
    
    try:
        # Validate invoice exists
        try:
            invoice = InvoiceController(db).get_invoice_by_invoiceID(invoice_id, db)
            if not invoice:
                raise HTTPException(status_code=404, detail=f"Invoice with ID {invoice_id} not found")
        except Exception as e:
            logger.error(f"Error fetching invoice {invoice_id}: {str(e)}")
            raise HTTPException(status_code=500, detail="Error fetching invoice information")

        # Get supplier info
        try:
            supplier = SupplierController(db).get_supplier_by_id(invoice.supplier_id)
            if not supplier:
                raise HTTPException(status_code=404, detail=f"Supplier for invoice {invoice_id} not found")
        except Exception as e:
            logger.error(f"Error fetching supplier for invoice {invoice_id}: {str(e)}")
            raise HTTPException(status_code=500, detail="Error fetching supplier information")

        if sync:
            # Synchronous processing for immediate feedback
            temp_file_path = None
            try:
                logger.info(f"Starting synchronous reprocessing for invoice {invoice_id}")

                # Download invoice from S3
                invoice_url = get_presigned_url(file_key=f'{supplier}/{invoice_id}')
                if not invoice_url:
                    raise HTTPException(status_code=500, detail="Could not get download URL for invoice")

                # Create temporary directory for processing
                upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{supplier}'
                os.makedirs(upload_folder, exist_ok=True)
                temp_file_path = os.path.normpath(os.path.join(upload_folder, invoice.filename))

                # Download with timeout
                try:
                    response = requests.get(invoice_url, timeout=30)
                    response.raise_for_status()
                    with open(temp_file_path, 'wb') as file:
                        file.write(response.content)
                    logger.info(f"Downloaded invoice {invoice_id} from S3 ({len(response.content)} bytes)")
                except requests.RequestException as e:
                    raise HTTPException(status_code=500, detail=f"Failed to download invoice: {str(e)}")

                # Delete existing invoice data
                try:
                    InvoiceItemController(db).delete_invoice_items(invoice_id, db)
                    InvoiceController(db).delete_invoice(invoice_id, db)
                    logger.info(f"Deleted existing data for invoice {invoice_id}")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to delete existing data: {str(e)}")

                # Convert and process the invoice
                from mpi_backend.utils.invoice_convertor import convert_single_invoice
                converted_files, failed_files = convert_single_invoice(temp_file_path, supplier)
                if failed_files:
                    raise HTTPException(status_code=500, detail=f"Failed to convert invoice: {failed_files}")

                # Process extracted data with current session, preserving invoice ID
                from mpi_backend.utils.extracted_data_processor import process_extracted_data
                try:
                    process_extracted_data(converted_files, failed_files, existing_invoice_id=invoice_id)
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to process invoice data: {str(e)}")

                # Clean up temporary files
                if os.path.exists(upload_folder):
                    for filename in os.listdir(upload_folder):
                        file_to_remove = os.path.join(upload_folder, filename)
                        try:
                            os.remove(file_to_remove)
                        except OSError as e:
                            logger.warning(f"Could not remove file {file_to_remove}: {e}")

                logger.info(f"Synchronous reprocessing completed successfully for invoice {invoice_id}")
                
                return {
                    "status": "success",
                    "message": f"Invoice '{invoice.filename}' reprocessed successfully",
                    "invoice_id": invoice_id,
                    "filename": invoice.filename,
                    "supplier": supplier,
                    "processing": "synchronous"
                }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Synchronous reprocessing failed for invoice {invoice_id}: {str(e)}")
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except OSError:
                        pass
                raise HTTPException(status_code=500, detail=f"Reprocessing failed: {str(e)}")
        else:
            # Asynchronous background processing (original behavior)
            background_tasks.add_task(
                reprocess_invoice_background_task,
                invoice_id,
                invoice.filename,
                supplier
            )
            
            return {
                "status": "success",
                "message": f"Invoice '{invoice.filename}' queued for reprocessing",
                "invoice_id": invoice_id,
                "filename": invoice.filename,
                "supplier": supplier,
                "processing": "background"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in reprocess endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Reprocessing failed: {str(e)}")


@router.get("/sort", response_model=Page[Invoice])
def sort_invoices( db: Session = Depends(get_db), column_name:str = Query(None),
                   sort_order:str = Query('ascending',description="Sort By (ascending, descending)")):

    column_mapping= {"Date":"date",
                     "File Name":"filename",
                     "Status":"status",
                     "Job Address" : "customer_job",
                     "Invoice" : "ref_no"
                     }


    if column_name not in column_mapping and column_name != 'Supplier':
        raise HTTPException(status_code=400, detail="Invalid column name")

    column = column_mapping.get(column_name, 'date')

    invoices = InvoiceController(db).sort(db,column, sort_order)
    return paginate(invoices)


@router.delete("/delete")
async def delete_invoice(invoice_id: str, db: Session = Depends(get_db), token: str = Depends(JWTBearer())):

    # Delete from database
    invoice_controller = InvoiceController(db)
    invoice_id = invoice_controller.delete_invoice(invoice_id, db)


    return {"status": f"Invoice {invoice_id} and associated file deleted successfully."}


