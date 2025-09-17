"""
Utility functions for item processing.
Suffix cleaning logic has been removed - all item codes now retain their full original form.
"""

from typing import Optional, Dict, Tuple

# Supplier ID to suffix mapping (for reference only)
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
    14: 'F',  # Bruce Ferguson
}

# Supplier name to suffix mapping (for reference only)
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


def get_supplier_suffix(supplier_id: int) -> Optional[str]:
    """Get suffix for a supplier ID (for reference only)."""
    return SUPPLIER_SUFFIX_MAP.get(supplier_id)


def get_supplier_suffix_by_name(supplier_name: str) -> Optional[str]:
    """Get suffix for a supplier name (for reference only)."""
    return SUPPLIER_NAME_SUFFIX_MAP.get(supplier_name)


def extract_supplier_id(vendor_name: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Extract supplier ID and name from vendor string.
    Returns (supplier_id, supplier_name)
    """
    if not vendor_name:
        return None, None
    
    # Try to match vendor name to supplier names
    for supplier_name in SUPPLIER_NAME_SUFFIX_MAP.keys():
        if supplier_name.lower() in vendor_name.lower():
            # Find the supplier ID for this name
            for sid, name in SUPPLIER_NAME_SUFFIX_MAP.items():
                if name == supplier_name:
                    return sid, supplier_name
    
    return None, None


def should_skip_item(item_code: str) -> bool:
    """Check if item should be skipped from processing (tax, freight, etc.)."""
    if not item_code:
        return True
    
    item_str = str(item_code).strip()
    
    # Exclude tax and administrative items
    excluded_items = [
        "tax", "freight", "shipping", "handling", "subtotal", "total"
    ]
    
    if (item_str.startswith("10 Materials") or 
            item_str.lower() in excluded_items):
        return True
    
    return False


def is_empty_or_invalid_item(item_code: str) -> bool:
    """
    Check if an item code is empty or invalid.
    
    Args:
        item_code (str): Item code to check
        
    Returns:
        bool: True if item is empty or invalid, False otherwise
    """
    if not item_code:
        return True
    
    if not isinstance(item_code, str):
        return True
    
    # Check if item is just whitespace
    if not item_code.strip():
        return True
    
    # Check if item is too short (likely invalid)
    if len(item_code.strip()) < 2:
        return True
    
    return False 