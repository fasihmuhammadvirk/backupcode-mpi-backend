"""
WARNING: DEPRECATED. It's not clear how or where this should be used. We're keeping it to avoid breaking the app
but will remove when possible.

Centralized Supplier Suffix Management

This module provides a single source of truth for supplier suffix mappings.
All suffix-related operations should use this module instead of hardcoded mappings.

Database Integration:
- Primary source: suppliers table (suffix column)
- Fallback: In-memory mapping (for backward compatibility)

Usage:
    from mpi_backend.utils.supplier_suffix_manager import get_supplier_suffix
    
    suffix = get_supplier_suffix(supplier_id=1)  # Returns 'B'
    suffix = get_supplier_suffix(supplier_name="BMW Plumbing Supplies")  # Returns 'B'
"""

import logging
from typing import Optional, Dict, Tuple, List
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Unknown Supplier constants
# TO BE DEPRECATED, import from mpi_backend/database/controllers/Suppliers.py if needed
UNKNOWN_SUPPLIER_ID = 0
UNKNOWN_SUPPLIER_NAME = "Unknown Supplier"


def get_unknown_supplier() -> Tuple[int, str]:
    """
    Get the default unknown supplier ID and name.

    Use this function when a supplier cannot be identified from
    invoice data, file paths, or other sources. This replaces the
    previous behavior of defaulting to BMW Plumbing Supplies (ID 1).

    Returns:
        Tuple of (supplier_id, supplier_name) for Unknown Supplier
    """
    return UNKNOWN_SUPPLIER_ID, UNKNOWN_SUPPLIER_NAME


# Fallback mapping (used when database is unavailable)
# This is the SINGLE SOURCE OF TRUTH for suffix mappings
# Note: Only includes suppliers that exist in the database (IDs 0-13)
# Bruce (14) and Ferguson (15) do NOT exist in public.suppliers table
_FALLBACK_SUFFIX_MAP = {
    0: None,   # Unknown Supplier (no suffix)
    1: 'B',    # BMW Plumbing Supplies
    2: 'W',    # World Wide Plumbing
    3: 'Y',    # Y & S Plumbing Supply
    4: 'S',    # Supreme Plumbing Supply
    5: 'P',    # Pyramid Plumbing
    6: 'A',    # ABC Opus Services
    7: 'P',    # Park Plumbing Supply (same as Pyramid)
    8: 'G',    # Gotham Plumbing Supply
    9: 'F',    # FW Webb Plumbing Supply
    10: 'F',   # Flow Mark Plumbing Supply (same as FW Webb)
    11: 'PE',  # Plumbing Exchange
    12: 'A',   # AF Supply (same as ABC Opus)
    13: None,  # Lion Hvac Supplies (no suffix)
}

# Supplier name to ID mapping
# Note: Only includes suppliers that exist in the database (IDs 0-13)
_SUPPLIER_NAME_TO_ID = {
    "Unknown Supplier": 0,
    "BMW Plumbing Supplies": 1,
    "World Wide Plumbing": 2,
    "Y & S Plumbing Supply": 3,
    "Supreme Plumbing Supply": 4,
    "Pyramid Plumbing": 5,
    "ABC Opus Services": 6,
    "Park Plumbing Supply": 7,
    "Gotham Plumbing Supply": 8,
    "FW Webb Plumbing Supply": 9,
    "Flow Mark Plumbing Supply": 10,
    "Plumbing Exchange": 11,
    "AF Supply": 12,
    "Lion Hvac Supplies": 13,
}


