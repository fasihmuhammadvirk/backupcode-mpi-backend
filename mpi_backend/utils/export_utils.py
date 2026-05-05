import os
import io
import uuid
import json
import logging
import time
from typing import Any, Dict, List, Optional
from decimal import Decimal
from datetime import datetime

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import HTTPException

from mpi_backend.utils.item_processing_utils import is_empty_or_invalid_item
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.database.schemas.Filters import FilterRequest
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data_fast
from mpi_backend.utils.s3_utils import upload_export_and_get_url
from mpi_backend.utils.supplier_suffix_manager import (
    get_supplier_suffix,
    get_supplier_id_from_name,
    extract_supplier_info
)

logger = logging.getLogger(__name__)

# Sync aggregate export when selection is smaller than this; larger selections use background job (export-all parity).
AGGREGATE_EXPORT_SYNC_MAX_IDS = 1000

# The map between what is shown in UIs, Excels and the database columns that they represent
# NOTE: this isn't a one-to-one, there are some discrepancies from the frontend
DISPLAY_FIELD_TO_COLUMN_MAP = {
    # TODO: Add price difference to mart__invoice_items
    #"Price Difference": "price_increase",
    "File Name": "filename",
    "Sheet Name": "sheet_name",
    "Item": "item",
    "Description": "description",
    "Quantity": "qty",
    "Qty": "qty",
    "Cost": "cost",
    "Amount": "amount",
    "Date": "date",
    "Ref No": "ref_no",
    "Ref NO": "ref_no",
    "PO #": "po_number",
    "Customer Job": "customer_job",
    "Bill": "bill",
    "Vendor": "vendor",
    "Class": "class_",
    "class_": "class_",
    "Account": "account",
    "Memo": "memo",
    "Buyer": "buyer",
    "Date Added": "date_added",
    "Original Item": "mpi_item", # will be removed adding beacuse of incorect naming on frontend
    "Original Description": "mpi_description", # will be removed adding beacuse of incorect naming on frontend
    "Date Added": "date_added",
    "MPI Item": "mpi_item",
    "MPI Item Code": "mpi_item",
    "MPI Description": "mpi_description",
}

# Column order for Data Review aggregate Excel (one row per sheet + MPI bucket from mart SQL).
AGGREGATE_EXPORT_EXCEL_COLUMNS = [
    "Group",
    "MPI Item",
    "MPI Description",
    "Subtotal QTY",
    "PPP",
    "Total Amount",
]


def _normalize_line_breaks(df: pd.DataFrame) -> pd.DataFrame:
    """Replace line breaks with spaces in all string columns."""
    df.replace(to_replace=r'\r\n|\r|\n', value=' ', regex=True, inplace=True)
    return df


def convert_items_to_dataframe(items, use_suffix=True):
    """
    Convert invoice items to DataFrame with optional suffix support.
    Automatically filters out items with empty or invalid item codes.
    
    Args:
        items: List of InvoiceItem objects
        use_suffix: Whether to use item codes with suffixes (deprecated - always uses full item codes now)
    """
    columns_mapping = {
        'item': 'Item',
        'description': 'Description',
        'qty': 'Qty',
        'cost': 'Cost',
        'amount': 'Amount',
        'date': 'Date',
        'ref_no': 'Ref NO',
        'po_number': 'PO #',
        'customer_job': 'Customer Job',
        'bill': 'Bill',
        'vendor': 'Vendor',
        'class_': 'Class',
        'account': 'Account',
        'memo': 'Memo',
        'buyer': 'Buyer',
        "filename": "Filename",
        "sheet_name": "Sheet Name",
        "mpi_item": "MPI Item Code",
        "mpi_description": "MPI Description",
        "date_added": "Date Added"
    }

    items_dict = []
    for item in items:
        # Filter out items with empty or invalid item codes
        if is_empty_or_invalid_item(getattr(item, 'item', '')):
            continue
            
        item_data = item.__dict__.copy()
        # With suffix standardization, we always use the full item code as stored
        # No need to check for item_code_with_suffix property
        items_dict.append(item_data)
    
    df = pd.DataFrame(items_dict).rename(columns=columns_mapping)

    # Ensure ref_no is formatted as string to preserve leading zeros
    if 'Ref NO' in df.columns:
        df['Ref NO'] = df['Ref NO'].astype(str)
        # Add invisible non-breaking space to pure numeric refs to prevent Excel errors
        df['Ref NO'] = df['Ref NO'].apply(
            lambda x: '\u00A0' + str(x) if str(x).isdigit() else str(x)
        )

    # Only select columns that exist in the DataFrame
    available_columns = [col for col in columns_mapping.values() if col in df.columns]
    df = df[available_columns]

    _normalize_line_breaks(df)

    return df


