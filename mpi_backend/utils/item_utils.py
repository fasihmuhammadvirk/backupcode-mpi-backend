"""
Utility functions for item processing and cleaning.
"""
import re
from typing import Optional, List, Union, Dict, Any


# Supplier ID to suffix mapping
SUPPLIER_SUFFIX_MAP = {
    1: 'B',   # BMW Plumbing Supplies
    2: 'W',   # World Wide Plumbing  
    3: 'Y',   # Y & S Plumbing Supply
    4: 'S',   # Supreme Plumbing Supply
    5: 'P',   # Pyramid Plumbing
    6: 'A',   # ABC Opus Services
    7: 'P',   # Park Plumbing Supply (same as Pyramid)
    8: 'G',   # Gotham Plumbing Supply
    9: 'F',   # FW Webb Plumbing Supply
    10: 'F',  # Flow Mark Plumbing Supply (same as FW Webb)
    11: None, # Plumbing Exchange (no specific suffix)
    12: 'A',  # AF Supply (same as ABC Opus)
    13: None, # Lion Hvac Supplies (no specific suffix)
    14: 'F', # Bruce Ferguson
}

# Supplier name to suffix mapping for display purposes
SUPPLIER_NAME_SUFFIX_MAP = {
    "BMW Plumbing Supplies": "B",
    "World Wide Plumbing": "W",
    "Y & S Plumbing Supply": "Y",
    "Supreme Plumbing Supply": "S",
    "Pyramid Plumbing": "P",
    "ABC Opus Services": "A",
    "Park Plumbing Supply": "P",
    "Gotham Plumbing Supply": "G",
    "FW Webb Plumbing Supply": "F",
    "Flow Mark Plumbing Supply": "F",
    "Plumbing Exchange": None,  # No suffix
    "AF Supply": "A",
    "Lion Hvac Supplies": None,  # No suffix
    "Bruce Ferguson": "F",
}


def clean_supplier_suffix(item_code: str, supplier_id: Optional[int] = None) -> str:
    """
    Clean supplier-specific suffixes from item codes.
    Only removes the supplier's suffix if it appears at the END of the item code.
    
    Args:
        item_code (str): Original item code potentially with suffix
        supplier_id (int, optional): Specific supplier ID to clean only that supplier's suffix
        
    Returns:
        str: Cleaned item code without suffix
    """
    if not item_code or not isinstance(item_code, str):
        return item_code
    
    if supplier_id is not None:
        # Clean only the specific supplier's suffix, and only if it's at the end
        suffix = SUPPLIER_SUFFIX_MAP.get(supplier_id)
        if suffix:
            # Remove only this supplier's suffix pattern if it's at the end
            pattern = rf'\s*-\s*{suffix}\s*$'
            cleaned_value = re.sub(pattern, '', item_code.strip())
        else:
            # No suffix for this supplier, return as-is
            cleaned_value = item_code.strip()
    else:
        # Clean all known suffixes (fallback for general cleaning), only if at the end
        cleaned_value = re.sub(r'\s*-\s*[BWYSGFPA]\s*$', '', item_code.strip())
    
    # Remove any extra spaces
    return cleaned_value.strip()


def compare_item_codes_with_cleaning(item1: str, item2: str, supplier_id: Optional[int] = None) -> bool:
    """
    Compare two item codes with supplier-specific suffix cleaning support.
    
    Args:
        item1 (str): First item code
        item2 (str): Second item code  
        supplier_id (int, optional): Specific supplier ID for targeted suffix cleaning
        
    Returns:
        bool: True if items match (with or without suffix cleaning), False otherwise
    """
    if not item1 or not item2:
        return item1 == item2
    
    # Direct match
    if item1 == item2:
        return True
    
    # Clean both with supplier-specific logic and compare
    cleaned_item1 = clean_supplier_suffix(item1, supplier_id)
    cleaned_item2 = clean_supplier_suffix(item2, supplier_id)
    
    return cleaned_item1 == cleaned_item2


def get_supplier_suffix(supplier_id: int) -> Optional[str]:
    """
    Get the suffix letter for a specific supplier.
    
    Args:
        supplier_id (int): Supplier ID
        
    Returns:
        Optional[str]: Suffix letter or None if no suffix
    """
    return SUPPLIER_SUFFIX_MAP.get(supplier_id) 


def restore_suffix_by_supplier_id(item_code: str, supplier_id: int) -> str:
    """
    Restore supplier-specific suffix to item code for display purposes.
    This function is ONLY for display, filtering, sorting, and exports.
    
    Args:
        item_code (str): Item code without suffix
        supplier_id (int): Supplier ID to determine appropriate suffix
        
    Returns:
        str: Item code with suffix appended (e.g., "ABC123-B")
    """
    if not item_code:
        return item_code
    
    # Handle None input
    if item_code is None:
        return None
    
    # Clean whitespace
    clean_item = str(item_code).strip()
    if not clean_item:
        return clean_item
    
    # Exclude tax and administrative items from getting suffixes
    excluded_items = [
        "tax", "freight", "shipping", "handling", "subtotal", "total"
    ]
    if (clean_item.startswith("10 Materials") or 
            clean_item.lower() in excluded_items):
        return clean_item
    
    # Get suffix for supplier
    suffix = SUPPLIER_SUFFIX_MAP.get(supplier_id)
    if not suffix:
        return clean_item
    
    # Remove ALL existing suffixes first (including double suffixes like -B-B)
    all_suffixes = set(SUPPLIER_SUFFIX_MAP.values())
    all_suffixes.discard(None)  # Remove None values
    
    # Keep removing suffixes until none are found
    while True:
        found_suffix = False
        for existing_suffix in all_suffixes:
            if existing_suffix and clean_item.endswith(f"-{existing_suffix}"):
                clean_item = clean_item[:-len(f"-{existing_suffix}")]
                found_suffix = True
                break
        if not found_suffix:
            break
    
    # Add the correct suffix
    return f"{clean_item}-{suffix}"


