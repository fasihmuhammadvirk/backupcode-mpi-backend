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
