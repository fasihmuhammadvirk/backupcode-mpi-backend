"""
Test data for mapping functionality tests.

This module contains test data for validating Google Sheets extraction 
and mapping synchronization functionality. Focus is on testing whether
original_item (supplier_item_ids) should be extracted or not.
"""

# Valid original items that SHOULD be extracted
VALID_ORIGINAL_ITEMS = [
    "COMP-001",           # Standard item code
    "BV-100-1",          # Item with dashes and numbers
    "PVC250",            # Simple alphanumeric
    "CF075",             # Short but valid code
    "DRN-150",           # Another dash format
    "12345",             # Numeric item code
    "ABC123XYZ",         # Mixed alphanumeric
    "VALVE_001",         # Underscore format
    "PIPE.250",          # Dot format
    "FIT#123",           # Hash format
    "AB",                # Minimum valid length
    "98"                 # Minimum numeric valid
]

# Invalid original items that should NOT be extracted
INVALID_ORIGINAL_ITEMS = [
    "",                  # Empty string
    "   ",               # Only whitespace
    " ",                 # Single space
    "A",                 # Too short (single character)
    "1",                 # Single digit
    "supplier",          # Header-like text (lowercase)
    "SUPPLIER",          # Header-like text (uppercase)
    "item",              # Header-like text
    "ITEM",              # Header-like text
    "id",                # Header-like text
    "ID",                # Header-like text
    "code",              # Header-like text
    "CODE",              # Header-like text
    "description",       # Header-like text
    "DESCRIPTION",       # Header-like text
    "Item Code",         # Header with spaces
    "Supplier ID",       # Header with spaces
    "CODE123",           # Starts with header text
    "ITEM999",           # Starts with header text
    None,                # None value
    123,                 # Non-string type (number)
    [],                  # Non-string type (list)
    {}                   # Non-string type (dict)
]

# Simple valid mappings for testing extraction
VALID_MAPPINGS = [
    {
        "mpi_code": "TEST001",
        "description": "Test Item 1", 
        "supplier_item_ids": "COMP-001"
    },
    {
        "mpi_code": "TEST002",
        "description": "Test Item 2",
        "supplier_item_ids": "BV-100-1"
    },
    {
        "mpi_code": "TEST003", 
        "description": "Test Item 3",
        "supplier_item_ids": "PVC250"
    }
]

# Simple invalid mappings for testing rejection
INVALID_MAPPINGS = [
    {
        "mpi_code": "INVALID001",
        "description": "Invalid Item 1",
        "supplier_item_ids": ""  # Empty supplier item
    },
    {
        "mpi_code": "INVALID002", 
        "description": "Invalid Item 2",
        "supplier_item_ids": "   "  # Whitespace only
    },
    {
        "mpi_code": "INVALID003",
        "description": "Invalid Item 3", 
        "supplier_item_ids": "A"  # Too short
    },
    {
        "mpi_code": "INVALID004",
        "description": "Invalid Item 4",
        "supplier_item_ids": "supplier"  # Header-like text
    }
]

# Expected validation results
EXPECTED_VALID_COUNT = len(VALID_ORIGINAL_ITEMS)
EXPECTED_INVALID_COUNT = 0  # Invalid items should not be extracted

# Test cases for original item validation
VALIDATION_TEST_CASES = [
    # (original_item, should_be_valid, reason)
    ("COMP-001", True, "Standard item code format"),
    ("BV-100-1", True, "Alphanumeric with dashes"),
    ("PVC250", True, "Simple alphanumeric"),
    ("12345", True, "Numeric item code"),
    ("AB", True, "Minimum valid length"),
    ("", False, "Empty string"),
    ("   ", False, "Whitespace only"),
    ("A", False, "Too short - single character"),
    ("supplier", False, "Header-like text"),
    ("ITEM", False, "Header-like text"),
    ("Item Code", False, "Header with spaces"),
    ("CODE123", False, "Starts with header text"),
    (None, False, "None value"),
    (123, False, "Non-string type")
]

# Sheet names for testing
VALID_SHEET_NAMES = [
    "(AIR FITTINGS)",
    "(VALVES)", 
    "(PVC)",
    "(COPPER)",
    "(DRAINAGE)"
]

INVALID_SHEET_NAMES = [
    "(AB, ALL SYSTEMS)",  # Should be skipped
    "(AC, ITEMS WITHOUT TEMPORARY GROUP NAME)",  # Should be skipped
    ""  # Empty sheet name
] 