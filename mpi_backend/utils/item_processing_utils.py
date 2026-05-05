"""
Utility functions for item processing.
Suffix cleaning logic has been removed - all item codes now retain their full original form.

This module now uses centralized supplier_suffix_manager for all suffix operations.
"""

from typing import Optional, Tuple
from mpi_backend.utils.supplier_suffix_manager import (
    get_supplier_suffix,
    get_supplier_id_from_name,
    extract_supplier_info,
    SUPPLIER_SUFFIX_MAP,
    SUPPLIER_NAME_SUFFIX_MAP
)


def get_supplier_suffix_by_name(supplier_name: str) -> Optional[str]:
    """
    Get suffix for a supplier name.
    
    DEPRECATED: Use supplier_suffix_manager.get_supplier_suffix() instead.
    """
    supplier_id = get_supplier_id_from_name(supplier_name)
    if supplier_id is not None:
        return get_supplier_suffix(supplier_id=supplier_id)
    return None


def extract_supplier_id(vendor_name: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Extract supplier ID and name from vendor string.
    Returns (supplier_id, supplier_name)
    
    DEPRECATED: Use supplier_suffix_manager.extract_supplier_info() instead.
    """
    supplier_id, supplier_name, _ = extract_supplier_info(vendor_name)
    return supplier_id, supplier_name


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