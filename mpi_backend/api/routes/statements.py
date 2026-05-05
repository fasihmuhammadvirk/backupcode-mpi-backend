from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from mpi_backend.database import get_db
from mpi_backend.database.controllers.StatementController import (
    StatementController
)
from mpi_backend.database.schemas.MonthlyStatement import (
    MonthlyStatementExportAllRequest,
    MonthlyStatementExportSelectedRequest
)
from mpi_backend.database.models.User import User
from mpi_backend.utils.auth.dependencies import get_current_user
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
        description="List of supplier names, supplier IDs, or ['All'] to filter by. Use '0' for Unknown Supplier."
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
    current_user: User = Depends(get_current_user)
):
    """
    Get statement invoice data with filters and pagination.
    
    Returns invoice data from statements including invoice details, 
    statement information, and reconciliation status.
    
    **Note:** Date filtering behavior:
    - System invoices (no statement): filtered by their own invoice_date
    - Statement invoices: filtered by statement month/year (statement_date)
    
    **Parameters:**
    - **search**: Search term to look for in invoice numbers (full or partial match)
    - **from_date**: Start date filter in DD/MM/YYYY format 
      (filters by invoice_date)
    - **to_date**: End date filter in DD/MM/YYYY format 
      (filters by invoice_date)
    - **supplier_names**: Filter by list of supplier names (partial match supported),
      supplier IDs (numeric), ["All"] for all suppliers, or ["0"] for Unknown Supplier
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
        logger.error(f"Error in invoice data endpoint: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve invoice data. Please contact support if the issue persists."
        )


@router.get("/download")
def download_statement_pdf(
    statement_id: int = Query(
        ..., 
        description="ID of the statement to download"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
        logger.error(f"Error in statement download endpoint: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to download statement. Please contact support if the issue persists."
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
    current_user: User = Depends(get_current_user)
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
        logger.error(f"Error in statement reprocessing endpoint: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to reprocess statement. Please contact support if the issue persists."
        )


@router.get("/aggregate-monthly")
def get_aggregate_monthly(
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
        description="List of supplier names, supplier IDs, or ['All'] to filter by. Use '0' for Unknown Supplier."
    ),
    status: Optional[str] = Query(
        None,
        description="Invoice status filter: 'Processed', 'Failed', 'Unlisted', 'Missing System', 'Missing Statement', or 'all'"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get aggregated statistics for statement invoices.
    
    Returns aggregated amounts from all/processed/failed/unlisted/missing invoices
    based on the selected filters. Uses the same filtering logic as the invoice-data endpoint
    but returns aggregated totals instead of paginated data.
    
    **Parameters:**
    - **from_date**: Start date filter in DD/MM/YYYY format 
    - **to_date**: End date filter in DD/MM/YYYY format 
    - **supplier_names**: Filter by list of supplier names (partial match supported),
      supplier IDs (numeric), ["All"] for all suppliers, or ["0"] for Unknown Supplier
    - **status**: Filter by reconciliation status
      ('Processed', 'Failed', 'Unlisted', 'Missing System', 'Missing Statement', 'All')
    
    **Returns:**
    - **quantity**: Total number of invoices
    - **average**: Average of original invoice amounts (formatted currency)
    - **amount**: Sum of all original invoice amounts (formatted currency)
    - **filters_applied**: Summary of applied filters
    
    **Examples:**
    ```
    # Get aggregates for a specific month
    GET /statements/aggregate-monthly?from_date=01/05/2025&to_date=31/05/2025&status=Processed
    
    # Get aggregates for all suppliers
    GET /statements/aggregate-monthly?supplier_names=All&from_date=01/01/2025&to_date=31/12/2025
    
    # Get aggregates for failed invoices
    GET /statements/aggregate-monthly?status=Failed&from_date=01/01/2025&to_date=31/12/2025
    ```
    """
    try:
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
        
        if from_date_obj and to_date_obj and from_date_obj > to_date_obj:
            raise HTTPException(
                status_code=400,
                detail="from_date must be earlier than or equal to to_date"
            )
        
        valid_statuses = ['processed', 'failed', 'unlisted', 'missing', 'missing system', 'missing statement', 'all', None]
        if status and status.lower() not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {valid_statuses[:-1]}"
            )
        
        logger.info(
            f"Getting aggregate monthly - "
            f"Dates: {from_date} to {to_date}, "
            f"Suppliers: {supplier_names}, Status: {status}"
        )
        
        controller = StatementController(db)
        result = controller.get_aggregate_monthly(
            from_date=from_date_obj,
            to_date=to_date_obj,
            supplier_names=supplier_names,
            status=status
        )
        
        if not result['success']:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Failed to calculate aggregates: "
                    f"{result.get('error', 'Unknown error')}"
                )
            )
        
        logger.info(
            f"Successfully calculated aggregates: "
            f"Quantity: {result['quantity']}, "
            f"Average: {result['average']}, "
            f"Amount: {result['amount']}"
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in aggregate monthly endpoint: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve aggregate data. Please contact support if the issue persists."
        )