def get_supplier_suffix(
    supplier_id: Optional[int] = None,
    supplier_name: Optional[str] = None,
    db: Optional[Session] = None,
    with_dash: bool = False
) -> Optional[str]:
    """
    Get suffix for a supplier from database or fallback mapping.
    
    Args:
        supplier_id: Supplier ID (primary lookup method)
        supplier_name: Supplier name (alternative lookup method)
        db: Database session (optional, for database lookup)
        with_dash: If True, returns suffix with dash prefix (e.g., '-B' instead of 'B')
        
    Returns:
        Suffix string (e.g., 'B', 'W') or None if no suffix
        
    Examples:
        >>> get_supplier_suffix(supplier_id=1)
        'B'
        >>> get_supplier_suffix(supplier_id=1, with_dash=True)
        '-B'
        >>> get_supplier_suffix(supplier_name="BMW Plumbing Supplies")
        'B'
        >>> get_supplier_suffix(supplier_id=11)  # Plumbing Exchange
        'PE'
    """
    # If supplier_name provided but no ID, try to resolve ID
    if supplier_name and supplier_id is None:
        supplier_id = get_supplier_id_from_name(supplier_name)
    
    if supplier_id is None:
        return None

    # Try database first if session provided
    suffix = None
    if db:
        try:
            suffix = _get_suffix_from_database(db, supplier_id)
        except Exception as e:
            logger.warning(
                f"Failed to get suffix from database for supplier {supplier_id}: {e}")
    
    # Fallback to in-memory mapping
    if suffix is None:
        suffix = _FALLBACK_SUFFIX_MAP.get(supplier_id)
    
    # Add dash prefix if requested
    if suffix and with_dash:
        return f"-{suffix}"
    
    return suffix


def get_supplier_id_from_name(supplier_name: str) -> Optional[int]:
    """
    Get supplier ID from supplier name using conservative matching strategy.
    
    Matching Strategy (in order of priority):
    1. Exact match: "BMW Plumbing Supplies" → BMW
    2. Substring match with full supplier name: "Invoice from BMW Plumbing Supplies" → BMW
    3. No match: Returns None
    
    Args:
        supplier_name: Full or partial supplier name
        
    Returns:
        Supplier ID or None if not found
        
    Examples:
        >>> get_supplier_id_from_name("BMW Plumbing Supplies")
        1
        >>> get_supplier_id_from_name("Invoice from BMW Plumbing Supplies")
        1
        >>> get_supplier_id_from_name("Central Park Plumbing")
        None  # Won't incorrectly match "Park Plumbing Supply"
    """
    if not supplier_name:
        return None
    
    supplier_name_lower = supplier_name.lower().strip()
    
    # Strategy 1: Try exact match first (highest confidence)
    for name, supplier_id in _SUPPLIER_NAME_TO_ID.items():
        if name.lower() == supplier_name_lower:
            logger.debug(f"Exact match: '{supplier_name}' → '{name}' (ID: {supplier_id})")
            return supplier_id
    
    # Strategy 2: Try substring match where FULL supplier name appears in input
    # This is safe because we're looking for the complete supplier name as a substring
    # "Invoice from BMW Plumbing Supplies" contains "BMW Plumbing Supplies" ✓
    # "Central Park Plumbing" does NOT contain "Park Plumbing Supply" ✓
    for name, supplier_id in _SUPPLIER_NAME_TO_ID.items():
        if name.lower() in supplier_name_lower:
            logger.debug(
                f"Substring match: '{supplier_name}' contains '{name}' (ID: {supplier_id})")
            return supplier_id
    
    # No match found
    logger.debug(f"No supplier match found for: '{supplier_name}'")
    return None


def get_all_supplier_suffixes(db: Optional[Session] = None) -> Dict[int, Optional[str]]:
    """
    Get all supplier suffix mappings.
    
    Args:
        db: Database session (optional)
        
    Returns:
        Dictionary mapping supplier_id to suffix
    """
    if db:
        try:
            return _get_all_suffixes_from_database(db)
        except Exception as e:
            logger.warning(f"Failed to get suffixes from database: {e}")
    
    return _FALLBACK_SUFFIX_MAP.copy()


