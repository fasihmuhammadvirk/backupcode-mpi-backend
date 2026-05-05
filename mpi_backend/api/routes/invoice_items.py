import json
import time
import uuid
from typing import Optional, List
from uuid import UUID
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from datetime import datetime
from fastapi_pagination import paginate
from datetime import date

from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.controllers.ExportController import ExportController
from mpi_backend.database.schemas import (
    UpdateInvoiceItemRequest,
    UpdateInvoiceItemColumnsRequest,
    ExportToExcelFilterRequest,
    AggregateExportRequest,
)
from mpi_backend.database.schemas.Filters import OrderByFilter, FilterRequest
from mpi_backend.database.models.User import User
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.utils.auth.schema_selector import get_invoice_item_schema
from mpi_backend.utils.export_utils import (
    convert_items_to_dataframe,
    DISPLAY_FIELD_TO_COLUMN_MAP,
    export_items_generic,
    convert_mart_items_to_dataframe,
    AGGREGATE_EXPORT_SYNC_MAX_IDS,
)
from mpi_backend.database.dao.invoice_item_mart.utils import check_mart_table_exists
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data
from mpi_backend.utils.s3_utils import upload_export_and_get_url
from mpi_backend.database.schemas.InvoiceItems import ToggleVisibilityRequest
from mpi_backend.database.dao.invoice_item_mart.get_by_ids import get_by_ids


from .invoice_items_search import router as search_router

# Initialize logger at module level
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoice-items",tags=["Invoice Items"])

router.include_router(search_router)