def convert_items_to_dataframe_optimized(db_session, ids, columns=None, order_by=None, use_suffix=True):
    """
    Optimized DataFrame conversion using raw SQL for better performance.
    
    Args:
        db_session: Database session
        ids: List of invoice item IDs to export
        columns: List of column names to include (optional)
        order_by: List of OrderByFilter objects for sorting (optional)
        use_suffix: Whether to apply supplier suffixes
        
    Returns:
        DataFrame ready for Excel export
    """
    if not ids:
        return pd.DataFrame()
    
    # Define all possible columns for export
    column_mapping = {
        'item': 'Item',
        'description': 'Description', 
        'qty': 'Qty',
        'cost': 'Cost',
        'amount': 'Amount',
        'date': 'Date',
        'ref_no': 'Ref NO',
        'po_number': 'PO #',
        'customer_job': 'Customer Job',
        'bill': 'Bill',
        'vendor': 'Vendor',
        'class_': 'Class',
        'account': 'Account',
        'memo': 'Memo',
        'buyer': 'Buyer',
        'filename': 'Filename',
        'sheet_name': 'Sheet Name',
        'mpi_item': 'MPI Item Code',
        'mpi_description': 'MPI Description',
        'date_added': 'Date Added'
    }
    
    # Determine which columns to select
    if columns:
        # Map display column names back to database columns
        reverse_mapping = {v: k for k, v in column_mapping.items()}
        db_columns = []
        for col in columns:
            db_col = reverse_mapping.get(col, col.lower().replace(' ', '_'))
            if db_col in column_mapping:
                db_columns.append(db_col)
        selected_columns = db_columns
    else:
        # Default columns for export - match original convert_items_to_dataframe
        selected_columns = ['item', 'description', 'qty', 'cost', 'amount', 'date', 
                          'ref_no', 'po_number', 'customer_job', 'bill', 'vendor', 'class_', 'account', 'memo',
                          'buyer', 'filename', 'sheet_name', 'mpi_item', 'mpi_description', 'date_added']
    
    # Always include vendor for suffix calculation if needed
    if use_suffix and 'vendor' not in selected_columns:
        selected_columns.append('vendor')
    
    # Build the SQL query
    from mpi_backend.database.models.InvoiceItems import InvoiceItem
    
    # Build SELECT clause
    select_columns = []
    for col in selected_columns:
        if hasattr(InvoiceItem, col):
            select_columns.append(getattr(InvoiceItem, col))
    
    # Base query with empty item filter
    query = db_session.query(*select_columns).filter(InvoiceItem.id.in_(ids))
    
    # Filter out empty, null, or just dot item codes
    query = query.filter(
        InvoiceItem.item.isnot(None),
        InvoiceItem.item != "",
        InvoiceItem.item != ".",
        func.trim(InvoiceItem.item) != "",
        func.trim(InvoiceItem.item) != "."
    )
    
    # Apply ordering if specified
    if order_by:
        for order_filter in order_by:
            if hasattr(InvoiceItem, order_filter.column):
                column = getattr(InvoiceItem, order_filter.column)
                if order_filter.order == "asc":
                    query = query.order_by(column.asc())
                elif order_filter.order == "desc":
                    query = query.order_by(column.desc())
    
    # Execute optimized query directly to DataFrame
    try:
        # Execute query and convert to DataFrame efficiently
        results = query.all()
        
        if not results:
            return pd.DataFrame()
        
        # Convert to DataFrame efficiently
        df_data = []
        for row in results:
            row_dict = {}
            for i, col in enumerate(selected_columns):
                row_dict[col] = row[i] if i < len(row) else None
            df_data.append(row_dict)
        
        df = pd.DataFrame(df_data)
        
        # Apply duplication filtering if needed (only for large datasets)
        if len(df) > 1000:
            from mpi_backend.utils.duplication_filter import filter_exact_duplicates_df
            df = filter_exact_duplicates_df(df)
        
    except Exception as e:
        print(f"Optimized query failed, falling back to standard method: {e}")
        # Fallback to standard method if optimized fails
        full_query = db_session.query(InvoiceItem).filter(InvoiceItem.id.in_(ids))
        if order_by:
            for order_filter in order_by:
                if hasattr(InvoiceItem, order_filter.column):
                    column = getattr(InvoiceItem, order_filter.column)
                    if order_filter.order == "asc":
                        full_query = full_query.order_by(column.asc())
                    elif order_filter.order == "desc":
                        full_query = full_query.order_by(column.desc())
        
        full_results = full_query.all()
        from mpi_backend.utils.duplication_filter import filter_exact_duplicates
        filtered_results = filter_exact_duplicates(full_results)
        
        if not filtered_results:
            return pd.DataFrame()
        
        df_data = []
        for item in filtered_results:
            row_dict = {}
            for col in selected_columns:
                if hasattr(item, col):
                    row_dict[col] = getattr(item, col)
            df_data.append(row_dict)
        
        df = pd.DataFrame(df_data)
    
    _normalize_line_breaks(df)

    # Apply suffix logic if needed
    if use_suffix and 'item' in df.columns and 'vendor' in df.columns:
        df['item'] = df.apply(_apply_suffix_to_row, axis=1)
    
    # Format dates
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%m/%d/%Y')
    
    # Ensure ref_no is formatted as string to preserve leading zeros
    if 'ref_no' in df.columns:
        df['ref_no'] = df['ref_no'].astype(str)
        # Add invisible non-breaking space to pure numeric refs to prevent Excel errors
        df['ref_no'] = df['ref_no'].apply(
            lambda x: '\u00A0' + str(x) if str(x).isdigit() else str(x)
        )
    
    
    if 'date_added' in df.columns:
        df['date_added'] = pd.to_datetime(df['date_added']).dt.strftime('%m/%d/%Y')
    
    # Rename columns for display
    display_columns = {col: column_mapping.get(col, col.title()) for col in df.columns}
    df = df.rename(columns=display_columns)
    
    # With suffix standardization, vendor column is not needed for suffix calculation
    # Keep vendor column as requested by user
    
    return df


