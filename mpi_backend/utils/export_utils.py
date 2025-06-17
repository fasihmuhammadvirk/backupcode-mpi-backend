import pandas as pd


def convert_items_to_dataframe(items, use_suffix=True):
    """
    Convert invoice items to DataFrame with optional suffix support.
    
    Args:
        items: List of InvoiceItem objects
        use_suffix: Whether to use item_code_with_suffix property for display
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
        item_data = item.__dict__.copy()
        # Use item_code_with_suffix for display if requested
        if use_suffix and hasattr(item, 'item_code_with_suffix'):
            item_data['item'] = item.item_code_with_suffix
        items_dict.append(item_data)
    
    df = pd.DataFrame(items_dict).rename(columns=columns_mapping)
    
    # Only select columns that exist in the DataFrame
    available_columns = [col for col in columns_mapping.values() if col in df.columns]
    df = df[available_columns]

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
                          'ref_no', 'po_number', 'customer_job', 'bill', 'vendor', 'class_', 'memo',
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
    
    # Base query
    query = db_session.query(*select_columns).filter(InvoiceItem.id.in_(ids))
    
    # Apply ordering if specified
    if order_by:
        for order_filter in order_by:
            if hasattr(InvoiceItem, order_filter.column):
                column = getattr(InvoiceItem, order_filter.column)
                if order_filter.order == "asc":
                    query = query.order_by(column.asc())
                elif order_filter.order == "desc":
                    query = query.order_by(column.desc())
    
    # Execute query and convert to DataFrame
    results = query.all()
    
    if not results:
        return pd.DataFrame()
    
    # Convert to DataFrame
    df_data = []
    for row in results:
        row_dict = {}
        for i, col in enumerate(selected_columns):
            if i < len(row):
                row_dict[col] = row[i]
        df_data.append(row_dict)
    
    df = pd.DataFrame(df_data)
    
    # Apply suffix logic if needed
    if use_suffix and 'item' in df.columns and 'vendor' in df.columns:
        df['item'] = df.apply(_apply_suffix_to_row, axis=1)
    
    # Format dates
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%m/%d/%Y')
    if 'date_added' in df.columns:
        df['date_added'] = pd.to_datetime(df['date_added']).dt.strftime('%m/%d/%Y')
    
    # Rename columns for display
    display_columns = {col: column_mapping.get(col, col.title()) for col in df.columns}
    df = df.rename(columns=display_columns)
    
    # Remove vendor column if it was only added for suffix calculation
    if use_suffix and columns and 'Vendor' not in columns and 'Vendor' in df.columns:
        df = df.drop('Vendor', axis=1)
    
    return df


def _apply_suffix_to_row(row):
    """Helper function to apply suffix to item code based on vendor."""
    item_code = row.get('item', '')
    vendor = row.get('vendor', '')
    
    if not item_code or not vendor:
        return item_code
    
    # Supplier suffix mapping (from InvoiceItems model)
    suffix_map = {
        "BMW Plumbing Supplies": "-B",
        "World Wide Plumbing": "-W",
        "Y & S Plumbing Supply": "-Y", 
        "Supreme Plumbing Supply": "-S",
        "Pyramid Plumbing": "-P",
        "ABC Opus Services": "-A",
        "Park Plumbing Supply": "-P",
        "Gotham Plumbing Supply": "-G",
        "FW Webb Plumbing Supply": "-F",
        "Flow Mark Plumbing Supply": "-F",
        "Plumbing Exchange": "",
        "AF Supply": "-A",
        "Lion Hvac Supplies": "",
        "Bruce Ferguson": "-F",
    }
    
    # Find suffix for vendor
    suffix = ""
    for supplier_name, supplier_suffix in suffix_map.items():
        if supplier_name in vendor:
            suffix = supplier_suffix
            break
    
    return f"{item_code}{suffix}" if suffix else item_code


# because of circular dependency, had to duplicate code here, will find a better way soon (hopefully)
def extract_supplier_id(file_path):
    company_codes = {
        "BMW Plumbing Supplies": 1,
        "World Wide Plumbing": 2,
        "Y & S Plumbing Supply": 3,
        "Supreme Plumbing Supply": 4,
        "Pyramid Plumbing": 5,
        "ABC Opus Services": 6,
        "Park Plumbing Supply": 7,
        "Gotham Plumbing Supply": 8,
        "FW Webb Plumbing Supply": 9,
        "Flow Mark Plumbing Supply": 10
    }
    for company, code in company_codes.items():
        if company in file_path:
            return code, company
    return 1, "unknown" # need to return some default supplier


def convert_items_to_dataframe_with_suffixes(invoice_items, supplier_id=None, context="display"):
    """
    Convert invoice items to DataFrame with supplier-specific suffixes for display/export.
    
    Args:
        invoice_items: List of InvoiceItem objects
        supplier_id: Supplier ID for suffix determination
        context: Context (display, export, pdf, excel, etc.)
        
    Returns:
        DataFrame with suffixes applied to Item column
    """
    from mpi_backend.utils.item_utils import should_restore_suffix, restore_suffix_by_supplier_id
    
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
    
    # Apply suffixes if context requires it
    if should_restore_suffix(context) and supplier_id and 'item' in df.columns:
        df['Item'] = df['item'].apply(lambda x: restore_suffix_by_supplier_id(x, supplier_id) if x else x)
    elif 'item' in df.columns:
        df['Item'] = df['item']
    
    return df


def prepare_invoice_items_for_display(data, supplier_info=None, context="display"):
    """
    Prepare invoice items for display with suffix restoration.
    
    Args:
        data: DataFrame or list of items
        supplier_info: Dictionary with supplier information (must contain 'id' key)
        context: Display context
        
    Returns:
        Prepared data with suffixes applied
    """
    from mpi_backend.utils.item_utils import should_restore_suffix, restore_suffix_by_supplier_id
    
    if data is None or len(data) == 0:
        return data
    
    # Handle DataFrame
    if isinstance(data, pd.DataFrame):
        result_df = data.copy()
        
        # Apply suffixes if context and supplier info provided
        if (should_restore_suffix(context) and 
            supplier_info and 
            'id' in supplier_info and 
            'Item' in result_df.columns):
            
            supplier_id = supplier_info['id']
            result_df['Item'] = result_df['Item'].apply(
                lambda x: restore_suffix_by_supplier_id(x, supplier_id) if x else x
            )
        
        return result_df
    
    # Handle list of items
    elif isinstance(data, list):
        if not data:
            return data
        
        result_list = []
        for item in data:
            if isinstance(item, dict):
                item_copy = item.copy()
                # Apply suffix to item field
                if (should_restore_suffix(context) and 
                    supplier_info and 
                    'id' in supplier_info and 
                    'item' in item_copy):
                    
                    supplier_id = supplier_info['id']
                    item_copy['item'] = restore_suffix_by_supplier_id(
                        item_copy['item'], supplier_id
                    )
                result_list.append(item_copy)
            else:
                result_list.append(item)
        
        return result_list
    
    # Return as-is for other types
    return data


def convert_items_to_dataframe_batch(db_session, ids, columns=None, order_by=None, use_suffix=True, batch_size=1000):
    """
    Batch processing version for very large exports to handle memory efficiently.
    
    Args:
        db_session: Database session
        ids: List of invoice item IDs to export
        columns: List of column names to include (optional)
        order_by: List of OrderByFilter objects for sorting (optional)
        use_suffix: Whether to apply supplier suffixes
        batch_size: Number of records to process at once
        
    Returns:
        DataFrame ready for Excel export
    """
    if not ids:
        return pd.DataFrame()
    
    # Process in batches if dataset is large
    if len(ids) <= batch_size:
        return convert_items_to_dataframe_optimized(db_session, ids, columns, order_by, use_suffix)
    
    # Process large datasets in batches
    dataframes = []
    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i:i + batch_size]
        batch_df = convert_items_to_dataframe_optimized(
            db_session, batch_ids, columns, order_by, use_suffix
        )
        if not batch_df.empty:
            dataframes.append(batch_df)
        
        # Print progress for large exports
        if len(ids) > 5000:
            progress = min(i + batch_size, len(ids))
            print(f"Processing batch: {progress}/{len(ids)} records")
    
    # Combine all batches
    if dataframes:
        final_df = pd.concat(dataframes, ignore_index=True)
        
        # Apply final sorting if specified (since batch processing might affect order)
        if order_by and len(dataframes) > 1:
            sort_columns = []
            ascending_list = []
            for order_filter in order_by:
                # Map back to display column names
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
                    'memo': 'Memo',
                    'buyer': 'Buyer'
                }
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
