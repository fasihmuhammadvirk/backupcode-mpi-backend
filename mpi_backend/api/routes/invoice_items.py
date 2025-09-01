from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from mpi_backend.database import get_async_db
from datetime import datetime
from fastapi_pagination import Page, paginate
from datetime import date
import os
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.controllers.Invoice import InvoiceController
from mpi_backend.database.schemas import InvoiceItems, UpdateInvoiceItemRequest, PaginatedInvoiceItemsResponse, ExportToExcelFilterRequest
from mpi_backend.database.schemas.Filters import OrderByFilter
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.export_utils import convert_items_to_dataframe
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
from mpi_backend.database.schemas.InvoiceItems import ToggleVisibilityRequest
router = APIRouter(prefix="/invoice-items",tags=["Invoice Items"])


@router.get("/all", response_model=Page[InvoiceItems])
async def get_invoices(
        db: AsyncSession = Depends(get_async_db),
        token: str = Depends(JWTBearer())
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
    """
    try:
        invoice_items = await InvoiceItemController(db).get_invoice_items()

        return paginate(invoice_items)

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No Records Found!")


@router.get("/id", response_model=Page[InvoiceItems])
async def get_invoices(
        db: AsyncSession = Depends(get_async_db),
        invoice_id: Optional[UUID] = Query(None, description="Filter by invoice_id"),
        token: str = Depends(JWTBearer())
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
    """
    try:
        invoice_items = InvoiceItemController(db).get_invoice_items(invoice_id=invoice_id)
        return paginate(invoice_items)

    except Exception as e:
        raise HTTPException(status_code=404, detail="No Records Found!")


@router.get("/supplier-date", response_model=PaginatedInvoiceItemsResponse)
async def get_invoices(
        db: AsyncSession = Depends(get_async_db),
        supplier_name: List[str] = Query(None),
        from_date: date = Query(None),
        to_date: date = Query(None),
        job_location: str = Query(None),
        export_status: str = Query(None),
        page: int = Query(1, ge=1),
        size: int = Query(10),
        token: str = Depends(JWTBearer())
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
        invoice_items = await InvoiceItemController(db).get_invoice_items_by_filters(supplier=supplier_name,
                                                                               from_date=from_date,
                                                                               to_date=to_date,
                                                                               job_location=job_location,
                                                                               export_status=export_status,
                                                                               page=page, page_size=size)
        return invoice_items

    except Exception as e:
        raise HTTPException(status_code=404, detail="No Records Found!")


@router.put("/update")
async def update_invoice_items(items: List[UpdateInvoiceItemRequest], background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_async_db)):
    """
    Update multiple invoice items with background task processing.
    
    **Summary:**
        Updates multiple invoice items in batch with support for background
        task processing. This endpoint allows bulk updates to invoice line
        items and handles the updates asynchronously for better performance.
        
    **Request Body:**
        - **items** (`List[UpdateInvoiceItemRequest]`, required): Array of invoice items to update
        
    **Background Tasks:**
        - **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing
        
    **Authentication:**
        - No authentication required (may need to be added based on requirements)
        
    **Returns:**
        - **Dict**: Update confirmation message:
            - **status** (`str`): Success message confirming updates
            
    **Response Example:**
    ```json
    {
        "status": "invoices updated successfully"
    }
    ```
    
    **Update Process:**
        1. Validates all invoice item updates
        2. Processes updates in batch for efficiency
        3. Handles background tasks for async operations
        4. Returns immediate confirmation
        
    **Background Tasks:**
        - Updates are processed asynchronously
        - Non-blocking operation for better performance
        - Tasks continue processing after response is sent
        
    **Error Handling:**
        - Updates are processed in transaction
        - Partial failures may occur (consider adding error details)
        - Background tasks handle async operations
        
    **Notes:**
        - Batch processing for multiple items
        - Background task support for performance
        - Immediate response with async processing
        - Consider adding authentication if required
        - Updates are processed in database transaction
    """
    controller = InvoiceItemController(db)
    controller.update_invoice_items([item.dict() for item in items], background_tasks)
    return {"status": "invoices updated successfully"}


@router.put("/toggle-visibility", status_code=200)
async def toggle_visibility(
    request: ToggleVisibilityRequest,
    db: AsyncSession = Depends(get_async_db),
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
    updated_count = await controller.toggle_visibility(request.ids, request.make_visible)
    return {"status": f"Updated visibility for {updated_count} items"}


@router.get("/hidden-items", response_model=Page[InvoiceItems])
async def get_hidden_items(
    db: AsyncSession = Depends(get_async_db),
    token: str = Depends(JWTBearer())
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
    """
    controller = InvoiceItemController(db)
    return paginate(await controller.get_hidden_items())

@router.get("/count")
async def count_invoice_items(db: AsyncSession = Depends(get_async_db), token: str = Depends(JWTBearer())):
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
    no_of_line_items = await InvoiceItemController(db).count_line_items()
    return {"count": no_of_line_items}

@router.get("/sort", response_model=Page[InvoiceItems])
async def sort_invoices(db: AsyncSession = Depends(get_async_db), column_name: str = Query(None),
                   sort_order: str = Query('ascending', description="Sort By (ascending, descending)")):
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
        "ID": "id",
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
        "MPI Item": "mpi_item",
        "MPI Description": "mpi_description",
    }

    if column_name not in column_mapping:
        raise HTTPException(status_code=400, detail="Invalid column name")

    column = column_mapping.get(column_name, 'date')

    invoice_items = await InvoiceItemController(db).sort(db, column, sort_order)
    return paginate(invoice_items)

@router.post("/export")
async def export_invoices(
        ids: List[int],
        columns: Optional[List[str]] = None,
        order_by: Optional[List[OrderByFilter]] = None,
        db: AsyncSession = Depends(get_async_db),
        token: str = Depends(JWTBearer()),
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
    try:
        from mpi_backend.config import (
            EXPORT_MAX_RECORDS_BEFORE_BATCH, 
            EXPORT_USE_OPTIMIZED,
            EXPORT_BATCH_SIZE
        )
        import time
        
        start_time = time.time()
        record_count = len(ids)
        
        # Handle column name mapping
        if columns:
            columns = [col.replace('class_', 'Class') for col in columns]
        
        # Choose export method based on record count and configuration
        if EXPORT_USE_OPTIMIZED and record_count > 100:
            print(f"Using optimized export for {record_count} records")
            
            if record_count > EXPORT_MAX_RECORDS_BEFORE_BATCH:
                # Use batch processing for very large exports
                from mpi_backend.utils.export_utils import convert_items_to_dataframe_batch
                items_df = convert_items_to_dataframe_batch(
                    db_session=db,
                    ids=ids,
                    columns=columns,
                    order_by=order_by,
                    use_suffix=True,
                    batch_size=EXPORT_BATCH_SIZE
                )
                method_used = "batch_optimized"
            else:
                # Use standard optimized method
                from mpi_backend.utils.export_utils import convert_items_to_dataframe_optimized
                items_df = convert_items_to_dataframe_optimized(
                    db_session=db,
                    ids=ids,
                    columns=columns,
                    order_by=order_by,
                    use_suffix=True
                )
                method_used = "optimized"
        else:
            # Use standard method for small exports or when optimization is disabled
            print(f"Using standard export for {record_count} records")
            controller = InvoiceItemController(db)
            items = await controller.get_invoice_items_by_ids(ids, order_by=order_by)
            items_df = convert_items_to_dataframe(items)
            method_used = "standard"
        
        if items_df.empty:
            raise HTTPException(status_code=404, detail="No data found for export")
        
        # Handle column selection
        if columns and not items_df.empty:
            available_columns = [col for col in columns if col in items_df.columns]
            if available_columns:
                items_df = items_df[available_columns]
        else:
            # Default columns
            default_columns = ["Item","Description","Qty","Cost","Amount","Date","Ref NO","PO #","Customer Job","Bill","Vendor","Class","Memo"]
            available_columns = [col for col in default_columns if col in items_df.columns]
            items_df = items_df[available_columns]
        
        # Prepare file paths
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
        filename = f'{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.xlsx'
        file_path = f'{upload_folder}{filename}'
        
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        # Choose Excel export method based on optimization level
        if method_used in ["optimized", "batch_optimized"]:
            from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data_fast
            save_final_data_fast(items_df, file_path)
        else:
            save_final_data(final_df=items_df, supplier='', output_path=file_path)

        processing_time = time.time() - start_time
        print(f"Export completed using {method_used} method in {processing_time:.2f} seconds for {len(items_df)} items")

        # Upload to S3 and get download URL
        upload_file(file_path, file_key=f'Exports/{filename}', is_invoice=False)
        download_url = get_presigned_url(file_key=f'Exports/{filename}', is_invoice=False)

        return download_url
        
    except Exception as e:
        print(f"Export error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.post("/export-all")
async def export_all_invoices(request: ExportToExcelFilterRequest,
        db: AsyncSession = Depends(get_async_db),
        token: str = Depends(JWTBearer()),
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
    try:
        import time
        start_time = time.time()
        
        # Get filtered IDs efficiently
        ids = await InvoiceItemController(db).apply_filters(request, page=1, size=0, col_param='id')
        
        if request.excluded_rows_ids:
            ids = list(set(ids) - set(request.excluded_rows_ids))
        
        if not ids:
            raise HTTPException(status_code=404, detail="No items found matching the filters")
        
        filter_time = time.time() - start_time
        print(f"Filter processing took {filter_time:.2f} seconds, found {len(ids)} items")
        
        # Use the optimized export function
        result = export_invoices(
            ids=ids,
            columns=request.columns,
            order_by=request.order_by,
            db=db,
            token=token
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Export-all error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