def _apply_suffix_to_row(row):
    """Helper function to apply suffix to item code based on vendor."""
    item_code = row.get('item', '')
    vendor = row.get('vendor', '')
    
    if not item_code or not vendor:
        return item_code
    
    # Exclude tax and administrative items from getting suffixes
    item_str = str(item_code).strip()
    excluded_items = [
        "tax", "freight", "shipping", "handling", "subtotal", "total"
    ]
    if (item_str.startswith("10 Materials") or 
            item_str.lower() in excluded_items):
        return item_code
    
    # Find suffix for vendor
    supplier_id = get_supplier_id_from_name(vendor)
    suffix = ""
    if supplier_id is not None:
        suffix_value = get_supplier_suffix(supplier_id=supplier_id, with_dash=True)
        if suffix_value:
            suffix = suffix_value
    
    if not suffix:
        return item_code
    
    # With suffix standardization, we use the full item codes as stored
    # No suffix manipulation needed
    return item_code


# Use centralized supplier suffix manager (resolves circular dependency)
def extract_supplier_id(file_path):
    """
    Extract supplier ID and name from file path or vendor string.
    
    Uses centralized supplier_suffix_manager for consistent supplier identification.
    
    Args:
        file_path: File path or vendor name string to extract supplier from
        
    Returns:
        Tuple of (supplier_id, supplier_name) or (None, None) if not found
        
    Note:
        Returns (None, None) instead of a default fallback to prevent
        mis-assigning items to the wrong supplier. Callers should check
        for None and skip mapping updates when supplier cannot be identified.
    """
    supplier_id, supplier_name, _ = extract_supplier_info(file_path)
    if supplier_id is not None:
        return supplier_id, supplier_name
    return None, None  # Return None to prevent mis-assignment to wrong supplier


def convert_items_to_dataframe_with_suffixes(invoice_items, supplier_id=None, context="display"):
    """
    Convert invoice items to DataFrame with full item codes (suffix standardization).
    
    Args:
        invoice_items: List of InvoiceItem objects
        supplier_id: Supplier ID (deprecated - no longer used for suffix determination)
        context: Context (display, export, pdf, excel, etc.)
        
    Returns:
        DataFrame with full item codes as stored
    """
    # Removed suffix restoration imports - no longer needed with suffix standardization
    
    if not invoice_items:
        return pd.DataFrame()
    
    # Convert to list of dictionaries
    items_data = []
    for item in invoice_items:
        # Check if it's a Mock object by checking for Mock-specific attributes
        is_mock = (hasattr(item, '_mock_name') or 
                  hasattr(item, '_mock_return_value') or
                  str(type(item)).find('Mock') != -1)
        
        if is_mock and hasattr(item, '__dict__'):
            # Mock object - use __dict__ directly
            item_dict = item.__dict__.copy()
        else:
            # Real object - get attributes normally
            item_dict = {}
            try:
                for attr in dir(item):
                    if not attr.startswith('_') and not callable(getattr(item, attr)):
                        try:
                            value = getattr(item, attr)
                            # Handle SQLAlchemy objects that might not be serializable
                            if hasattr(value, '__dict__'):
                                continue
                            item_dict[attr] = value
                        except:
                            continue
            except AttributeError:
                # Fallback for objects that have issues with dir()
                if hasattr(item, '__dict__'):
                    item_dict = item.__dict__.copy()
        
        items_data.append(item_dict)
    
    # Create DataFrame
    df = pd.DataFrame(items_data)
    
    # With suffix standardization, we use the full item codes as stored
    if 'item' in df.columns:
        df['Item'] = df['item']
    
    return df


