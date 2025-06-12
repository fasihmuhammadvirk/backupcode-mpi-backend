"""
Utility functions for item processing and cleaning.
"""
import re
from typing import Optional


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
    14: 'F', # Bruce Ferguson (no specific suffix)
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