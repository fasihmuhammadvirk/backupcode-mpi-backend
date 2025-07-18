from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import boto3

from mpi_backend.database import get_db
from mpi_backend.database.controllers.StatementController import (
    StatementController
)
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.s3_utils import get_presigned_url
from mpi_backend.utils.statement_extractor.extractor import StatementExtractor
from mpi_backend.config import (
    INVOICE_DOWNLOAD_FOLDER, 
    AWS_SERVER_PUBLIC_KEY, 
    AWS_SERVER_SECRET_KEY, 
    REGION, 
    BUCKET_NAME
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/statements", tags=["Monthly Statements"])


def parse_date_ddmmyyyy(date_str: str) -> datetime.date:
    """Parse date from DD/MM/YYYY format"""
    try:
        return datetime.strptime(date_str, '%d/%m/%Y').date()
    except ValueError:
        raise ValueError(
            f"Invalid date format: {date_str}. Expected DD/MM/YYYY"
        )


@router.get("/invoice-data")
def get_statement_invoice_data(
    search: Optional[str] = Query(
        None,
        description="Search term to look for in invoice numbers (full or partial match)",
        min_length=1
    ),
    from_date: Optional[str] = Query(
        None,
        description="Start date in DD/MM/YYYY format (e.g., '01/05/2025')",
        regex=r"^\d{1,2}/\d{1,2}/\d{4}$"
    ),
    to_date: Optional[str] = Query(
        None,
        description="End date in DD/MM/YYYY format (e.g., '01/06/2025')",
        regex=r"^\d{1,2}/\d{1,2}/\d{4}$"
    ),
    supplier_names: Optional[List[str]] = Query(
        None,
        description="List of supplier names, supplier IDs, or ['All'] to filter by. Use '0' for all suppliers."
    ),
    status: Optional[str] = Query(
        None,
        description="Invoice status filter: 'Processed', 'Failed', 'Unlisted', 'Missing System', 'Missing Statement', or 'all'"
    ),
    page: int = Query(
        1,
        ge=1,
        description="Page number (1-based)"
    ),
    page_size: int = Query(
        20,
        ge=1,
        le=100,
        description="Number of items per page (1-100)"
    ),
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Get statement invoice data with filters and pagination.
    
    Returns invoice data from statements including invoice details, 
    statement information, and reconciliation status.
    
    **Note:** Date filtering is applied to invoice_date, not statement_date.
    
    **Parameters:**
    - **search**: Search term to look for in invoice numbers (full or partial match)
    - **from_date**: Start date filter in DD/MM/YYYY format 
      (filters by invoice_date)
    - **to_date**: End date filter in DD/MM/YYYY format 
      (filters by invoice_date)
    - **supplier_names**: Filter by list of supplier names (partial match supported), 
      supplier IDs (numeric), ["All"] for all suppliers, or ["0"] for all suppliers
    - **status**: Filter by reconciliation status 
      ('Processed', 'Failed', 'Unlisted', 'Missing System', 'Missing Statement', 'All')
      - 'All' returns combined data from all categories
      - 'Missing System' returns invalid invoices from system (InvoiceItem table)
      - 'Missing Statement' returns invalid invoices from statements (PlumbingInvoice table)
    - **page**: Page number for pagination (starts from 1)
    - **page_size**: Number of items per page (1-100)
    
    **Returns:**
    - **data**: Array of invoice objects with required fields
    - **pagination**: Metadata about pagination 
      (total pages, current page, etc.)
    - **filters_applied**: Summary of applied filters
    
    **Response Fields:**
    Each invoice object contains:
    - **invoice_number**: The invoice number
    - **invoice_date**: Date of the invoice
    - **customer_po**: Customer PO number (customer_pi in requirements)
    - **statement_date**: Date of the statement containing this invoice
    - **supplier_name**: Name of the supplier
    - **status**: Reconciliation status (Processed/Failed/Unlisted/Missing System/Missing Statement)
    - **original_amount**: Original invoice amount
    - **balance**: Outstanding balance
    
    **Examples:**
    ```
    # Search by invoice number
    GET /statements/invoice-data?search=INV-12345
    
    # Search by invoice number with date filter
    GET /statements/invoice-data?search=456&from_date=01/05/2025&to_date=01/06/2025
    
    # Filter by date and status (no search)
    GET /statements/invoice-data?from_date=01/05/2025&to_date=01/06/2025&status=Processed
    
    # Get all suppliers' data
    GET /statements/invoice-data?supplier_names=All&page=1&page_size=20
    
    # Filter by single supplier ID
    GET /statements/invoice-data?supplier_names=3&page=1&page_size=20
    
    # Find missing/invalid invoice data from system
    GET /statements/invoice-data?status=Missing System&page=1&page_size=20
    
    # Find missing/invalid invoice data from statements  
    GET /statements/invoice-data?status=Missing Statement&page=1&page_size=20
    ```
    """
    try:
        # Parse and validate dates
        from_date_obj = None
        to_date_obj = None
        
        if from_date:
            try:
                from_date_obj = parse_date_ddmmyyyy(from_date)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid from_date format: {str(e)}"
                )
        
        if to_date:
            try:
                to_date_obj = parse_date_ddmmyyyy(to_date)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid to_date format: {str(e)}"
                )
        
        # Validate date range
        if from_date_obj and to_date_obj and from_date_obj > to_date_obj:
            raise HTTPException(
                status_code=400,
                detail="from_date must be earlier than or equal to to_date"
            )
        
        # Validate status parameter
        valid_statuses = ['processed', 'failed', 'unlisted', 'missing', 'missing system', 'missing statement', 'all', None]
        if status and status.lower() not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {valid_statuses[:-1]}"
            )
        
        logger.info(
            f"Getting invoice data - Search: {search}, "
            f"Dates: {from_date} to {to_date}, "
            f"Suppliers: {supplier_names}, Status: {status}, "
            f"Page: {page}, Size: {page_size}"
        )
        
        # Get data from controller
        controller = StatementController(db)
        
        # Use search method if search term is provided
        if search:
            result = controller.search_statement_invoice_data(
                search=search,
                from_date=from_date_obj,
                to_date=to_date_obj,
                supplier_names=supplier_names,
                status=status,
                page=page,
                page_size=page_size
            )
        else:
            result = controller.get_statement_invoice_data(
                from_date=from_date_obj,
                to_date=to_date_obj,
                supplier_names=supplier_names,
                status=status,
                page=page,
                page_size=page_size
            )
        
        if not result['success']:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Failed to retrieve data: "
                    f"{result.get('error', 'Unknown error')}"
                )
            )
        
        logger.info(
            f"Successfully retrieved {len(result['data'])} invoices "
            f"(page {page} of {result['pagination']['total_pages']})"
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in invoice data endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )



@router.get("/download")
def download_statement_pdf(
    statement_id: int = Query(
        ..., 
        description="ID of the statement to download"
    ),
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Download monthly statement PDF by statement ID.
    
    Returns a presigned URL for downloading the statement PDF from S3.
    The URL expires after 3 minutes for security.
    
    **Parameters:**
    - **statement_id**: The ID of the statement to download
    
    **Returns:**
    - **link**: Presigned S3 URL for downloading the PDF
    - **statement_info**: Basic statement information
    - **expires_in**: URL expiration time in seconds
    
    **Example:**
    ```
    GET /statements/download?statement_id=123
    ```
    
    **Response:**
    ```json
    {
        "link": "https://s3-presigned-url...",
        "statement_info": {
            "statement_id": 123,
            "supplier_name": "ABC Supplier",
            "statement_date": "2025-01-31",
            "pdf_filename": "statement_abc_202501.pdf"
        },
        "expires_in": 180
    }
    ```
    """
    try:
        logger.info(
            f"Downloading statement PDF for statement_id: {statement_id}"
        )
        
        # Get statement details
        controller = StatementController(db)
        statement_info = controller.get_statement_by_id(statement_id)
        
        if not statement_info:
            raise HTTPException(
                status_code=404, 
                detail=f"Statement with ID {statement_id} not found"
            )
        
        # Check if PDF filename exists
        pdf_filename = statement_info.get('pdf_filename')
        if not pdf_filename:
            raise HTTPException(
                status_code=404, 
                detail=f"No PDF file associated with statement {statement_id}"
            )
        
        # Generate presigned URL for statement PDF
        # Statements are stored with key pattern: statements/{filename}.pdf (due to is_invoice=True)
        s3_key = f"statements/{pdf_filename}"
        
        try:
            # Use the utility function which now includes inline content disposition
            presigned_url = get_presigned_url(
                file_key=s3_key,
                expiration_time=180,
                is_invoice=True
            )
            
            if not presigned_url:
                raise Exception("Failed to generate presigned URL")
        except Exception as e:
            logger.error(
                f"Error generating presigned URL for {s3_key}: {str(e)}"
            )
            raise HTTPException(
                status_code=500,
                detail="Could not generate download link for statement PDF"
            )
        
        logger.info(
            f"Successfully generated download link for statement "
            f"{statement_id}"
        )
        
        return {
            "link": presigned_url,
            "statement_info": {
                "statement_id": statement_info['statement_id'],
                "supplier_name": statement_info['supplier_name'],
                "statement_date": statement_info['statement_date'],
                "pdf_filename": statement_info['pdf_filename']
            },
            "expires_in": 180
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in statement download endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )
        
@router.post("/reprocess")
def reprocess_statement(
    statement_id: Optional[str] = Query(
        None, 
        description="ID of the statement to reprocess (optional)"
    ),
    supplier_name: Optional[str] = Query(
        None,
        description="Supplier name filter for bulk reprocessing (optional)"
    ),
    max_statements: int = Query(
        100,
        ge=1,
        le=1000,
        description="Maximum number of statements to reprocess in bulk (1-1000)"
    ),
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Reprocess monthly statements.
    
    This endpoint supports both single statement and bulk reprocessing.
    
    **Parameters:**
    - **statement_id**: The ID of the statement to reprocess (optional)
    - **supplier_name**: Supplier name filter for bulk reprocessing (optional)
    - **max_statements**: Maximum number of statements to reprocess in bulk (default: 100)
    
    **Usage Examples:**
    
    **Single Statement Reprocessing:**
    ```
    POST /statements/reprocess?statement_id=123
    ```
    
    **Bulk Reprocessing by Supplier:**
    ```
    # Reprocess all statements for a specific supplier
    POST /statements/reprocess?supplier_name=World Wide Plumbing
    
    # Reprocess all statements for a specific supplier with limit
    POST /statements/reprocess?supplier_name=World Wide Plumbing&max_statements=50
    ```
    
    **Bulk Reprocessing All Statements:**
    ```
    # Reprocess all statements (up to 100)
    POST /statements/reprocess
    
    # Reprocess all statements with custom limit
    POST /statements/reprocess?max_statements=200
    ```
    
    **Returns:**
    - **success**: Boolean indicating overall success
    - **message**: Summary message
    - **results**: Detailed results for each statement processed
    - **statistics**: Summary statistics
    """
    try:
        controller = StatementController(db)
        
        # Single statement reprocessing
        if statement_id and statement_id.isdigit():
            logger.info(f"Reprocessing single statement with ID: {statement_id}")
            
            result = controller.reprocess_statement(int(statement_id))
            
            if not result['success']:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Failed to reprocess statement: "
                        f"{result.get('error', 'Unknown error')}"
                    )
                )
            
            logger.info(f"Successfully reprocessed statement {statement_id}")
            return result
        
        # Bulk reprocessing
        else:
            # Determine the type of bulk reprocessing
            if supplier_name and not statement_id:
                logger.info(f"Starting bulk reprocessing for supplier: {supplier_name}, Max: {max_statements}")
            elif not supplier_name and not statement_id:
                logger.info(f"Starting bulk reprocessing for all suppliers, Max: {max_statements}")
            else:
                logger.info(f"Starting bulk reprocessing - Supplier: {supplier_name or 'All'}, Max: {max_statements}")
            
            result = controller.reprocess_all_statements(
                supplier_name=supplier_name,
                max_statements=max_statements
            )
            
            if not result['success']:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Bulk reprocessing failed: "
                        f"{result.get('error', 'Unknown error')}"
                    )
                )
            
            logger.info(f"Bulk reprocessing completed: {result['statistics']}")
            return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in statement reprocessing endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.delete("/{statement_id}")
def delete_statement(
    statement_id: int,
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Delete a monthly statement and all its associated invoice items.
    
    **Parameters:**
    - **statement_id**: The ID of the statement to delete
    
    **Returns:**
    - **success**: Boolean indicating if deletion was successful
    - **message**: Summary message
    - **details**: Information about what was deleted
    
    **Response Example:**
    ```json
    {
        "success": true,
        "message": "Statement 123 deleted successfully",
        "details": {
            "statement_id": 123,
            "supplier_name": "BMW Plumbing Supplies",
            "statement_date": "2025-01-31",
            "invoices_deleted": 15,
            "statements_deleted": 1
        }
    }
    ```
    
    **Note:** This operation is irreversible. All invoice data 
    associated with this statement will be permanently deleted.
    """
    try:
        logger.info(f"Delete request for statement ID: {statement_id}")
        
        controller = StatementController(db)
        result = controller.delete_statement(statement_id)
        
        if not result['success']:
            if 'not found' in result.get('error', '').lower():
                raise HTTPException(
                    status_code=404,
                    detail=result['error']
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=result['error']
                )
        
        logger.info(
            f"Successfully deleted statement {statement_id}: "
            f"{result['details']['invoices_deleted']} invoices removed"
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete statement endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )
       