def prepare_invoice_items_for_display(data, supplier_info=None, context="display"):
    """
    Prepare invoice items for display with full item codes (suffix standardization).
    
    Args:
        data: DataFrame or list of items
        supplier_info: Dictionary with supplier information (deprecated - no longer used for suffix determination)
        context: Display context
        
    Returns:
        Prepared data with full item codes as stored
    """
    # Removed suffix restoration imports - no longer needed with suffix standardization
    
    if data is None or len(data) == 0:
        return data
    
    # Handle DataFrame
    if isinstance(data, pd.DataFrame):
        result_df = data.copy()
        
        # With suffix standardization, we use the full item codes as stored
        # No suffix restoration needed
        
        return result_df
    
    # Handle list of items
    elif isinstance(data, list):
        if not data:
            return data
        
        result_list = []
        for item in data:
            if isinstance(item, dict):
                item_copy = item.copy()
                # With suffix standardization, we use the full item codes as stored
                # No suffix restoration needed
                result_list.append(item_copy)
            else:
                result_list.append(item)
        
        return result_list
    
    # Return as-is for other types
    return data


def convert_items_to_dataframe_batch(db_session, ids, columns=None, order_by=None, use_suffix=True, batch_size=500):
    """
    Ultra-fast batch processing for large exports with optimized performance.
    
    Args:
        db_session: Database session
        ids: List of invoice item IDs to export
        columns: List of column names to include (optional)
        order_by: List of OrderByFilter objects for sorting (optional)
        use_suffix: Whether to apply supplier suffixes
        batch_size: Number of records to process at once (optimized to 500)
        
    Returns:
        DataFrame ready for Excel export
    """
    if not ids:
        return pd.DataFrame()
    
    # For smaller datasets, use optimized method directly
    if len(ids) <= batch_size:
        return convert_items_to_dataframe_optimized(db_session, ids, columns, order_by, use_suffix)
    
    # Process large datasets in optimized batches
    dataframes = []
    total_batches = (len(ids) + batch_size - 1) // batch_size
    
    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i:i + batch_size]
        
        # Use optimized method for each batch
        batch_df = convert_items_to_dataframe_optimized(
            db_session, batch_ids, columns, order_by, use_suffix
        )
        
        if not batch_df.empty:
            dataframes.append(batch_df)
        
        # Progress reporting for large exports
        if len(ids) > 2000:
            batch_num = (i // batch_size) + 1
            print(f"Processing batch {batch_num}/{total_batches}: {len(batch_df)} records")
    
    # Efficiently combine all batches
    if dataframes:
        # Use concat with ignore_index for better performance
        final_df = pd.concat(dataframes, ignore_index=True)
        
        # Apply final sorting only if needed and we have multiple batches
        if order_by and len(dataframes) > 1:
            sort_columns = []
            ascending_list = []
            column_mapping = {
                'item': 'Item', 'description': 'Description', 'qty': 'Qty', 
                'cost': 'Cost', 'amount': 'Amount', 'date': 'Date',
                'ref_no': 'Ref NO', 'po_number': 'PO #', 'customer_job': 'Customer Job',
                'bill': 'Bill', 'vendor': 'Vendor', 'class_': 'Class',
                'memo': 'Memo', 'buyer': 'Buyer'
            }
            
            for order_filter in order_by:
                display_col = column_mapping.get(order_filter.column, order_filter.column.title())
                if display_col in final_df.columns:
                    sort_columns.append(display_col)
                    ascending_list.append(order_filter.order == "asc")
            
            if sort_columns:
                final_df = final_df.sort_values(by=sort_columns, ascending=ascending_list)
                final_df = final_df.reset_index(drop=True)
        
        return final_df
    else:
        return pd.DataFrame()


def convert_unmapped_items_to_dataframe(items):
    """
    Convert unmapped items to DataFrame for Excel export.
    
    Args:
        items: List of unmapped item dictionaries from UnmappedItemsController
        
    Returns:
        DataFrame ready for Excel export
    """
    if not items:
        return pd.DataFrame()
    
    # Define column mapping for unmapped items
    columns_mapping = {
        'original_item_id': 'Original Item ID',
        'original_description': 'Original Description',
        'cost': 'Cost',
        'amount': 'Amount',
        'quantity': 'Quantity',
        'times_bought': 'Times Bought',
        'sheet_name': 'Sheet Name',
        'supplier': 'Supplier'
    }
    
    # Convert items to DataFrame
    df = pd.DataFrame(items)

    # Rename columns for display
    available_columns = [col for col in columns_mapping.keys() if col in df.columns]
    df = df[available_columns].rename(columns=columns_mapping)

    _normalize_line_breaks(df)

    # Format numeric columns
    if 'Cost' in df.columns:
        df['Cost'] = pd.to_numeric(df['Cost'], errors='coerce')
    if 'Amount' in df.columns:
        df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
    if 'Quantity' in df.columns:
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')
    
    return df



def convert_mart_items_to_dataframe(items: list[Dict[str, str|Decimal]], columns: Optional[list[str]]=None):
    """
    Convert mart query results (list of dicts) to DataFrame for Excel export.

    This function processes raw mart table results (dictionaries) instead of ORM objects,
    providing better performance for large exports by avoiding ORM overhead.

    Args:
        items: List of dictionaries from mart__invoice_items DAO queries
        columns: List of display column names to include (optional)

    Returns:
        DataFrame ready for Excel export with formatted dates and columns
    """
    if not items:
        return pd.DataFrame()

    # Define all possible columns for export (DB column -> Display name)
    # TODO: This and all others need to be consolidated into a single map/list
    column_mapping = {
        "item": "Item",
        "description": "Description",
        "qty": "Qty",
        "cost": "Cost",
        "amount": "Amount",
        "date": "Date",
        "ref_no": "Ref NO",
        "po_number": "PO #",
        "customer_job": "Customer Job",
        "bill": "Bill",
        "vendor": "Vendor",
        "class_": "Class",
        "account": "Account",
        "memo": "Memo",
        "buyer": "Buyer",
        "filename": "Filename",
        "sheet_name": "Sheet Name",
        "mpi_item": "MPI Item Code",
        "mpi_item_label": "MPI Item",
        "mpi_description": "MPI Description",
        "date_added": "Date Added",
        "group_name": "Group",
        "ppp": "PPP",
        "subtotal_qty": "Subtotal QTY",
        "total_amount": "Total Amount",
        "quotes_count": "Quotes Count",
        "best_price": "Market Best Price",
        "potential_savings": "Potential Savings",
        "supplier_name": "Supplier Name",
        "purchase_date": "Purchase Date",
        "unit_price": "Unit Price",
        "variance_amount": "Variance Amount",
        "variance_percentage": "Variance Percentage",
        "is_best_value": "Is Best Value",
        "is_worst_quote": "Is Worst Purchase",

        # Unmapped items columns
        "original_item_id": "Original Item ID",
        "original_description": "Original Description",
        "supplier": "Supplier",
        "quantity": "Quantity",
        "times_bought": "Times Bought",
    }

    # Reverse mapping for column selection (Display name -> DB column)
    reverse_mapping = {v: k for k, v in column_mapping.items()}

    # Convert items to DataFrame
    df = pd.DataFrame(items)

    _normalize_line_breaks(df)

    # Determine which columns to include
    if columns:
        # Map display column names back to database columns
        db_columns = []
        for col in columns:
            db_col = reverse_mapping.get(col, col.lower().replace(" ", "_"))
            if db_col in df.columns:
                db_columns.append(db_col)
        selected_columns = db_columns
    else:
        # Use all available columns from mapping that exist in data
        selected_columns = [col for col in column_mapping.keys() if col in df.columns]

    # Filter to selected columns
    df = df[selected_columns]

    # Format dates
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%m/%d/%Y")

    if "date_added" in df.columns:
        df["date_added"] = pd.to_datetime(df["date_added"], errors="coerce").dt.strftime("%m/%d/%Y")

    # Ensure columns with potential leading zeros are formatted as strings
    text_columns = ["ref_no", "item", "mpi_item", "po_number", "original_item_id"]
    for col in text_columns:
        if col in df.columns:
            df[col] = df[col].astype(str)

    # 2dp = two decimal places; coerces Decimal types to float as a side-effect
    round_2dp_columns = ["ppp"]
    for col in round_2dp_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(2)

    # Rename columns for display
    display_columns = {col: column_mapping.get(col, col.title()) for col in df.columns}
    df = df.rename(columns=display_columns)

    return df



def export_items_generic(
    items: list[Dict[str, str|Decimal]],
    columns: Optional[list[str]]=None,
    background_tasks=None,
    threshold: int=1000
):
    """
    Generic export function that automatically handles sync vs async based on data size.

    This function decides whether to process the export synchronously (return URL immediately)
    or asynchronously (return export_id for status tracking) based on record count.

    Args:
        items: List[Dict] - List of item dicts from mart query
        columns: List of display column names to export (optional)
        background_tasks: FastAPI BackgroundTasks (optional, enables async if provided)
        threshold: Record count threshold for async processing (default 1000)

    Returns:
        - If sync: Presigned S3 URL string
        - If async: Dict with export_id, status, status_endpoint
    """
    record_count = len(items)

    # Decide sync vs async
    if record_count < threshold or background_tasks is None:
        # Process synchronously
        logger.info(f"Processing export synchronously for {record_count} records")

        # Convert to DataFrame
        items_df = convert_mart_items_to_dataframe(items, columns=columns)

        if items_df.empty:
            raise HTTPException(status_code=404, detail="No data found for export")

        # Prepare file paths
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
        filename = f'{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.xlsx'
        file_path = f'{upload_folder}{filename}'

        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        # Save Excel file
        save_final_data_fast(items_df, file_path)

        download_url = upload_export_and_get_url(file_path)

        return download_url

    else:
        # Process asynchronously
        logger.info(f"Processing export asynchronously for {record_count} records")

        # Generate unique export ID
        export_id = str(uuid.uuid4())
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
        export_status_file = f'{upload_folder}status_{export_id}.json'

        # Create status file indicating processing
        os.makedirs(upload_folder, exist_ok=True)
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'processing',
                'export_id': export_id,
                'record_count': record_count,
                'started_at': datetime.now().isoformat(),
                'message': 'Export is being processed in the background'
            }, f)

        # Add background task
        background_tasks.add_task(
            process_export_background_mart,
            export_id=export_id,
            items=items,
            columns=columns,
            upload_folder=upload_folder
        )

        # Return immediately with export ID and status endpoint
        return {
            "export_id": export_id,
            "status": "processing",
            "record_count": record_count,
            "message": "Export is being processed. Use the export_id to check status.",
            "status_endpoint": f"/invoice-items/export-status/{export_id}"
        }