def extract_supplier_info(vendor_name: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Extract supplier ID, name, and suffix from vendor string.
    
    Args:
        vendor_name: Vendor name string (e.g., "BMW Plumbing Supplies - Invoice #123")
        
    Returns:
        Tuple of (supplier_id, supplier_name, suffix)
        
    Examples:
        >>> extract_supplier_info("BMW Plumbing Supplies - Invoice #123")
        (1, "BMW Plumbing Supplies", "B")
    """
    if not vendor_name:
        return None, None, None
    
    supplier_id = get_supplier_id_from_name(vendor_name)
    if supplier_id is None:
        return None, None, None
    
    # Get the full supplier name
    supplier_name = None
    for name, sid in _SUPPLIER_NAME_TO_ID.items():
        if sid == supplier_id:
            supplier_name = name
            break
    
    suffix = get_supplier_suffix(supplier_id=supplier_id)

    return supplier_id, supplier_name, suffix


def get_supplier_name_from_id(supplier_id: int) -> Optional[str]:
    """
    Get supplier name from supplier ID (reverse lookup).

    Args:
        supplier_id: The supplier's database ID

    Returns:
        Supplier name or None if not found

    Examples:
        >>> get_supplier_name_from_id(1)
        'BMW Plumbing Supplies'
        >>> get_supplier_name_from_id(0)
        'Unknown Supplier'
        >>> get_supplier_name_from_id(999)
        None
    """
    for name, sid in _SUPPLIER_NAME_TO_ID.items():
        if sid == supplier_id:
            return name
    return None


def get_all_supplier_names() -> List[str]:
    """
    Get list of all supplier names.

    This replaces the SUPPLIERS array from config/__init__.py.
    The order matches the original SUPPLIERS array for backward compatibility.

    Returns:
        List of supplier names in order by ID (excluding Unknown Supplier at ID 0)

    Examples:
        >>> names = get_all_supplier_names()
        >>> names[0]
        'BMW Plumbing Supplies'
        >>> names[1]
        'World Wide Plumbing'
    """
    # Sort by ID and exclude Unknown Supplier (ID 0)
    sorted_suppliers = sorted(
        [(sid, name) for name, sid in _SUPPLIER_NAME_TO_ID.items() if sid > 0],
        key=lambda x: x[0]
    )
    return [name for _, name in sorted_suppliers]


def get_processable_supplier_names() -> List[str]:
    """
    Get list of processable supplier names.

    This replaces PROCESSABLE_SUPPLIERS from config/__init__.py.
    Returns all known suppliers excluding Unknown Supplier.

    Unlike get_all_supplier_names(), this function explicitly filters
    out Unknown Supplier by name for clarity and future-proofing.

    Returns:
        List of supplier names that can be processed
    """
    return [
        name for name in get_all_supplier_names()
        if name != UNKNOWN_SUPPLIER_NAME
    ]


def _get_suffix_from_database(db: Session, supplier_id: int) -> Optional[str]:
    """Get suffix from database suppliers table."""
    from mpi_backend.database.models.Suppliers import Supplier
    from sqlalchemy import inspect
    
    # Check if suffix column exists in the table
    mapper = inspect(Supplier)
    if 'suffix' not in [col.key for col in mapper.columns]:
        return None
    
    # Query only id and suffix columns to avoid errors if suffix doesn't exist
    result = db.query(Supplier.id, Supplier.suffix).filter(Supplier.id == supplier_id).first()
    if result:
        return result[1]  # suffix is the second element
    
    return None


def _get_all_suffixes_from_database(db: Session) -> Dict[int, Optional[str]]:
    """Get all suffixes from database suppliers table."""
    from mpi_backend.database.models.Suppliers import Supplier
    from sqlalchemy import inspect
    
    # Check if suffix column exists in the table
    mapper = inspect(Supplier)
    if 'suffix' not in [col.key for col in mapper.columns]:
        # Fallback if suffix column doesn't exist yet
        return _FALLBACK_SUFFIX_MAP.copy()
    
    # Query only id and suffix columns
    suppliers = db.query(Supplier.id, Supplier.suffix).all()
    suffix_map = {}
    
    for supplier_id, suffix in suppliers:
        suffix_map[supplier_id] = suffix if suffix else _FALLBACK_SUFFIX_MAP.get(supplier_id)
    
    return suffix_map


# Backward compatibility exports
SUPPLIER_SUFFIX_MAP = _FALLBACK_SUFFIX_MAP
SUPPLIER_NAME_SUFFIX_MAP = {
    name: _FALLBACK_SUFFIX_MAP.get(sid)
    for name, sid in _SUPPLIER_NAME_TO_ID.items()
}