@router.get("/all")
def get_invoices(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Get all invoice items with pagination.

    **Summary:**
        Retrieves all invoice items from the database with automatic pagination.
        This endpoint provides access to all invoice line items across all
        invoices and suppliers.

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **Page[InvoiceItems]**: Paginated response containing invoice item objects
        - Fields returned vary by user role (admin/bookkeeping see all fields, standard users see limited fields)

    **Response Example:**
    ```json
    {
        "items": [
            {
                "id": 123,
                "invoice_id": "uuid-here",
                "item": "ABC123",
                "description": "Pipe Fitting 3/4 inch",
                "qty": 10,
                "cost": 15.50,
                "amount": 155.00,
                "date": "2024-01-15",
                "vendor": "BMW Plumbing",
                "customer_job": "Project Alpha"
            }
        ],
        "total": 1500,
        "page": 1,
        "size": 10,
        "pages": 150
    }
    ```

    **Pagination:**
        - Automatic pagination applied
        - Default page size determined by fastapi-pagination
        - Page numbers are 1-based

    **Error Codes:**
        - **404**: No invoice items found in the database

    **Notes:**
        - Returns all invoice items regardless of invoice or supplier
        - Only returns active (visible) invoice items
        - Results are ordered by most recent first
        - Large datasets may require multiple page requests
        - Response fields are filtered based on user role for security
    """
    try:
        invoice_items = InvoiceItemController(db).get_invoice_items()

        # Apply role-based schema filtering
        ItemSchema = get_invoice_item_schema(current_user)
        filtered_items = [ItemSchema.model_validate(item) for item in invoice_items]

        return paginate(filtered_items)

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No Records Found!")


@router.get("/id")
def get_invoices_by_id(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
        invoice_id: Optional[UUID] = Query(None, description="Filter by invoice_id")
):
    """
    Get invoice items filtered by specific invoice ID.

    **Summary:**
        Retrieves all invoice items associated with a specific invoice ID.
        This endpoint allows filtering invoice items by their parent invoice,
        providing a way to view all line items for a particular invoice.

    **Query Parameters:**
        - **invoice_id** (`UUID`, optional): The invoice ID to filter by

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **Page[InvoiceItems]**: Paginated response containing invoice item objects
        - Fields returned vary by user role (admin/bookkeeping see all fields, standard users see limited fields)

    **Response Example:**
    ```json
    {
        "items": [
            {
                "id": 123,
                "invoice_id": "550e8400-e29b-41d4-a716-446655440000",
                "item": "ABC123",
                "description": "Pipe Fitting 3/4 inch",
                "qty": 10,
                "cost": 15.50,
                "amount": 155.00,
                "date": "2024-01-15",
                "vendor": "BMW Plumbing"
            }
        ],
        "total": 25,
        "page": 1,
        "size": 10,
        "pages": 3
    }
    ```

    **Filtering Behavior:**
        - If invoice_id is provided: Returns only items for that invoice
        - If invoice_id is null/empty: Returns all invoice items (same as /all)

    **Pagination:**
        - Automatic pagination applied
        - Page size determined by fastapi-pagination
        - Page numbers are 1-based

    **Error Codes:**
        - **404**: No invoice items found for the specified invoice ID

    **Notes:**
        - UUID format required for invoice_id parameter
        - Only returns active (visible) invoice items
        - Results are ordered by most recent first
        - Useful for viewing complete invoice details
        - Response fields are filtered based on user role for security
    """
    try:
        invoice_items = InvoiceItemController(db).get_invoice_items(invoice_id=invoice_id)

        # Apply role-based schema filtering
        ItemSchema = get_invoice_item_schema(current_user)
        filtered_items = [ItemSchema.model_validate(item) for item in invoice_items]

        return paginate(filtered_items)

    except Exception as e:
        raise HTTPException(status_code=404, detail="No Records Found!")


@router.get("/supplier-date")
def get_invoices_by_supplier_date(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
        supplier_name: List[str] = Query(None),
        from_date: date = Query(None),
        to_date: date = Query(None),
        job_location: str = Query(None),
        export_status: str = Query(None),
        page: int = Query(1, ge=1),
        size: int = Query(10)
):
    """
    Get invoice items with advanced filtering by supplier, date range, and other criteria.
    
    **Summary:**
        Retrieves invoice items with comprehensive filtering capabilities including
        supplier names, date ranges, job locations, and export status. This endpoint
        provides flexible querying for invoice line items with pagination support.
        
    **Query Parameters:**
        - **supplier_name** (`List[str]`, optional): List of supplier names to filter by
        - **from_date** (`date`, optional): Start date for filtering (YYYY-MM-DD)
        - **to_date** (`date`, optional): End date for filtering (YYYY-MM-DD)
        - **job_location** (`str`, optional): Customer job location filter
        - **export_status** (`str`, optional): Export status filter
        - **page** (`int`, default=1): Page number for pagination (1-based)
        - **size** (`int`, default=10): Number of items per page
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **PaginatedInvoiceItemsResponse**: Paginated response containing:
            - **items** (`List[InvoiceItems]`): Array of invoice item objects
            - **total** (`int`): Total number of items matching filters
            - **page** (`int`): Current page number
            - **size** (`int`): Items per page
            - **pages** (`int`): Total number of pages
            
    **Response Example:**
    ```json
    {
        "items": [
            {
                "id": 123,
                "invoice_id": "uuid-here",
                "item": "ABC123",
                "description": "Pipe Fitting 3/4 inch",
                "qty": 10,
                "cost": 15.50,
                "amount": 155.00,
                "date": "2024-01-15",
                "vendor": "BMW Plumbing",
                "customer_job": "Project Alpha",
                "export_status": "exported"
            }
        ],
        "total": 250,
        "page": 1,
        "size": 10,
        "pages": 25
    }
    ```
    
    **Filter Combinations:**
        - Multiple filters can be combined for precise searching
        - Date range filtering supports both start and end dates
        - Supplier filtering supports multiple supplier names
        - All filters are optional and can be used independently
        
    **Error Codes:**
        - **404**: No invoice items found matching the filter criteria
        
    **Notes:**
        - All date filters use YYYY-MM-DD format
        - Pagination is 1-based (page 1 is the first page)
        - Results are ordered by most recent first
        - Only returns active (visible) invoice items
        - Empty filters return all invoice items (subject to pagination)
    """
    try:
        invoice_items_dict = InvoiceItemController(db).get_invoice_items_by_filters(supplier=supplier_name,
                                                                               from_date=from_date,
                                                                               to_date=to_date,
                                                                               job_location=job_location,
                                                                               export_status=export_status,
                                                                               page=page, page_size=size)

        # Apply role-based schema filtering to items in the response dict
        ItemSchema = get_invoice_item_schema(current_user)
        if 'items' in invoice_items_dict and invoice_items_dict['items']:
            invoice_items_dict['items'] = [
                ItemSchema.model_validate(item) for item in invoice_items_dict['items']
            ]

        return invoice_items_dict

    except Exception as e:
        raise HTTPException(status_code=404, detail="No Records Found!")



@router.put("/update")
def update_invoice_items(items: List[UpdateInvoiceItemRequest], db: Session = Depends(get_db)):
    """
    Update multiple invoice items synchronously with proper null handling.
    
    **Summary:**
        Updates multiple invoice items in batch with synchronous processing.
        This endpoint handles bulk updates to invoice line items with proper
        null value handling and immediate database commits.
        
    **Request Body:**
        - **items** (`List[UpdateInvoiceItemRequest]`, required): Array of invoice items to update
        
    **Authentication:**
        - No authentication required (may need to be added based on requirements)
        
    **Returns:**
        - **Dict**: Update confirmation message with count:
            - **status** (`str`): Success message confirming updates
            - **updated_count** (`int`): Number of items successfully updated
            
    **Response Example:**
    ```json
    {
        "status": "invoices updated successfully",
        "updated_count": 150
    }
    ```
    
    **Update Process:**
        1. Preprocesses items to handle null values properly
        2. Converts null account fields to empty strings
        3. Processes updates in batches of 100 items
        4. Commits changes immediately to database
        5. Returns count of successfully updated items
        
    **Null Value Handling:**
        - **account**: null, "null", "None", "" → "" (empty string)
        - **is_active**: null → True (default active)
        - **numeric fields**: null → None (preserved as null)
        
    **Batch Processing:**
        - Processes items in batches of 100 for performance
        - Commits each batch separately to prevent timeouts
        - Handles large payloads efficiently
        
    **Error Handling:**
        - Updates are processed in transaction
        - Rollback on errors to maintain data integrity
        - Detailed logging for debugging
        
    **Notes:**
        - Synchronous processing for immediate feedback
        - Proper null handling for all field types
        - Batch processing for large datasets
        - No mapping creation for UIDI items
    """
    try:
        logger.info(f"PUT /invoice-items/update endpoint called with {len(items)} items")
        
        # Convert to dict format - schema handles null values automatically
        processed_items = [item.model_dump() for item in items]
        
        # Use the synchronous update method
        controller = InvoiceItemController(db)
        updated_count = controller.update_invoice_items_sync(processed_items)
        
        logger.info(f"Successfully updated {updated_count} items")
        return {
            "status": "invoices updated successfully",
            "updated_count": updated_count
        }
        
    except Exception as e:
        logger.error(f"Error in update endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@router.put("/update-columns")
def update_invoice_item_columns(
    request: UpdateInvoiceItemColumnsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update columns of a single invoice item.
    
    **Summary:**
        Updates multiple columns for a specific invoice item row.
        This allows you to update one or more fields for a single line item.
        
    **Request Body:**
        - **id** (`int`, required): The invoice item ID to update
        - **updates** (`Dict[str, any]`, required): Column names and values to update
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Update confirmation with:
            - **status** (`str`): Success message
            - **updated_count** (`int`): Number of items updated (always 1)
            - **updated_fields** (`List[str]`): List of field names that were updated
            
    **Response Example:**
    ```json
    {
        "status": "Invoice item updated successfully",
        "updated_count": 1,
        "updated_fields": ["memo", "export_status"]
    }
    ```
    
    **Updatable Columns:**
        filename, sheet_name, mpi_item, mpi_description, item, description,
        qty, cost, amount, date, ref_no, po_number, customer_job, bill,
        vendor, class_, account, memo, buyer, date_added, is_active
        
    **Request Examples:**
    
    Update single column:
    ```json
    {
        "id": 123,
        "updates": {
            "export_status": "Exported"
        }
    }
    ```
    
    Update multiple columns:
    ```json
    {
        "id": 123,
        "updates": {
            "memo": "Updated memo",
            "export_status": "Exported",
            "customer_job": "Project Alpha"
        }
    }
    ```
    
    **Error Codes:**
        - **400**: Invalid request format or column names
        - **403**: Insufficient permissions (e.g., updating account column without bookkeeping/admin role)
        - **404**: Invoice item with specified id not found
        - **500**: Database error during update
        
    **Notes:**
        - Column names are case-sensitive
        - Use 'class_' for the class column
        - Updating 'account' column requires bookkeeping or admin role
        - The update is performed in a single transaction
        - Transaction rollback occurs on any failure to maintain data integrity
    """
    from mpi_backend.utils.auth.roles import UserRole

    # Determine restricted columns based on user role
    # Standard users cannot update account column
    restricted_columns = []
    if current_user.role == UserRole.STANDARD.value:
        restricted_columns.append('account')
    
    # Call controller to handle the business logic
    controller = InvoiceItemController(db)
    result = controller.update_invoice_item_columns(
        item_id=request.id,
        updates=request.updates,
        restricted_columns=restricted_columns
    )
    
    # Return success response
    return {
        "status": "Invoice item updated successfully",
        **result
    }


@router.put("/toggle-visibility", status_code=200)
def toggle_visibility(
    request: ToggleVisibilityRequest,
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Toggle visibility of multiple invoice items.
    
    **Summary:**
        Changes the visibility status of multiple invoice items by setting their
        active/inactive status. This allows hiding or showing invoice items
        without permanently deleting them from the database.
        
    **Request Body:**
        - **request** (`ToggleVisibilityRequest`): Object containing:
            - **ids** (`List[int]`, required): Array of invoice item IDs to update
            - **make_visible** (`bool`, required): Whether to make items visible (true) or hidden (false)
            
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Update confirmation message:
            - **status** (`str`): Success message with count of updated items
            
    **Response Example:**
    ```json
    {
        "status": "Updated visibility for 15 items"
    }
    ```
    
    **Visibility States:**
        - **make_visible: true**: Sets items as active/visible
        - **make_visible: false**: Sets items as inactive/hidden
        
    **Update Process:**
        1. Validates all invoice item IDs exist
        2. Updates visibility status in batch
        3. Returns count of successfully updated items
        4. Maintains data integrity
        
    **Error Handling:**
        - Invalid IDs are ignored (not counted in result)
        - Returns count of successfully updated items only
        - Database transaction ensures consistency
        
    **Notes:**
        - Hidden items are not returned by default query endpoints
        - Items can be restored by setting make_visible to true
        - Batch operation for multiple items
        - No permanent data loss (soft delete approach)
        - Use /hidden-items endpoint to view hidden items
    """
    controller = InvoiceItemController(db)
    updated_count = controller.toggle_visibility(request.ids, request.make_visible)
    return {"status": f"Updated visibility for {updated_count} items"}


@router.get("/hidden-items")
def get_hidden_items(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all hidden (inactive) invoice items with pagination.

    **Summary:**
        Retrieves all invoice items that have been marked as hidden/inactive.
        This endpoint provides access to invoice items that are not visible
        in the standard query endpoints but still exist in the database.

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **Page[InvoiceItems]**: Paginated response containing hidden invoice item objects
        - Fields returned vary by user role (admin/bookkeeping see all fields, standard users see limited fields)

    **Response Example:**
    ```json
    {
        "items": [
            {
                "id": 123,
                "invoice_id": "uuid-here",
                "item": "ABC123",
                "description": "Pipe Fitting 3/4 inch",
                "qty": 10,
                "cost": 15.50,
                "amount": 155.00,
                "date": "2024-01-15",
                "vendor": "BMW Plumbing",
                "is_active": false
            }
        ],
        "total": 50,
        "page": 1,
        "size": 10,
        "pages": 5
    }
    ```

    **Hidden Items:**
        - Items with is_active = false
        - Not returned by standard query endpoints
        - Can be restored using toggle-visibility endpoint
        - Maintained for audit and recovery purposes

    **Pagination:**
        - Automatic pagination applied
        - Page size determined by fastapi-pagination
        - Page numbers are 1-based

    **Use Cases:**
        - Audit trail and data recovery
        - Reviewing hidden items before permanent deletion
        - Restoring accidentally hidden items
        - Data cleanup and maintenance

    **Notes:**
        - Only returns items with is_active = false
        - Results are ordered by most recent first
        - Use toggle-visibility endpoint to restore items
        - Hidden items maintain all original data
        - Response fields are filtered based on user role for security
    """
    controller = InvoiceItemController(db)
    hidden_items = controller.get_hidden_items()

    # Apply role-based schema filtering
    ItemSchema = get_invoice_item_schema(current_user)
    filtered_items = [ItemSchema.model_validate(item) for item in hidden_items]

    return paginate(filtered_items)

@router.get("/count")
def count_invoice_items(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Get total count of active invoice items.
    
    **Summary:**
        Returns the total number of active (visible) invoice items in the
        database. This endpoint provides a quick way to get the count of
        all invoice line items without retrieving the actual data.
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **Dict**: Count information:
            - **count** (`int`): Total number of active invoice items
            
    **Response Example:**
    ```json
    {
        "count": 15420
    }
    ```
    
    **Count Details:**
        - Only includes active (is_active = true) invoice items
        - Excludes hidden/inactive items
        - Counts all invoice items across all invoices and suppliers
        - Real-time count from database
        
    **Performance:**
        - Optimized database query for counting
        - No data retrieval, only count calculation
        - Fast response time even with large datasets
        
    **Use Cases:**
        - Dashboard statistics and metrics
        - Data validation and verification
        - Performance monitoring
        - System health checks
        
    **Notes:**
        - Count includes only visible/active items
        - Hidden items are not included in count
        - Count is calculated in real-time
        - Useful for monitoring system data volume
    """
    no_of_line_items = InvoiceItemController(db).count_line_items()
    return {"count": no_of_line_items}

@router.get("/sort")
def sort_invoices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    column_name: str = Query(None),
    sort_order: str = Query('ascending', description="Sort By (ascending, descending)")
):
    """
    Sort invoice items by specified column with pagination.
    
    **Summary:**
        Retrieves and sorts invoice items by a specified column in either
        ascending or descending order. This endpoint provides flexible sorting
        capabilities for invoice line items with automatic pagination.
        
    **Query Parameters:**
        - **column_name** (`str`, required): Column to sort by:
            - 'File Name': Sort by filename
            - 'Sheet Name': Sort by sheet name
            - 'Item': Sort by item code
            - 'Description': Sort by item description
            - 'Quantity': Sort by quantity
            - 'Cost': Sort by unit cost
            - 'Amount': Sort by total amount
            - 'Date': Sort by invoice date
            - 'Ref No': Sort by reference number
            - 'PO #': Sort by purchase order number
            - 'Customer Job': Sort by customer job location
            - 'Bill': Sort by bill information
            - 'Vendor': Sort by vendor/supplier name
            - 'Class': Sort by class information
            - 'Memo': Sort by memo field
            - 'Buyer': Sort by buyer information
            - 'Date Added': Sort by date added to system
            - 'MPI Item': Sort by MPI item code
            - 'MPI Description': Sort by MPI description
        - **sort_order** (`str`, default='ascending'): Sort direction:
            - 'ascending': A to Z, lowest to highest, oldest to newest
            - 'descending': Z to A, highest to lowest, newest to oldest
            
    **Returns:**
        - **Page[InvoiceItems]**: Paginated response containing sorted invoice item objects
        
    **Response Example:**
    ```json
    {
        "items": [
            {
                "id": 123,
                "invoice_id": "uuid-here",
                "item": "ABC123",
                "description": "Pipe Fitting 3/4 inch",
                "qty": 10,
                "cost": 15.50,
                "amount": 155.00,
                "date": "2024-01-15",
                "vendor": "BMW Plumbing"
            }
        ],
        "total": 1500,
        "page": 1,
        "size": 10,
        "pages": 150
    }
    ```
    
    **Supported Sort Columns:**
        - **Text Fields**: File Name, Sheet Name, Item, Description, etc.
        - **Numeric Fields**: Quantity, Cost, Amount
        - **Date Fields**: Date, Date Added
        - **Reference Fields**: Ref No, PO #, Customer Job
        
    **Error Codes:**
        - **400**: Invalid column name specified
        
    **Notes:**
        - Automatic pagination is applied to results
        - Sort order affects all paginated pages consistently
        - Column names are case-sensitive and must match exactly
        - Default sort order is ascending if not specified
        - Results maintain sort order across all pages
        - Only active (visible) invoice items are included
    """
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
        "Account": "account",
        "Memo": "memo",
        "Buyer": "buyer",
        "Date Added": "date_added",
        "Original Item": "mpi_item", # will be removed adding beacuse of incorect naming on frontend
        "Original Description": "mpi_description", # will be removed adding beacuse of incorect naming on frontend
        "Date Added": "date_added",
        "MPI Item": "mpi_item",
        "MPI Description": "mpi_description",
    }

    if column_name not in column_mapping:
        raise HTTPException(status_code=400, detail="Invalid column name")

    column = column_mapping.get(column_name, 'date')

    invoice_items = InvoiceItemController(db).sort(db, column, sort_order)

    # Apply role-based schema filtering
    ItemSchema = get_invoice_item_schema(current_user)
    filtered_items = [ItemSchema.model_validate(item) for item in invoice_items]

    return paginate(filtered_items)

@router.post("/export")
def export_invoices(
        ids: List[str],
        columns: Optional[List[str]] = None,
        order_by: Optional[List[OrderByFilter]] = None,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Export selected invoice items to Excel with automatic performance optimization.
    
    **Summary:**
        Exports specific invoice items to an Excel file with automatic performance
        optimization. The system automatically chooses the best export method based
        on data size and configuration settings.
        
    **Request Body:**
        - **ids** (`List[int]`, required): Array of invoice item IDs to export
        - **columns** (`List[str]`, optional): Specific columns to include in export
        - **order_by** (`List[OrderByFilter]`, optional): Sorting criteria for export
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **str**: Presigned S3 URL for downloading the Excel file
        
    **Response Example:**
    ```json
    "https://s3.amazonaws.com/bucket/Exports/2024-12-19_14-30-25.xlsx?AWSAccessKeyId=..."
    ```
    
    **Performance Optimization:**
        - **Standard Method**: For small exports (< 100 records) or when optimization disabled
        - **Optimized Method**: For medium exports (100+ records) with enhanced performance
        - **Batch Method**: For large exports with configurable batch processing
        
    **Export Process:**
        1. Validates invoice item IDs
        2. Chooses optimal export method based on record count
        3. Retrieves data with specified columns and ordering
        4. Converts to Excel format with performance optimization
        5. Uploads file to S3 storage
        6. Returns presigned download URL
        
    **Column Selection:**
        - If columns specified: Uses only requested columns
        - If no columns specified: Uses default columns:
            - Item, Description, Qty, Cost, Amount, Date, Ref NO, PO #, Customer Job, Bill, Vendor, Class, Memo
        
    **Error Codes:**
        - **404**: No data found for export
        - **500**: Export processing error
        
    **Performance Features:**
        - Automatic method selection based on data size
        - Batch processing for large datasets
        - Optimized database queries
        - Fast Excel generation for large exports
        
    **Notes:**
        - File is stored in S3 with timestamp for uniqueness
        - Presigned URL has limited expiration time
        - Performance optimization is automatic and transparent
        - Supports custom column selection and ordering
        - File is automatically cleaned up by S3 lifecycle policies
    """
    logger.info(f"Exporting {ids, columns, order_by}")

    # Convert the display columns to database columns
    db_columns = None
    if columns:
        db_columns = [DISPLAY_FIELD_TO_COLUMN_MAP[c] for c in columns if c in DISPLAY_FIELD_TO_COLUMN_MAP]

    try:
        items = get_by_ids(db, ids, db_columns, order_by)
    except Exception:
        # Defensive: get_by_ids already swallows + rolls back internally,
        # but if anything escapes we still don't want a poisoned session.
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception("Export: mart get_by_ids raised unexpectedly")
        raise HTTPException(status_code=500, detail="Export failed: could not fetch items")

    # The legacy invoice_items table cannot serve as a fallback: its `id` column
    # is int4 (max ~2.1B), but mart invoice_items_id values are 18+ digit hashes
    # since the new normalized extraction pipeline (2026-01-21). Querying the
    # legacy table with these IDs causes an integer overflow and leaves the
    # transaction in a failed state (psycopg2 InFailedSqlTransaction).
    if items is None:
        logger.error("Export: mart get_by_ids returned None; aborting")
        raise HTTPException(status_code=500, detail="Export failed: items unavailable")

    try:
        return export_items_generic(items, columns)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Export error")
        raise HTTPException(status_code=500, detail="Export failed")


def process_export_in_background(export_id: str, ids: List[str], columns: Optional[List[str]], order_by: Optional[List[OrderByFilter]]):
    """
    Background task to process large exports without blocking the request.
    Updates status file with progress and final download URL.
    """
    from mpi_backend.database import SessionLocal
    
    export_status_file = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/status_{export_id}.json'
    start_time = time.time()
    
    try:
        # Create new database session for background task
        db = SessionLocal()
        
        # Update status to processing
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'processing',
                'export_id': export_id,
                'record_count': len(ids),
                'started_at': datetime.now().isoformat(),
                'message': 'Export is being processed'
            }, f)
        
        db_columns = None
        if columns:
            db_columns = [DISPLAY_FIELD_TO_COLUMN_MAP[c] for c in columns if c in DISPLAY_FIELD_TO_COLUMN_MAP]
        items = get_by_ids(db, ids, db_columns, order_by)

        # The legacy invoice_items table cannot serve as a fallback: its `id` column
        # is int4 but mart invoice_items_id values are 18+ digit hashes. See the
        # synchronous /export endpoint for full context.
        if items is None:
            raise Exception("Export failed: items unavailable from mart")

        items_df = convert_mart_items_to_dataframe(items, columns)

        if items_df.empty:
            raise Exception("No data found for export")
        
        # Handle column selection
        if columns and not items_df.empty:
            available_columns = [col for col in columns if col in items_df.columns]
            if available_columns:
                items_df = items_df[available_columns]
        else:
            default_columns = ["Item","Description","Qty","Cost","Amount","Date","Ref NO","PO #","Customer Job","Bill","Vendor","Class","Memo"]
            available_columns = [col for col in default_columns if col in items_df.columns]
            items_df = items_df[available_columns]
        
        # Prepare file paths
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
        filename = f'{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.xlsx'
        file_path = f'{upload_folder}{filename}'
        
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        # Save Excel file
        from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data_fast
        save_final_data_fast(items_df, file_path)
        
        processing_time = time.time() - start_time
        print(f"Background export completed in {processing_time:.2f} seconds for {len(items_df)} items")
        
        download_url = upload_export_and_get_url(file_path)

        # Update status to completed
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'completed',
                'export_id': export_id,
                'record_count': len(ids),
                'started_at': datetime.now().isoformat(),
                'completed_at': datetime.now().isoformat(),
                'download_url': download_url,
                'processing_time': f"{processing_time:.2f}s",
                'message': 'Export completed successfully'
            }, f)

        db.close()

    except Exception as e:
        logger.exception(f"Background export error")
        # Update status to failed
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'failed',
                'export_id': export_id,
                'error': str(e),
                'message': 'Export failed'
            }, f)