def stream_csv_generator(items: list[Dict[str, str|Decimal]], columns: Optional[list[str]]=None, chunk_size: int=100):
    """
    Generator that yields CSV data in chunks for true streaming.

    This avoids loading the entire CSV into memory before sending to client.

    Args:
        items: List of item dicts to export
        columns: Optional list of columns to include
        chunk_size: Number of rows per chunk (default 100)

    Yields:
        CSV string chunks (header first, then data rows)
    """
    try:
        df = convert_mart_items_to_dataframe(items, columns=columns)

        if df.empty:
            yield ""
            return

        # Yield header row first
        yield ','.join(f'"{col}"' for col in df.columns) + '\n'

        # Yield data rows in chunks
        for start_idx in range(0, len(df), chunk_size):
            chunk_df = df.iloc[start_idx:start_idx + chunk_size]
            csv_buffer = io.StringIO()
            chunk_df.to_csv(csv_buffer, index=False, header=False)
            yield csv_buffer.getvalue()

    except Exception as e:
        logger.error(f"Error in CSV streaming: {e}")
        raise


def export_generic(
    items: list[Dict[str, str|Decimal]],
    columns: Optional[list[str]]=None,
    background_tasks=None,
    threshold: int=1000,
    file_type: str="csv",
    filename_prefix: str="export"
):
    """
    Generic export function that automatically handles sync vs async based on data size.

    Follows the same pattern as export_items_generic() but optimized for CSV/PDF output.

    Args:
        items: List of item dicts to export
        columns: Optional list of columns to include
        background_tasks: FastAPI BackgroundTasks (optional, enables async if provided)
        threshold: Record count threshold for async processing (default 1000)
        file_type: Type of file to export (csv or pdf)
        filename_prefix: Prefix for the exported filename

    Returns:
        - If sync (small dataset): Generator for StreamingResponse
        - If async (large dataset): Dict with export_id, status, status_endpoint
    """
    record_count = len(items)

    # For small datasets or when background_tasks not available, use streaming generator
    if record_count < threshold or background_tasks is None:
        logger.info(f"Processing {file_type} export synchronously (streaming) for {record_count} records")
        if file_type == "csv":
            return {
                "type": "streaming",
                "generator": stream_csv_generator(items, columns),
                "filename": f"{filename_prefix}_{datetime.now().strftime('%Y-%m-%d')}.{file_type}"
            }
        elif file_type == "pdf":
            return {
                "type": "streaming",
                "pdf_bytes": generate_po_pdf(items),
                "filename": f"{filename_prefix}_{datetime.now().strftime('%Y-%m-%d')}.{file_type}"
            }
        raise ValueError(f"Unsupported file_type: {file_type}. Supported types: 'csv', 'pdf'")

    else:
        # For large datasets, process asynchronously via S3
        logger.info(f"Processing {file_type} export asynchronously for {record_count} records")

        export_id = str(uuid.uuid4())
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
        export_status_file = f'{upload_folder}status_{export_id}.json'

        os.makedirs(upload_folder, exist_ok=True)
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'processing',
                'export_id': export_id,
                'record_count': record_count,
                'format': file_type,
                'started_at': datetime.now().isoformat(),
                'message': f'{file_type} export is being processed in the background'
            }, f)

        background_tasks.add_task(
            process_export_background,
            export_id=export_id,
            items=items,
            columns=columns,
            upload_folder=upload_folder,
            filename_prefix=filename_prefix,
            file_type=file_type
        )

        return {
            "type": "async",
            "export_id": export_id,
            "status": "processing",
            "record_count": record_count,
            "message": f"{file_type} export is being processed. Use the export_id to check status.",
            "status_endpoint": f"/invoice-items/export-status/{export_id}"
        }


