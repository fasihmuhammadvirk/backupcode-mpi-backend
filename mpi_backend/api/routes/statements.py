from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from mpi_backend.database import get_db
from mpi_backend.database.controllers.statement_controller import (
    StatementController
)
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.s3_utils import get_presigned_url

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
    supplier_name: Optional[str] = Query(
        None,
        description="Supplier name to filter by"
    ),
    status: Optional[str] = Query(
        None,
        description="Invoice status filter: 'Processed', 'Failed', or 'all'"
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
    
    **Parameters:**
    - **from_date**: Start date filter in DD/MM/YYYY format 
      (filters by statement_date)
    - **to_date**: End date filter in DD/MM/YYYY format 
      (filters by statement_date)
    - **supplier_name**: Filter by supplier name (partial match supported)
    - **status**: Filter by reconciliation status 
      ('Processed', 'Failed', 'all')
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
    - **status**: Reconciliation status (Processed/Failed/Unknown)
    - **original_amount**: Original invoice amount
    - **balance**: Outstanding balance
    
    **Example:**
    ```
    GET /statements/invoice-data?from_date=01/05/2025&to_date=01/06/2025&
    status=Processed&page=1&page_size=20
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
        valid_statuses = ['processed', 'failed', 'all', None]
        if status and status.lower() not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {valid_statuses[:-1]}"
            )
        
        logger.info(
            f"Getting invoice data - Dates: {from_date} to {to_date}, "
            f"Supplier: {supplier_name}, Status: {status}, "
            f"Page: {page}, Size: {page_size}"
        )
        
        # Get data from controller
        controller = StatementController(db)
        result = controller.get_statement_invoice_data(
            from_date=from_date_obj,
            to_date=to_date_obj,
            supplier_name=supplier_name,
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
        # Statements are stored with key pattern: statements/{filename}
        s3_key = f"statements/{pdf_filename}"
        
        try:
            presigned_url = get_presigned_url(
                file_key=s3_key,
                expiration_time=180,  # 3 minutes
                is_invoice=False
            )
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
 