def process_aggregate_export_in_background(
    export_id: str,
    aggregate_request_dict: dict,
    all_filtered_rows_selected: bool,
    record_count: int,
):
    """
    Large selection aggregate export or full-filter aggregate export (always async for the latter).

    Uses the same status file + GET /export-status/{export_id} contract as other Excel exports.
    """
    from mpi_backend.database import SessionLocal

    export_status_file = f"{INVOICE_DOWNLOAD_FOLDER}/Exports/status_{export_id}.json"
    start_time = time.time()
    started_at_iso = datetime.now().isoformat()
    db = SessionLocal()
    try:
        with open(export_status_file, "w") as f:
            json.dump(
                {
                    "status": "processing",
                    "export_id": export_id,
                    "record_count": record_count,
                    "started_at": started_at_iso,
                    "message": "Aggregate export is being processed",
                },
                f,
            )
  
        req = AggregateExportRequest.model_validate(aggregate_request_dict)
        controller = ExportController()
        if all_filtered_rows_selected:
            download_url = controller.run_aggregate_export_for_filtered(
                db, req.to_filter_request(), req.excluded_rows_ids
            )
        else:
            download_url = controller.run_aggregate_export_for_ids(db, req.ids or [])

        processing_time = time.time() - start_time
        with open(export_status_file, "w") as f:
            json.dump(
                {
                    "status": "completed",
                    "export_id": export_id,
                    "record_count": record_count,
                    "started_at": started_at_iso,
                    "completed_at": datetime.now().isoformat(),
                    "download_url": download_url,
                    "processing_time": f"{processing_time:.2f}s",
                    "message": "Export completed successfully",
                },
                f,
            )
    except Exception as e:
        logger.exception("Background aggregate export error")
        with open(export_status_file, "w") as f:
            json.dump(
                {
                    "status": "failed",
                    "export_id": export_id,
                    "error": "Aggregate export failed. Please try again.",
                    "message": "Aggregate export failed",
                },
                f,
            )
    finally:
        db.close()