def process_export_background(
    export_id: str,
    items: list[Dict[str, str|Decimal]],
    columns: Optional[list[str]],
    upload_folder: str,
    filename_prefix: str = "export",
    file_type: str = "csv"
):
    """
    Background task to process CSV/PDF exports for large datasets.

    Saves CSV/PDF to file, uploads to S3, and updates status file.

    Args:
        export_id: Unique identifier for this export
        items: List of item dicts to export
        columns: Optional list of columns to include
        upload_folder: Directory for export files
        filename_prefix: Prefix for the exported filename
        file_type: Type of file to export (csv or pdf)
    """
    export_status_file = f'{upload_folder}status_{export_id}.json'

    try:
        start_time = time.time()

        # Update status to processing
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'processing',
                'export_id': export_id,
                'record_count': len(items),
                'format': file_type,
                'started_at': datetime.now().isoformat(),
                'message': f'{file_type} export is being processed'
            }, f)

        # Prepare file paths
        filename = f'{filename_prefix}_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.{file_type}'
        file_path = f'{upload_folder}{filename}'

        if file_type == "csv":
            # Convert items to DataFrame
            items_df = convert_mart_items_to_dataframe(items, columns=columns)

            if items_df.empty:
                raise Exception("No data found for CSV export")

            # Save CSV file
            items_df.to_csv(file_path, index=False)
        elif file_type == "pdf":
            # Convert items to DataFrame
            pdf_bytes = generate_po_pdf(items)

            # Save PDF file
            with open(file_path, 'wb') as f:
                f.write(pdf_bytes)

        processing_time = time.time() - start_time
        logger.info(f"Background {file_type} export completed in {processing_time:.2f}s for {len(items)} items")

        download_url = upload_export_and_get_url(file_path)

        # Update status to completed
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'completed',
                'export_id': export_id,
                'record_count': len(items),
                'format': file_type,
                'started_at': datetime.now().isoformat(),
                'completed_at': datetime.now().isoformat(),
                'download_url': download_url,
                'processing_time': f"{processing_time:.2f}s",
                'message': f'{file_type} export completed successfully'
            }, f)

    except Exception as e:
        logger.error(f"Background {file_type} export error: {str(e)}")
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'failed',
                'export_id': export_id,
                'format': file_type,
                'error': str(e),
                'message': f'{file_type} export failed'
            }, f)