def restore_suffix_by_supplier_name(item_code: str, supplier_name: str) -> str:
    """
    Restore supplier-specific suffix to item code using supplier name.
    This function is ONLY for display purposes.
    
    Args:
        item_code (str): Item code without suffix
        supplier_name (str): Supplier name to determine appropriate suffix
        
    Returns:
        str: Item code with suffix appended (e.g., "ABC123-B")
    """
    if not item_code or not supplier_name:
        return item_code
    
    # Clean whitespace from item code
    clean_item = str(item_code).strip()
    if not clean_item:
        return clean_item
    
    # Exclude tax and administrative items from getting suffixes
    excluded_items = [
        "tax", "freight", "shipping", "handling", "subtotal", "total"
    ]
    if (clean_item.startswith("10 Materials") or 
            clean_item.lower() in excluded_items):
        return clean_item
    
    # Clean whitespace from supplier name
    clean_supplier_name = supplier_name.strip()
    
    # Get suffix for supplier name
    suffix = SUPPLIER_NAME_SUFFIX_MAP.get(clean_supplier_name)
    if not suffix:
        return item_code
    
    # Remove ALL existing suffixes first (including double suffixes)
    all_suffixes = set(SUPPLIER_NAME_SUFFIX_MAP.values())
    all_suffixes.discard(None)  # Remove None values
    
    # Keep removing suffixes until none are found
    while True:
        found_suffix = False
        for existing_suffix in all_suffixes:
            if existing_suffix and clean_item.endswith(f"-{existing_suffix}"):
                clean_item = clean_item[:-len(f"-{existing_suffix}")]
                found_suffix = True
                break
        if not found_suffix:
            break
    
    # Add the correct suffix
    return f"{clean_item}-{suffix}"


def bulk_restore_suffixes(items: Union[List[str], List[Dict[str, Any]]], 
                         supplier_id: Optional[int] = None,
                         supplier_name: Optional[str] = None) -> Union[List[str], List[Dict[str, Any]]]:
    """
    Restore suffixes to a list of items for display purposes.
    
    Args:
        items: List of item codes (strings) or dictionaries containing item information
        supplier_id: Supplier ID to determine suffix
        supplier_name: Supplier name to determine suffix (alternative to supplier_id)
        
    Returns:
        List with suffixes restored to items
    """
    if not items:
        return items
    
    # Use supplier_id if provided, otherwise try to derive from supplier_name
    if supplier_id is None and supplier_name:
        suffix = SUPPLIER_NAME_SUFFIX_MAP.get(supplier_name.strip())
        if suffix:
            # Find supplier_id for this suffix
            for sid, s in SUPPLIER_SUFFIX_MAP.items():
                if s == suffix:
                    supplier_id = sid
                    break
    
    if supplier_id is None:
        return items
    
    result = []
    for item in items:
        if isinstance(item, str):
            # Simple string list
            result.append(restore_suffix_by_supplier_id(item, supplier_id))
        elif isinstance(item, dict):
            # Dictionary with item field
            item_copy = item.copy()
            if 'item' in item_copy:
                item_copy['item'] = restore_suffix_by_supplier_id(item_copy['item'], supplier_id)
            result.append(item_copy)
        else:
            # Unknown type, add as-is
            result.append(item)
    
    return result


def should_restore_suffix(context: str) -> bool:
    """
    Determine if suffix should be restored based on context.
    
    Args:
        context (str): Context where item will be used (display, export, pdf, excel, ui, etc.)
        
    Returns:
        bool: True if suffix should be restored for this context
    """
    # Display contexts where suffixes should be shown
    display_contexts = {
        'display', 'export', 'pdf', 'excel', 'ui', 'table', 'grid', 
        'report', 'view', 'show', 'list', 'filter', 'sort'
    }
    
    # Check case-insensitive
    return context.lower() in display_contexts 


def is_empty_or_invalid_item(item_code: str) -> bool:
    """
    Check if an item code is empty, just a dot, or invalid and should be filtered out.
    
    Args:
        item_code (str): Original item code to check
        
    Returns:
        bool: True if item should be filtered out, False if it's valid
    """
    if not item_code:
        return True
    
    # Clean whitespace
    clean_item = str(item_code).strip()
    
    # Check for empty or just dot
    if not clean_item or clean_item == "." or clean_item == "":
        return True
    
    return False 