@router.get("/export-status/{export_id}")
def get_export_status(export_id: str, token: str = Depends(JWTBearer())):
    """
    Get the status of an export job.
    
    **Summary:**
        Check the status of a background export job and get the download URL when completed.
        
    **Path Parameters:**
        - **export_id** (`str`, required): The export ID returned from /export-all
        
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **dict**: Status information including:
            - **status** (`str`): 'processing', 'completed', or 'failed'
            - **export_id** (`str`): The export ID
            - **download_url** (`str`, optional): S3 download URL (only when completed)
            - **message** (`str`): Status message
            
    **Response Examples:**
    
    Processing:
    ```json
    {
      "status": "processing",
      "export_id": "abc123",
      "record_count": 75332,
      "message": "Export is being processed"
    }
    ```
    
    Completed:
    ```json
    {
      "status": "completed",
      "export_id": "abc123",
      "record_count": 75332,
      "download_url": "https://s3.amazonaws.com/...",
      "processing_time": "17.43s",
      "message": "Export completed successfully"
    }
    ```
    
    Failed:
    ```json
    {
      "status": "failed",
      "export_id": "abc123",
      "error": "Error message",
      "message": "Export failed"
    }
    ```
    """
    
    export_status_file = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/status_{export_id}.json'
    
    if not os.path.exists(export_status_file):
        raise HTTPException(status_code=404, detail="Export ID not found")
    
    try:
        with open(export_status_file, 'r') as f:
            status_data = json.load(f)
        return status_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading export status: {str(e)}")