def process_export_background_mart(
    export_id,
    items,
    columns,
    upload_folder
):
    """
    Background task to process mart-based exports.

    Updates status file through lifecycle and generates Excel file.

    Args:
        export_id: Unique identifier for this export
        items: List of item dicts to export
        columns: List of display column names (optional)
        upload_folder: Directory for export files
    """

    export_status_file = f'{upload_folder}status_{export_id}.json'

    try:
        start_time = time.time()

        # Update status to processing
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'processing',
                'export_id': export_id,
                'record_count': len(items),
                'started_at': datetime.now().isoformat(),
                'message': 'Export is being processed'
            }, f)

        # Convert items to DataFrame
        items_df = convert_mart_items_to_dataframe(items, columns=columns)

        if items_df.empty:
            raise Exception("No data found for export")

        # Prepare file paths
        filename = f'{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.xlsx'
        file_path = f'{upload_folder}{filename}'

        # Save Excel file
        save_final_data_fast(items_df, file_path)

        processing_time = time.time() - start_time
        print(f"Background export completed in {processing_time:.2f} seconds for {len(items_df)} items")

        download_url = upload_export_and_get_url(file_path)

        # Update status to completed
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'completed',
                'export_id': export_id,
                'record_count': len(items),
                'started_at': datetime.now().isoformat(),
                'completed_at': datetime.now().isoformat(),
                'download_url': download_url,
                'processing_time': f"{processing_time:.2f}s",
                'message': 'Export completed successfully'
            }, f)

    except Exception as e:
        print(f"Background export error: {str(e)}")
        # Update status to failed
        with open(export_status_file, 'w') as f:
            json.dump({
                'status': 'failed',
                'export_id': export_id,
                'error': str(e),
                'message': 'Export failed'
            }, f)

def generate_po_pdf(items: list[dict]) -> bytes:
    """
    Build a styled purchase-order HTML document and render it to PDF bytes.

    Args:
        items: List of dicts produced by POItemResponse.to_dict().
                Expected keys: mpi_item, item, description, supplier, cost, qty, date.

    Returns:
        Raw PDF bytes ready to be streamed.

    Raises:
        ValueError: if items list is empty.
        ImportError: if weasyprint is not installed.
    """
    if not items:
        raise ValueError("No items provided for PDF generation")

    try:
        from weasyprint import HTML, CSS
    except ImportError:
        raise ImportError(
            "weasyprint is required for PDF export. "
            "Install with 'uv add weasyprint'."
        )

    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    # ── Build table rows ──────────────────────────────────────────────────────
    row_html_parts: list[str] = []
    grand_total = 0.0
    for i, item in enumerate(items):
        try:
            cost = float(item.get("cost", 0) or 0)
            qty  = float(item.get("qty",  1) or 1)
        except (ValueError, TypeError):
            cost, qty = 0.0, 1.0
        line_total = cost * qty
        grand_total += line_total

        row_class = "even" if i % 2 == 0 else "odd"
        row_html_parts.append(f"""
        <tr class="{row_class}">
            <td>{i + 1}</td>
            <td class="code mpi-code">{item.get('mpi_item') or item.get('item_mpi_code') or '—'}</td>
            <td class="code">{item.get('item') or item.get('item_code') or '—'}</td>
            <td>{item.get('description') or item.get('mpi_description') or '—'}</td>
            <td>{item.get('supplier') or item.get('supplier_name') or '—'}</td>
            <td class="num">{qty:,.0f}</td>
            <td class="num">${cost:,.2f}</td>
            <td class="num total-cell">${line_total:,.2f}</td>
            <td>{item.get('date') or item.get('purchase_date') or '—'}</td>
        </tr>""")

    rows_html = "\n".join(row_html_parts)
    item_count = len(items)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Purchase Order</title>