@router.delete("/{statement_id}")
def delete_statement(
    statement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
        logger.error(f"Error in delete statement endpoint: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete statement. Please contact support if the issue persists."
        )


@router.post("/export")
async def export_selected_statements(
    request: MonthlyStatementExportSelectedRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Export specific statement invoices by their IDs to Excel.
    
    **Summary:**
        Exports specific invoices from monthly statements identified by their invoice IDs.
        Each supplier gets its own sheet in the Excel file.
        
    **Request Body:**
        - **request** (`MonthlyStatementExportSelectedRequest`, required):
            - **invoice_ids** (`List[str]`, required): List of IDs to export. Supports three types: UUIDs (Invoice table), integer invoice_ids (plumbing_invoices), integer item IDs (invoice_items). The system intelligently detects and handles all types.
            
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **str**: Presigned S3 URL for downloading the Excel file
        
    **Response Example:**
    ```json
    "https://s3.amazonaws.com/bucket/Exports/MonthlyStatement_Selected.xlsx?AWSAccessKeyId=..."
    ```
    
    **Excel File Structure:**
        - Each supplier gets its own sheet
        - Sheet name = Supplier name (max 31 chars)
        - Sheets sorted alphabetically by supplier name
        - Data within each sheet sorted by Invoice Date (ascending)
        
    **Columns (in order):**
        1. Invoice Number
        2. Invoice Date (YYYY-MM-DD)
        3. Statement Date (YYYY-MM-DD)
        4. Supplier Name
        5. Status (Processed/Failed)
        6. Original Amount (currency)
        7. Balance (currency)
        
    **Request Example:**
    ```json
    {
      "invoice_ids": [
        "bf5daa2e-6d21-49f1-a855-81203f6095fa",
        "123",
        "456"
      ]
    }
    ```
    
    **Intelligent ID Handling:**
        - The endpoint automatically detects three ID types:
          1. **UUIDs** - From Invoice table (parent invoice with all items)
          2. **Integers (invoice_id)** - From plumbing_invoices (statement invoices)
          3. **Integers (item_id)** - From invoice_items (individual items)
        - Mixed types in the same request are fully supported
        - System queries appropriate tables based on ID format
    
    **Notes:**
        - Only invoices that exist will be exported
        - File naming: `MonthlyStatement_Selected_{timestamp}.xlsx`
        - Returns S3 presigned URL for download
    """
    try:
        import time
        start_time = time.time()
        
        if not request.invoice_ids:
            raise HTTPException(status_code=400, detail="invoice_ids list cannot be empty")
        
        controller = StatementController(db)
        download_url = controller.export_selected_statements(
            invoice_ids=request.invoice_ids
        )
        
        processing_time = time.time() - start_time
        logger.info(f"Selected statements export completed in {processing_time:.2f} seconds for {len(request.invoice_ids)} invoices")
        
        return download_url
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Selected statements export error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail="Failed to export selected statements. Please contact support if the issue persists."
        )


@router.post("/export-all")
async def export_all_statements(
    request: MonthlyStatementExportAllRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Export all filtered Monthly Statement data to Excel with optional exclusions.
    
    **Summary:**
        Exports invoice data from monthly statements with comprehensive filtering.
        Supports excluding specific invoice IDs. Each supplier gets its own sheet.
        
    **Request Body:**
        - **request** (`MonthlyStatementExportAllRequest`, required):
            - **from_date** (`date`): Start date for the date range (YYYY-MM-DD)
            - **to_date** (`date`): End date for the date range (YYYY-MM-DD)
            - **supplier_names** (`List[str]`, optional): List of supplier names, ['All'] for all suppliers
            - **status** (`str`, optional): Invoice status filter - 'Processed', 'Failed', 'Unlisted', 'Missing System', 'Missing Statement', or 'All'
            - **excluded_invoice_ids** (`List[str]`, optional): IDs to exclude from export. Supports three types: UUIDs (Invoice table), integer invoice_ids (plumbing_invoices), integer item IDs (invoice_items). The system intelligently detects and handles all types.
            
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **str**: Presigned S3 URL for downloading the Excel file
        
    **Response Example:**
    ```json
    "https://s3.amazonaws.com/bucket/Exports/MonthlyStatement_2025-01_AllSuppliers.xlsx?AWSAccessKeyId=..."
    ```
    
    **Excel File Structure:**
        - Each supplier gets its own sheet
        - Sheet name = Supplier name (max 31 chars)
        - Sheets sorted alphabetically by supplier name
        - Data within each sheet sorted by Invoice Date (ascending)
        
    **Columns (in order):**
        1. Invoice Number
        2. Invoice Date (YYYY-MM-DD)
        3. Statement Date (YYYY-MM-DD)
        4. Supplier Name
        5. Status (Processed/Failed)
        6. Original Amount (currency)
        7. Balance (currency)
        
    **File Naming:**
        - Single supplier: `MonthlyStatement_{YYYY-MM}_{SupplierName}.xlsx`
        - Multiple/All suppliers: `MonthlyStatement_{YYYY-MM}_AllSuppliers.xlsx`
        
    **Request Examples:**
    ```json
    // Single supplier with status filter
    {
      "from_date": "2025-01-01",
      "to_date": "2025-01-31",
      "supplier_names": ["BMW Plumbing Supplies"],
      "status": "Processed"
    }
    
    // All suppliers with exclusions
    {
      "from_date": "2025-01-01",
      "to_date": "2025-01-31",
      "supplier_names": ["All"],
      "status": "All",
      "excluded_invoice_ids": [123, 456, 789]
    }
    ```
        
    **Error Codes:**
        - **404**: No invoice data found for the specified filters
        - **500**: Export processing error
        
    **Notes:**
        - Follows current filters (month/date, suppliers, status)
        - Excluded invoices are removed from the export
        - Returns S3 presigned URL for download
    """
    try:
        import time
        start_time = time.time()
        
        controller = StatementController(db)
        download_url = controller.export_monthly_statement(
            from_date=request.from_date,
            to_date=request.to_date,
            supplier_names=request.supplier_names,
            status=request.status,
            excluded_invoice_ids=request.excluded_invoice_ids
        )
        
        processing_time = time.time() - start_time
        logger.info(f"Monthly statement export completed in {processing_time:.2f} seconds")
        
        return download_url
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Monthly statement export error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail="Failed to export monthly statement. Please contact support if the issue persists."
        )