@router.post("/export-all")
def export_all_invoices(
        request: ExportToExcelFilterRequest,
        background_tasks: BackgroundTasks,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Export all filtered invoice items to Excel with automatic performance optimization.
    
    **Summary:**
        Exports all invoice items matching the specified filter criteria to an Excel
        file. This endpoint applies filters to get the complete dataset and then
        uses the optimized export functionality for large datasets.
        
    **Request Body:**
        - **request** (`ExportToExcelFilterRequest`): Filter criteria and export options:
            - Filter parameters (supplier, date range, status, etc.)
            - **columns** (`List[str]`, optional): Specific columns to include
            - **order_by** (`List[OrderByFilter]`, optional): Sorting criteria
            - **excluded_rows_ids** (`List[int]`, optional): IDs to exclude from export
            
    **Authentication:**
        - Requires valid JWT token in Authorization header
        
    **Returns:**
        - **str**: Presigned S3 URL for downloading the Excel file
        
    **Response Example:**
    ```json
    "https://s3.amazonaws.com/bucket/Exports/2024-12-19_14-30-25.xlsx?AWSAccessKeyId=..."
    ```
    
    **Export Process:**
        1. Applies filter criteria to get matching invoice item IDs
        2. Excludes specified row IDs if provided
        3. Uses optimized export method for large datasets
        4. Generates Excel file with selected columns and ordering
        5. Uploads to S3 and returns download URL
        
    **Filter Support:**
        - All standard invoice item filters supported
        - Date range filtering
        - Supplier filtering
        - Status and export status filtering
        - Job location filtering
        
    **Performance Features:**
        - Efficient ID retrieval using filter optimization
        - Automatic performance method selection
        - Batch processing for large datasets
        - Optimized database queries
        
    **Error Codes:**
        - **404**: No items found matching the filters
        - **500**: Export processing error
        
    **Notes:**
        - Supports exclusion of specific rows from export
        - Uses same performance optimization as /export endpoint
        - File is stored in S3 with timestamp for uniqueness
        - Presigned URL has limited expiration time
        - Suitable for exporting large filtered datasets
        - Automatic cleanup by S3 lifecycle policies
    """
    logger.info(f"Exporting all but excluding {request.excluded_rows_ids}")
    try:
        start_time = time.time()
        
        # Get filtered IDs efficiently (maintains order from apply_filters)
        filter_request = FilterRequest(
            filters=request.filters,
            comparison_filters=request.comparison_filters,
            order_by=request.order_by,
            color_filters=request.color_filters,
            search=request.search,
            substring_search=request.substring_search
        )
        result = InvoiceItemController(db).apply_filters(filter_request)
        
        # TODO: apply_filters returns all of the data. When exporting, we should create a query and return
        # a database cursor then pass that cursor into the excel exporter.
        # Only getting the ids here to maintain backwards compatibility
        # Remove excluded IDs while preserving order. IDs are kept as strings to avoid
        # JS precision loss and to bind cleanly into the mart's NUMERIC[] (mart IDs
        # exceed bigint range since the new normalized extraction pipeline).
        ids = [str(item['id']) for item in result['items']]
        if request.excluded_rows_ids:
            excluded_set = {str(x) for x in request.excluded_rows_ids}
            ids = [str(item['id']) for item in result['items'] if str(item['id']) not in excluded_set]
        
        if not ids:
            raise HTTPException(status_code=404, detail="No items found matching the filters")
        
        filter_time = time.time() - start_time
        logger.info(f"Filter processing took {filter_time:.2f} seconds, found {len(ids)} items")
        
        # For small exports (< 1000 records), process synchronously
        if len(ids) < 1000:
            result = export_invoices(
                ids=ids,
                columns=request.columns,
                order_by=request.order_by,
                current_user=current_user,
                db=db
            )
            return result
        
        # For large exports, use background task and return immediately
        # Generate a unique export ID
        export_id = str(uuid.uuid4())
        export_status_file = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/status_{export_id}.json'
        
        # Create status file indicating processing
        os.makedirs(f'{INVOICE_DOWNLOAD_FOLDER}/Exports/', exist_ok=True)
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'processing',
                'export_id': export_id,
                'record_count': len(ids),
                'started_at': datetime.now().isoformat(),
                'message': 'Export is being processed in the background'
            }, f)
        
        # Add background task
        background_tasks.add_task(
            process_export_in_background,
            export_id=export_id,
            ids=ids,
            columns=request.columns,
            order_by=request.order_by
        )
        
        # Return immediately with export ID and status endpoint
        return {
            "export_id": export_id,
            "status": "processing",
            "record_count": len(ids),
            "message": "Export is being processed. Use the export_id to check status.",
            "status_endpoint": f"/invoice-items/export-status/{export_id}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Export-all error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


def _start_aggregate_background_export(
    background_tasks: BackgroundTasks,
    payload: dict,
    record_count: int,
    all_filtered_rows_selected: bool,
) -> dict:
    """
    Helper to start a background aggregate export job.

    Generates a UUID export_id, creates the status file with 'processing' state,
    queues the background task, and returns the response dict.
    """
    export_id = str(uuid.uuid4())
    export_status_file = f"{INVOICE_DOWNLOAD_FOLDER}/Exports/status_{export_id}.json"
    os.makedirs(f"{INVOICE_DOWNLOAD_FOLDER}/Exports/", exist_ok=True)
    with open(export_status_file, "w") as f:
        json.dump(
            {
                "status": "processing",
                "export_id": export_id,
                "record_count": record_count,
                "started_at": datetime.now().isoformat(),
                "message": "Aggregate export is being processed in the background",
            },
            f,
        )
    background_tasks.add_task(
        process_aggregate_export_in_background,
        export_id=export_id,
        aggregate_request_dict=payload,
        all_filtered_rows_selected=all_filtered_rows_selected,
        record_count=record_count,
    )
    return {
        "export_id": export_id,
        "status": "processing",
        "record_count": record_count,
        "message": "Aggregate export is being processed. Use export_id to check status.",
        "status_endpoint": f"/invoice-items/export-status/{export_id}",
    }


@router.post("/export-aggregate")
def export_aggregate_invoices(
    request: AggregateExportRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Aggregate Excel export: one row per (sheet name, MPI item).

    - ``all_filtered_rows_selected=true``: same row scope as Data Review filters (and optional
      ``excluded_rows_ids``). Always runs in a background job; returns ``export_id`` for polling.
    - Otherwise: requires non-empty ``ids``. Under ``AGGREGATE_EXPORT_SYNC_MAX_IDS`` returns a
      presigned URL immediately; larger selections use the same background + polling flow.

    Mart-only (no ORM fallback). Matches override/void semantics of ``get_by_ids`` / ``apply_filters``.
    """
    logger.info(
        "Aggregate export: all_filtered=%s id_count=%s",
        request.all_filtered_rows_selected,
        len(request.ids or []),
    )

    if not check_mart_table_exists(db):
        raise HTTPException(
            status_code=503,
            detail="Mart data is unavailable; aggregate export cannot run.",
        )

    payload = request.model_dump()
    ids = list(request.ids) if request.ids else []

    # Full filtered dataset (Data Review "select all" semantics on the server).
    if request.all_filtered_rows_selected:
        return _start_aggregate_background_export(background_tasks, payload, 0, True)

    # Explicit row selection only.
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="Provide invoice item ids, or set all_filtered_rows_selected=true to export the full filtered result set.",
        )

    if len(ids) < AGGREGATE_EXPORT_SYNC_MAX_IDS:
        try:
            return ExportController().run_aggregate_export_for_ids(db, ids)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception:
            raise HTTPException(status_code=500, detail="Aggregate export failed.")

    return _start_aggregate_background_export(background_tasks, payload, len(ids), False)
