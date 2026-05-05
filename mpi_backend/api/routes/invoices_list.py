from fastapi import (
    APIRouter, Depends, HTTPException, Query, UploadFile, File
)
import asyncio
from concurrent.futures import ThreadPoolExecutor
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
from mpi_backend.utils.invoice_converter import convert_single_invoice
from mpi_backend.database.schemas import Invoice, PaginatedInvoiceResponse
from mpi_backend.database.models.User import User
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.utils.s3_utils import get_presigned_url, get_invoice_pdf_presigned_url, upload_file
from mpi_backend.database.controllers.UserUploadedPdfController import UserUploadedPdfController
import re
import shutil

# Create a dedicated thread pool executor for background tasks
# This runs in a separate thread pool, not blocking the main FastAPI event loop
BACKGROUND_EXECUTOR = ThreadPoolExecutor(
    max_workers=10, 
    thread_name_prefix="invoice_reprocess"
)

def _sanitize_path_component(name: str) -> str:
    """Sanitize user/DB-provided strings for safe filesystem usage on Windows/Linux.
    Replaces reserved characters and path separators with underscores.
    """
    if not name:
        return "unknown"
    # Replace Windows reserved characters and any slashes/backslashes
    name = re.sub(r'[<>:"/\\|?*]+', '_', name)
    # Collapse spaces
    name = re.sub(r"\s+", " ", name).strip()
    # Guard against device names (CON, PRN, AUX, NUL, COM1, LPT1, etc.)
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name):
        name = f"_{name}__"
    return name


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
        current_user: User = Depends(get_current_user)
):
    """
    Get paginated list of invoices with advanced filtering capabilities.
    
    **Summary:**
        Retrieves a paginated list of invoices with support for multiple filter
        criteria including supplier, date range, status, job location, and export
        status. This is the primary endpoint for browsing and searching invoices.
        
    **Query Parameters:**
        - **supplier_id** (`List[int]`, optional): List of supplier IDs to filter by
        - **from_date** (`date`, optional): Start date for filtering (YYYY-MM-DD)
        - **to_date** (`date`, optional): End date for filtering (YYYY-MM-DD)
        - **status** (`str`, default='all'): Invoice status filter:
            - 'all': All invoices
            - 'processed': Only processed invoices
            - 'unprocessed': Only unprocessed invoices
        - **job_location** (`str`, optional): Customer job location filter
        - **export_status** (`str`, optional): Export status filter
        - **page** (`int`, default=1): Page number for pagination (1-based)
        - **size** (`int`, default=10): Number of items per page (1-100)
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **PaginatedInvoiceResponse**: Paginated response containing:
            - **items** (`List[Invoice]`): Array of invoice objects
            - **total** (`int`): Total number of invoices matching filters
            - **page** (`int`): Current page number
            - **size** (`int`): Items per page
            - **pages** (`int`): Total number of pages
            
    **Response Example:**
    ```json
    {
        "items": [
            {
                "id": 123,
                "invoice_id": "INV-2024-001",
                "filename": "invoice_001.pdf",
                "ref_no": "REF-001",
                "date": "2024-01-15",
                "status": "processed",
                "supplier_id": 1,
                "customer_job": "Project Alpha",
                "export_status": "exported"
            }
        ],
        "total": 150,
        "page": 1,
        "size": 10,
        "pages": 15
    }
    ```
    
    **Filter Combinations:**
        - Multiple filters can be combined for precise searching
        - Date range filtering supports both start and end dates
        - Supplier filtering supports multiple supplier IDs
        - Status filtering provides quick access to different invoice states
        
    **Error Codes:**
        - **404**: No records found matching the filter criteria
        
    **Notes:**
        - All date filters use YYYY-MM-DD format
        - Pagination is 1-based (page 1 is the first page)
        - Maximum page size is 100 items
        - Results are ordered by most recent first
        - Empty filters return all invoices (subject to pagination)
    """
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
    current_user: User = Depends(get_current_user)
):
    """
    Get all invoices without pagination or filtering.
    
    **Summary:**
        Retrieves all invoices from the database without any pagination or
        filtering. This endpoint is useful for bulk operations or when all
        invoice data is needed at once.
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **List[Invoice]**: Array of all invoice objects in the database
        
    **Response Example:**
    ```json
    [
        {
            "id": 123,
            "invoice_id": "INV-2024-001",
            "filename": "invoice_001.pdf",
            "ref_no": "REF-001",
            "date": "2024-01-15",
            "status": "processed",
            "supplier_id": 1,
            "customer_job": "Project Alpha"
        },
        {
            "id": 124,
            "invoice_id": "INV-2024-002",
            "filename": "invoice_002.pdf",
            "ref_no": "REF-002",
            "date": "2024-01-16",
            "status": "unprocessed",
            "supplier_id": 2,
            "customer_job": "Project Beta"
        }
    ]
    ```
    
    **Performance Considerations:**
        - Returns all invoices without pagination
        - May be slow for large datasets
        - Use with caution in production environments
        - Consider using the paginated endpoint for large datasets
        
    **Error Codes:**
        - **500**: Internal server error during data retrieval
        
    **Notes:**
        - No filtering or pagination applied
        - Returns complete invoice records
        - Suitable for data export or bulk processing
        - Use paginated endpoint for better performance with large datasets
    """
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
    filename: str = Query(...),
    current_user: User = Depends(get_current_user)
):
    """
    Download invoice PDF file by filename path.

    **Summary:**
        Generates a presigned URL for downloading an invoice PDF file from the
        dedicated invoices S3 bucket. The URL provides secure, time-limited
        access to the invoice file without requiring direct S3 credentials.

    **Query Parameters:**
        - **filename** (`str`, required): The full S3 path to the PDF file
          (e.g., 'invoices/bmwpsupply_at_gmail.com/2026-01/19bb4e4f85460b3f_doc00076757.pdf')

    **Returns:**
        - **Dict**: Object containing the download link:
            - **link** (`str`): Presigned S3 URL for downloading the PDF

    **Response Example:**
    ```json
    {
        "link": "https://s3.amazonaws.com/invoices-bucket/invoices/bmwpsupply_at_gmail.com/2026-01/19bb4e4f85460b3f_doc00076757.pdf?AWSAccessKeyId=..."
    }
    ```

    **Process Flow:**
        1. Authenticates the user
        2. Uses the filename directly as the S3 key
        3. Generates presigned URL with expiration time
        4. Returns secure download link

    **Error Codes:**
        - **401**: Authentication required
        - **404**: File not available

    **Notes:**
        - Presigned URLs have limited expiration time (180 seconds)
        - Authentication required via get_current_user dependency
        - File path is used directly without database lookups
        - Uses dedicated invoice PDFs bucket and credentials
    """
    logger.info(f"GET /invoice/download - Downloading invoice: {filename}")
    try:
        url = get_invoice_pdf_presigned_url(
            file_key=filename,
            expiration_time=180
        )

        if url is None:
            raise HTTPException(
                status_code=404,
                detail="Couldn't fetch requested file"
            )

        logger.info(f"GET /invoice/download - Successfully generated download URL for: {filename}")
        return {"link": url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /invoice/download - Error downloading invoice {filename}: {str(e)}")
        raise HTTPException(
            status_code=404,
            detail="Couldn't fetch requested file"
        )


def reprocess_invoice_background_task(invoice_id: str, supplier: str, filename: str):
    """
    Background task to reprocess an invoice without blocking the API response.
    
    Args:
        invoice_id: The ID of the invoice to reprocess
        supplier: The supplier name
        filename: The filename of the invoice
    """
    logger.info(f"Background task started: Reprocessing invoice {invoice_id}")
    
    try:
        # Create a new database session for the background task
        from mpi_backend.database import SessionLocal
        db = SessionLocal()
        
        try:
            # Download invoice from S3
            invoice_url = get_presigned_url(file_key=f'{supplier}/{invoice_id}')
            if not invoice_url:
                logger.error(f"Background task - Couldn't fetch requested Invoice URL for: {invoice_id}")
                return
            
            # Create upload directory (sanitize supplier for filesystem safety)
            safe_supplier = _sanitize_path_component(supplier)
            upload_folder = os.path.join(INVOICE_DOWNLOAD_FOLDER, safe_supplier)
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            
            # Download file
            response = requests.get(invoice_url, timeout=30)
            if response.status_code == 200:
                file_path = os.path.join(upload_folder, filename)
                with open(file_path, 'wb') as file:
                    file.write(response.content)
            else:
                logger.error(f"Background task - Failed to download invoice from URL: {invoice_url}, status: {response.status_code}")
                return
            
            # Convert and process the invoice
            converted_files, failed_files = convert_single_invoice(
                file_path, supplier
            )
            if failed_files:
                logger.error(f"Background task - Failed to convert invoice: {failed_files}")
                return
            
            # Process extracted data with existing invoice ID
            process_extracted_data(
                converted_files, failed_files, existing_invoice_id=invoice_id
            )
            
            # Clean up files after processing
            for entry in os.listdir(upload_folder):
                path = os.path.join(upload_folder, entry)
                try:
                    if os.path.isfile(path) or os.path.islink(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                except Exception:
                    pass
            
            logger.info(f"Background task completed: Successfully reprocessed invoice {filename}")
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Background task failed for invoice {invoice_id}: {str(e)}")


@router.post("/upload")
async def upload_and_process_invoice(
    supplier_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload and process invoice PDF file synchronously.
    
    **Summary:**
        Uploads an invoice PDF file for a specific supplier and processes it
        synchronously to extract data and create invoice records. This endpoint
        handles the complete workflow from file upload to data extraction and
        storage.
        
    **Form Data:**
        - **supplier_id** (`int`, required): The ID of the supplier for the invoice
        - **file** (`UploadFile`, required): PDF file to upload and process
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Processing results containing:
            - **status** (`str`): Processing status ('created', 'updated', 'skipped', 'error')
            - **message** (`str`): Detailed status message
            - **filename** (`str`): Original filename
            - **supplier** (`str`): Supplier name
            - **invoice_id** (`str`, optional): Created/updated invoice ID
            - **ref_no** (`str`, optional): Invoice reference number
            - **vendor** (`str`, optional): Vendor information
            - **date** (`str`, optional): Invoice date
            
    **Response Examples:**
    
    **Success Response:**
    ```json
    {
        "status": "created",
        "message": "Invoice processed successfully",
        "filename": "invoice_001.pdf",
        "supplier": "BMW Plumbing",
        "invoice_id": "123",
        "ref_no": "REF-001",
        "vendor": "BMW Plumbing Supplies",
        "date": "2024-01-15"
    }
    ```
    
    **Skipped Response:**
    ```json
    {
        "status": "skipped",
        "message": "Invoice already exists",
        "filename": "invoice_001.pdf",
        "supplier": "BMW Plumbing"
    }
    ```
    
    **Process Flow:**
        1. Validates file type (PDF only)
        2. Verifies supplier exists
        3. Saves file to temporary storage
        4. Converts PDF to Excel format
        5. Extracts and processes invoice data
        6. Creates or updates invoice records
        7. Uploads file to S3 storage
        8. Cleans up temporary files
        
    **Error Codes:**
        - **400**: Invalid file type (non-PDF files)
        - **404**: Supplier not found
        - **500**: Processing error or file conversion failure
        
    **File Requirements:**
        - Only PDF files are accepted
        - File should contain valid invoice data
        - File size should be reasonable for processing
        
    **Notes:**
        - Processing is synchronous (blocks until complete)
        - Duplicate detection prevents processing same invoice twice
        - Temporary files are automatically cleaned up
        - File is stored in S3 with supplier-specific path
        - Invoice items are extracted and stored separately
    """
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

        # Create upload directory (sanitize supplier for filesystem safety)
        safe_supplier = _sanitize_path_component(supplier)
        upload_folder = os.path.normpath(os.path.join(INVOICE_DOWNLOAD_FOLDER, safe_supplier))
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

        # Process extracted data and get result
        results = process_extracted_data(converted_files, failed_files)
        result = results[0] if results else None
        if not result:
            logger.error(f"POST /invoice/upload - No result from processing for: {file.filename}")
            raise HTTPException(
                status_code=500, 
                detail="No result from invoice processing"
            )

        from mpi_backend.database.models.Invoice import Invoice
        created_invoice = None
        invoice_id = result.get("invoice_id")
        status = result.get("status")
        message = result.get("message")
        ref_no = result.get("ref_no")
        vendor = result.get("vendor")
        date = result.get("date")

        if status == "skipped":
            logger.warning(f"POST /invoice/upload - {message}")
            return {
                "status": "skipped",
                "message": message,
                "filename": file.filename,
                "supplier": supplier
            }
        elif status in ("updated", "created") and invoice_id:
            created_invoice = db.query(Invoice).filter_by(id=invoice_id).first()
        elif status == "error":
            logger.error(f"POST /invoice/upload - {message}")
            raise HTTPException(status_code=500, detail=message)
        # Fallback: try to fetch by filename (legacy)
        if not created_invoice:
            created_invoice = db.query(Invoice).filter_by(
                filename=file.filename, 
                supplier_id=supplier_id
            ).order_by(Invoice.id.desc()).first()

        if not created_invoice:
            logger.error(f"POST /invoice/upload - Failed to retrieve invoice record for: {file.filename}")
            raise HTTPException(
                status_code=500, 
                detail="Failed to retrieve invoice record"
            )

        # Upload to S3
        s3_key = f'{supplier}/{created_invoice.id}'
        upload_file(file_name=file_path, file_key=s3_key)

        # Clean up files after processing (handle files and directories)
        for entry in os.listdir(upload_folder):
            path = os.path.join(upload_folder, entry)
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:
                # Do not fail response on cleanup issues
                pass

        logger.info(f"POST /invoice/upload - Successfully uploaded and processed invoice: {file.filename}")
        return {
            "status": status,
            "message": message,
            "filename": file.filename,
            "supplier": supplier,
            "invoice_id": str(created_invoice.id),
            "ref_no": ref_no,
            "vendor": vendor,
            "date": date
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /invoice/upload - Error in upload endpoint: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Upload failed: {str(e)}"
        )


@router.post("/bulk-upload")
async def bulk_upload_invoices(
    supplier_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload multiple invoice PDF files and queue them for extraction.
    
    **Summary:**
        Accepts a supplier ID and a list of PDF files. Uploads them to S3 following
        the structure `invoices/{supplier_name}/{date}/{filename}` and adds them
        to the PDF extraction queue for processing via a database trigger.
        
    **Form Data:**
        - **supplier_id** (`int`, required): The ID of the supplier for the invoices
        - **files** (`List[UploadFile]`, required): List of PDF files to upload
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **List[Dict]**: List of processing results for each file
    """
    logger.info(f"POST /invoice/bulk-upload - Uploading {len(files)} invoices for supplier_id: {supplier_id}")
    controller = UserUploadedPdfController(db)
    results = await controller.bulk_upload_invoices(
        supplier_id=supplier_id,
        files=files,
        user_id=str(current_user.id)
    )
    return results


@router.get("/uploads")
def get_recent_uploads(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
    supplier_id: Optional[int] = Query(None, description="Filter by supplier ID"),
    current_user: User = Depends(get_current_user)
):
    """
    Get paginated list of user-uploaded PDF invoices with their extraction status.

    **Summary:**
        Returns all files uploaded by users via the bulk-upload endpoint, ordered
        by most-recent upload first. Each row includes the extraction queue status
        (pending, in_progress, completed, failed) so the front-end can show a
        live processing state.

    **Query Parameters:**
        - **page** (`int`, default=1): Page number (1-based)
        - **size** (`int`, default=20): Items per page (1-100)
        - **supplier_id** (`int`, optional): Filter results to one supplier

    **Returns:**
        Paginated envelope:
        ```json
        {
            "items": [
                {
                    "id": "uuid",
                    "filename": "INV-2026-0042.pdf",
                    "s3_file_key": "invoices/Flowmark/2026-02/INV-2026-0042.pdf",
                    "supplier_id": 3,
                    "supplier_name": "Flowmark",
                    "uploaded_at": "2026-02-23T10:15:00+00:00",
                    "queue_status": "completed",
                    "queue_error": null
                    "queue_id": "uuid"
                }
            ],
            "total": 42,
            "page": 1,
            "size": 10,
            "pages": 5
        }
        ```

    **queue_status values:**
        - `pending`     — queued, not yet picked up by the AI worker
        - `in_progress` — AI worker is currently extracting
        - `completed`   — extraction finished successfully
        - `failed`      — extraction failed (see queue_error for details)
        - `null`        — queue row not yet created (race condition, rare)

    **Error Codes:**
        - **401**: Authentication required
        - **500**: Internal server error
    """
    logger.info(
        f"GET /invoice/uploads - page={page}, size={size}, supplier_id={supplier_id}"
    )
    try:
        result = UserUploadedPdfController(db).get_recent_uploads(
            page=page,
            size=size,
            supplier_id=supplier_id,
            user_id=str(current_user.id)
        )
        return result
    except Exception as e:
        logger.error(f"GET /invoice/uploads - Error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve recent uploads"
        )


@router.get("/uploads/{queue_id}/extraction-details")
def get_upload_extraction_details(
    queue_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get extracted invoice header fields for a specific upload by its extraction queue ID.

    **Summary:**
        Queries the `raw.model_extracted_data` for the row linked to the given `queue_id` (pdf_extraction_queue.id).
        Returns the best latest extraction attempt (highest validation score). Returns 404 if the AI worker
        has not yet processed the file.

    **Path Parameters:**
        - **queue_id** (`str`, required): The UUID of the pdf_extraction_queue row
          (returned as `queue_id` in the `/invoice/uploads` response)

    **Returns:**
    ```json
    {
        "confidence_score": 0.98,
        "validation_score": 100,
        "ref_no": "INV-88392",
        "date": "2026-02-20",
        "po_number": "PO-2026-019",
        "tax": "0",
        "sub_total": "4250.00",
        "freight": "0",
        "status": "model_approved",
        "extracted_at": "2026-02-21T08:32:10+00:00"
    }
    ```

    **Error Codes:**
        - **401**: Authentication required
        - **404**: Extraction not found — file has not been processed yet
        - **500**: Internal server error
    """
    logger.info(f"GET /invoice/uploads/{queue_id}/extraction-details")
    try:
        result = UserUploadedPdfController(db).get_extracted_header_details(queue_id=queue_id)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Extraction data not found. The file may still be processing."
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"GET /invoice/uploads/{queue_id}/extraction-details - Error: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve extraction details"
        )


@router.post("/process")
async def process_again(
    invoice_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reprocess an existing invoice to update extracted data (TRUE ASYNC).
    
    **Summary:**
        Queues an existing invoice for reprocessing in a dedicated background thread pool.
        This endpoint returns immediately while the actual reprocessing happens in a separate
        thread pool, ensuring ZERO blocking of other API requests. Perfect for bulk operations.
        
    **Query Parameters:**
        - **invoice_id** (`str`, required): The ID of the invoice to reprocess
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Immediate response containing:
            - **status** (`str`): Confirmation message
            - **invoice_id** (`str`): The invoice ID being reprocessed
            - **filename** (`str`): Original filename
            - **message** (`str`): Status information
            
    **Response Example:**
    ```json
    {
        "status": "Invoice reprocessing queued successfully",
        "invoice_id": "123",
        "filename": "invoice_001.pdf",
        "message": "Reprocessing started in background thread pool. Check logs for progress."
    }
    ```
    
    **Process Flow:**
        1. Validates invoice exists and gets supplier info
        2. Queues task in dedicated background thread pool
        3. Returns immediate response (ZERO blocking)
        4. Background thread handles:
           - Downloads PDF file from S3
           - Converts PDF to Excel format
           - Reprocesses extracted data
           - Updates existing invoice items
           - Cleans up temporary files
        
    **Error Codes:**
        - **404**: Invoice not found or supplier not found
        - **500**: Validation error
        
    **Reprocessing Behavior:**
        - Updates existing invoice items without deleting invoice record
        - Enhanced duplicate detection prevents data loss
        - Preserves original invoice metadata
        - Updates extracted item data with latest processing logic
        
    **Performance Benefits:**
        - **TRUE ASYNC**: Runs in separate thread pool (not FastAPI's event loop)
        - **ZERO BLOCKING**: Other API calls are never delayed
        - **BULK FRIENDLY**: Can process 100+ invoices simultaneously
        - **SCALABLE**: Dedicated thread pool with configurable workers
        - **MONITORED**: Comprehensive logging for progress tracking
        
    **Notes:**
        - Processing is TRUE ASYNC (separate thread pool)
        - Returns immediately with confirmation
        - Other API requests are NEVER blocked
        - Perfect for bulk reprocessing operations
        - Check application logs for processing status
        - Thread pool executor handles concurrent processing
    """
    logger.info(f"POST /invoice/process - Queuing invoice for async reprocessing: {invoice_id}")
    try:
        # Get invoice and supplier info for validation
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

        # Queue the background task using async executor (non-blocking)
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            BACKGROUND_EXECUTOR,
            reprocess_invoice_background_task,
            invoice_id,
            supplier,
            invoice.filename
        )
        
        # Don't await the future - let it run in background
        # This ensures the endpoint returns immediately
        logger.info(f"POST /invoice/process - Successfully queued invoice {invoice.filename} for async reprocessing")
        
        return {
            "status": "Invoice reprocessing queued successfully",
            "invoice_id": invoice_id,
            "filename": invoice.filename,
            "message": "Reprocessing started in background thread pool. Check logs for progress."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /invoice/process - Error in reprocess endpoint: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to queue reprocessing: {str(e)}"
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
    """
    Sort invoices by specified column with pagination.
    
    **Summary:**
        Retrieves and sorts invoices by a specified column in either ascending
        or descending order. This endpoint provides flexible sorting capabilities
        for invoice data with automatic pagination.
        
    **Query Parameters:**
        - **column_name** (`str`, required): Column to sort by:
            - 'Date': Sort by invoice date
            - 'File Name': Sort by filename
            - 'Status': Sort by processing status
            - 'Job Address': Sort by customer job location
            - 'Invoice': Sort by invoice reference number
            - 'Supplier': Sort by supplier name
        - **sort_order** (`str`, default='ascending'): Sort direction:
            - 'ascending': A to Z, oldest to newest
            - 'descending': Z to A, newest to oldest
            
    **Returns:**
        - **Page[Invoice]**: Paginated response containing sorted invoice objects
        
    **Response Example:**
    ```json
    {
        "items": [
            {
                "id": 123,
                "invoice_id": "INV-2024-001",
                "filename": "invoice_001.pdf",
                "ref_no": "REF-001",
                "date": "2024-01-15",
                "status": "processed",
                "supplier_id": 1,
                "customer_job": "Project Alpha"
            }
        ],
        "total": 150,
        "page": 1,
        "size": 10,
        "pages": 15
    }
    ```
    
    **Supported Sort Columns:**
        - **Date**: Invoice date (chronological sorting)
        - **File Name**: Original PDF filename (alphabetical)
        - **Status**: Processing status (processed/unprocessed)
        - **Job Address**: Customer job location (alphabetical)
        - **Invoice**: Reference number (alphabetical)
        - **Supplier**: Supplier name (alphabetical)
        
    **Error Codes:**
        - **400**: Invalid column name specified
        
    **Notes:**
        - Automatic pagination is applied to results
        - Sort order affects all paginated pages consistently
        - Column names are case-sensitive and must match exactly
        - Default sort order is ascending if not specified
        - Results maintain sort order across all pages
    """
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
    invoice_id: str = Query(
        ...,
        description="Invoice ID(s) to delete. Can be a single ID or multiple comma-separated IDs (e.g., '778cc73f-845a-491d-b1a2-c1bece2ca146' or '778cc73f-845a-491d-b1a2-c1bece2ca146,9a8b7c6d-5e4f-3g2h-1i0j-k1l2m3n4o5p6')"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete one or more invoices and their associated files from the system.
    
    **Summary:**
        Deletes one or more invoices based on the provided invoice_id parameter.
        Supports both single invoice deletion and bulk deletion of multiple invoices
        using comma-separated values.
        
    **Query Parameters:**
        - **invoice_id** (`str`, required): Invoice ID(s) to delete:
            - Single ID: "778cc73f-845a-491d-b1a2-c1bece2ca146"
            - Multiple IDs: "778cc73f-845a-491d-b1a2-c1bece2ca146,9a8b7c6d-5e4f-3g2h-1i0j-k1l2m3n4o5p6"
            - Comma-separated without spaces: "778cc73f-845a-491d-b1a2-c1bece2ca146,9a8b7c6d-5e4f-3g2h-1i0j-k1l2m3n4o5p6"
            
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Deletion summary containing:
            - **deleted_ids** (`List[str]`): Array of successfully deleted invoice IDs
            - **not_found_ids** (`List[str]`): Array of invoice IDs that were not found
            - **status** (`str`): Human-readable status message
            
    **Response Examples:**
    
    **Single Invoice Deletion:**
    ```json
    {
        "deleted_ids": ["778cc73f-845a-491d-b1a2-c1bece2ca146"],
        "not_found_ids": [],
        "status": "Invoice 778cc73f-845a-491d-b1a2-c1bece2ca146 and associated file deleted successfully."
    }
    ```
    
    **Multiple Invoice Deletion:**
    ```json
    {
        "deleted_ids": ["778cc73f-845a-491d-b1a2-c1bece2ca146", "9a8b7c6d-5e4f-3g2h-1i0j-k1l2m3n4o5p6"],
        "not_found_ids": [],
        "status": "Deleted 2 invoice(s)."
    }
    ```
    
    **Partial Deletion (Some Not Found):**
    ```json
    {
        "deleted_ids": ["778cc73f-845a-491d-b1a2-c1bece2ca146"],
        "not_found_ids": ["9a8b7c6d-5e4f-3g2h-1i0j-k1l2m3n4o5p6"],
        "status": "Deleted 1 invoice(s)."
    }
    ```
    
    **Process Flow:**
        1. Parses the invoice_id parameter for comma-separated values
        2. Validates each ID format
        3. Attempts to delete each invoice and associated files
        4. Tracks successful deletions and failures
        5. Returns comprehensive deletion summary
        
    **Error Codes:**
        - **400**: No invoice_id provided or invalid format
        - **401**: Unauthorized (invalid or missing JWT token)
        - **500**: Internal server error during deletion process
        
    **Notes:**
        - Comma-separated values should not contain spaces
        - Invalid IDs in the list will be reported in not_found_ids
        - Associated invoice files are also deleted from storage
        - Database records and related invoice items are permanently removed
        - Operation is atomic - either all valid invoices are deleted or none
    """
    logger.info(f"DELETE /invoice/delete - Deleting invoice(s): {invoice_id}")
    
    try:
        # Parse comma-separated invoice IDs
        if not invoice_id or not invoice_id.strip():
            raise HTTPException(
                status_code=400, 
                detail="invoice_id parameter is required"
            )
        
        # Split by comma and clean up whitespace
        ids_to_delete = [id.strip() for id in invoice_id.split(',') if id.strip()]
        
        if not ids_to_delete:
            raise HTTPException(
                status_code=400, 
                detail="At least one valid invoice_id is required"
            )
        
        invoice_controller = InvoiceController(db)
        
        if len(ids_to_delete) == 1:
            # Single invoice deletion
            deleted_id = invoice_controller.delete_invoice(ids_to_delete[0], db)
            return {
                "deleted_ids": [deleted_id],
                "not_found_ids": [],
                "status": f"Invoice {deleted_id} and associated file deleted successfully."
            }
        else:
            # Multiple invoice deletion
            summary = invoice_controller.delete_invoices(ids_to_delete, db)
            return {
                "deleted_ids": summary["deleted_ids"],
                "not_found_ids": summary["not_found_ids"],
                "status": f"Deleted {len(summary['deleted_ids'])} invoice(s)."
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DELETE /invoice/delete - Error deleting invoice(s) {invoice_id}: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Deletion failed: {str(e)}"
        )