</head>
<body>

  <!-- ── Header ───────────────────────────────────────────────────── -->
  <div class="page-header">
    <div class="header-left">
      <div class="company-name">MPI Plumbing</div>
      <div class="doc-title">Purchase Order</div>
    </div>
    <div class="header-right">
      <div class="meta-line"><span class="label">Generated:</span> {generated_at}</div>
      <div class="meta-line"><span class="label">Total Items:</span> {item_count}</div>
      <div class="meta-line grand-total-header">
        <span class="label">Grand Total:</span> ${grand_total:,.2f}
      </div>
    </div>
  </div>

  <!-- ── Table ────────────────────────────────────────────────────── -->
  <table>
    <thead>
      <tr>
        <th style="width:25px">#</th>
        <th style="width:90px">MPI Item #</th>
        <th style="width:90px">Org Item</th>
        <th>Description</th>
        <th style="width:105px">Supplier</th>
        <th style="width:40px">Qty</th>
        <th style="width:70px">Unit Cost</th>
        <th style="width:80px">Line Total</th>
        <th style="width:80px">Date</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
    <tfoot>
      <tr class="footer-row">
        <td colspan="7" class="footer-label">Grand Total</td>
        <td class="num grand-total">${grand_total:,.2f}</td>
        <td></td>
      </tr>
    </tfoot>
  </table>

  <!-- ── Footer note ──────────────────────────────────────────────── -->
  <div class="footer-note">
    This document was generated automatically by the MPI Plumbing system.
    Prices reflect the best available cost at the time of comparison.
  </div>

</body>
</html>"""

    css_content = """
@page {
    size: A4 landscape;
    margin: 15mm 12mm 15mm 12mm;
}

body {
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 9pt;
    color: #202124;
    margin: 0;
    padding: 0;
}

/* ── Header ──────────────────────────────────────────── */
.page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 2px solid #1A73E8;
}
.company-name {
    font-size: 18pt;
    font-weight: 700;
    color: #1A73E8;
    letter-spacing: -0.5px;
}
.doc-title {
    font-size: 11pt;
    color: #5f6368;
    margin-top: 2px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.header-right {
    text-align: right;
}
.meta-line {
    font-size: 8.5pt;
    color: #5f6368;
    margin-bottom: 2px;
}
.meta-line .label {
    font-weight: 600;
    color: #3c4043;
}
.grand-total-header {
    font-size: 10pt;
    margin-top: 4px;
    color: #1A73E8;
    font-weight: 700;
}

/* ── Table ──────────────────────────────────────────── */
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 8.5pt;
}
thead tr {
    background: #1A73E8;
    color: #ffffff;
}
thead th {
    padding: 7px 8px;
    text-align: left;
    font-weight: 600;
    font-size: 7.5pt;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
tbody tr.even { background: #ffffff; }
tbody tr.odd  { background: #f8f9fa; }
tbody tr:hover { background: #E8F0FE; }

tbody td {
    padding: 6px 8px;
    border-bottom: 1px solid #e8eaed;
    vertical-align: top;
}
.code { font-family: "Courier New", monospace; font-size: 8pt; color: #1A73E8; }
.num  { text-align: right; font-variant-numeric: tabular-nums; }
.total-cell { font-weight: 600; color: #1A73E8; }

/* ── Footer row ─────────────────────────────────────── */
tfoot .footer-row { background: #E8F0FE; }
tfoot td {
    padding: 7px 8px;
    font-weight: 700;
    font-size: 9pt;
}
.footer-label { text-align: right; color: #3c4043; }
.grand-total   { text-align: right; color: #1A73E8; font-size: 10pt; }

/* ── Footer note ────────────────────────────────────── */
.footer-note {
    margin-top: 12px;
    font-size: 7.5pt;
    color: #9aa0a6;
    border-top: 1px solid #e8eaed;
    padding-top: 6px;
}
"""

    pdf_bytes = HTML(string=html_content).write_pdf(
        stylesheets=[CSS(string=css_content)]
    )
    return pdf_bytes
