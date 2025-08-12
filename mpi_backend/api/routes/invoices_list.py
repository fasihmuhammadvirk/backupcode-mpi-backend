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
import re
import shutil
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
        token: str = Depends(JWTBearer())
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
    token: str = Depends(JWTBearer())
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
    db: Session = Depends(get_db), 
    invoice_id: str = Query(None)
):
    """
    Download invoice PDF file by invoice ID.
    
    **Summary:**
        Generates a presigned URL for downloading an invoice PDF file from S3
        storage. The URL provides secure, time-limited access to the invoice
        file without requiring direct S3 credentials.
        
    **Query Parameters:**
        - **invoice_id** (`str`, required): The ID of the invoice to download
        
    **Returns:**
        - **Dict**: Object containing the download link:
            - **link** (`str`): Presigned S3 URL for downloading the PDF
            
    **Response Example:**
    ```json
    {
        "link": "https://s3.amazonaws.com/bucket/supplier_name/invoice_id?AWSAccessKeyId=..."
    }
    ```
    
    **Process Flow:**
        1. Retrieves invoice record by invoice ID
        2. Gets supplier information for the invoice
        3. Constructs S3 file key using supplier name and invoice ID
        4. Generates presigned URL with expiration time
        5. Returns secure download link
        
    **Error Codes:**
        - **404**: Invoice not found or file not available
        
    **Notes:**
        - Presigned URLs have limited expiration time
        - File access is controlled through S3 permissions
        - No authentication required for this endpoint
        - URL provides direct access to the PDF file
        - File path follows pattern: {supplier_name}/{invoice_id}
    """
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
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{safe_supplier}'
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


@router.post("/process")
async def process_again(
    invoice_id: str, 
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Reprocess an existing invoice to update extracted data.
    
    **Summary:**
        Downloads an existing invoice from S3 storage and reprocesses it to
        update the extracted data. This is useful when the original processing
        failed or when updated processing logic needs to be applied to existing
        invoices.
        
    **Query Parameters:**
        - **invoice_id** (`str`, required): The ID of the invoice to reprocess
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Reprocessing results containing:
            - **status** (`str`): Success message
            - **invoice_id** (`str`): The reprocessed invoice ID
            - **filename** (`str`): Original filename
            
    **Response Example:**
    ```json
    {
        "status": "Success Invoice 'invoice_001.pdf' reprocessed successfully.",
        "invoice_id": "123",
        "filename": "invoice_001.pdf"
    }
    ```
    
    **Process Flow:**
        1. Retrieves existing invoice record
        2. Gets supplier information
        3. Downloads PDF file from S3
        4. Saves file to temporary storage
        5. Converts PDF to Excel format
        6. Reprocesses extracted data
        7. Updates existing invoice items
        8. Cleans up temporary files
        
    **Error Codes:**
        - **404**: Invoice not found or file not available
        - **500**: Processing error or file conversion failure
        
    **Reprocessing Behavior:**
        - Updates existing invoice items without deleting invoice record
        - Enhanced duplicate detection prevents data loss
        - Preserves original invoice metadata
        - Updates extracted item data with latest processing logic
        
    **Notes:**
        - Processing is synchronous (blocks until complete)
        - Original invoice record is preserved
        - Invoice items are updated with new extracted data
        - Temporary files are automatically cleaned up
        - Useful for applying updated extraction logic to existing invoices
    """
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

        # Create upload directory (sanitize supplier for filesystem safety)
        safe_supplier = _sanitize_path_component(supplier)
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{safe_supplier}'
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        # Download file
        # Stream download with small timeout to avoid blocking and suppress
        # verbose third-party logs
        response = requests.get(invoice_url, timeout=30)
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
        # The enhanced duplicate detection logic will handle updating existing invoice items
        # without deleting the invoice record itself
        process_extracted_data(
            converted_files, failed_files, existing_invoice_id=invoice_id
        )

        # Clean up files after processing (handle files and directories)
        for entry in os.listdir(upload_folder):
            path = os.path.join(upload_folder, entry)
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass

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
    invoice_id: str, 
    db: Session = Depends(get_db), 
    token: str = Depends(JWTBearer())
):
    """
    Delete an invoice and its associated file from the system.
    
    **Summary:**
        Permanently deletes an invoice record from the database and removes
        the associated PDF file from S3 storage. This operation is irreversible
        and will also delete all related invoice items.
        
    **Query Parameters:**
        - **invoice_id** (`str`, required): The ID of the invoice to delete
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Deletion confirmation message:
            - **status** (`str`): Success message confirming deletion
            
    **Response Example:**
    ```json
    {
        "status": "Invoice 123 and associated file deleted successfully."
    }
    ```
    
    **Deletion Process:**
        1. Removes invoice record from database
        2. Deletes associated invoice items
        3. Removes PDF file from S3 storage
        4. Cleans up any related temporary files
        
    **Cascade Effects:**
        - Invoice record is permanently deleted
        - All associated invoice items are removed
        - PDF file is deleted from S3 storage
        - Related metadata is cleaned up
        
    **Error Codes:**
        - **404**: Invoice not found
        - **500**: Deletion error or file removal failure
        
    **Notes:**
        - This operation is irreversible
        - All related data will be permanently lost
        - Use with caution in production environments
        - Consider backing up data before deletion
        - Deletion includes both database records and S3 files
    """
    # Delete from database
    invoice_controller = InvoiceController(db)
    invoice_id = invoice_controller.delete_invoice(invoice_id, db)

    return {
        "status": f"Invoice {invoice_id} and associated file deleted successfully."
    }


