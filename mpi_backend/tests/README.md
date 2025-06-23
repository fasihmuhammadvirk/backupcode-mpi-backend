# Testing Documentation

This directory contains unit tests for the MPI Backend mapping functionality. The tests focus on validating the core logic for extracting original items (supplier_item_ids) from Google Sheets.

## Test Structure

### Core Test Files

1. **`test_data.py`** - Test data definitions
   - `VALID_ORIGINAL_ITEMS`: Items that should be extracted
   - `INVALID_ORIGINAL_ITEMS`: Items that should be rejected
   - `VALIDATION_TEST_CASES`: Specific test cases with reasons
   - `VALID_MAPPINGS`: Simple valid mapping structures
   - `INVALID_MAPPINGS`: Simple invalid mapping structures

2. **`test_original_item_validation.py`** - Core validation tests
   - Tests the main validation logic for original items
   - Validates mapping structure requirements
   - No complex mocking or external dependencies

### Additional Test Files

3. **`test_google_sheets_extraction.py`** - Google Sheets extraction tests (with complex mocking)
4. **`test_mapping_sync_endpoint.py`** - API endpoint tests (with complex mocking)
5. **`test_runner.py`** - Test runner utility

## Running Tests

### Simple Validation Tests (Recommended)
```bash
# Run the core validation tests (fastest and most reliable)
python -m pytest tests/test_original_item_validation.py -v

# Run just the test data file to verify structure
python -c "from tests.test_data import VALID_ORIGINAL_ITEMS, INVALID_ORIGINAL_ITEMS; print('Valid:', len(VALID_ORIGINAL_ITEMS), 'Invalid:', len(INVALID_ORIGINAL_ITEMS))"
```

### All Tests
```bash
# Run all available tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_data.py -v
```

### Test Runner Script
```bash
# Use the test runner utility
python tests/test_runner.py
```

## Test Data Structure

### Valid Original Items
Items that **should be extracted**:
- `"COMP-001"` - Standard format with dashes
- `"PVC250"` - Alphanumeric codes
- `"AB"` - Minimum valid length (2 characters)
- `"12345"` - Numeric codes

### Invalid Original Items  
Items that **should be rejected**:
- `""` - Empty strings
- `"A"` - Too short (single character)
- `"supplier"` - Header-like text
- `"CODE123"` - Contains header terms
- `None` - Non-string types

## Validation Logic

The core validation logic checks:
1. **Type**: Must be a string
2. **Length**: Must be at least 2 characters after trimming
3. **Content**: Must not contain header-like terms (supplier, item, id, code, description)
4. **Not empty**: Must not be empty or whitespace-only

## Adding New Test Data

To add new test cases, simply update the lists in `test_data.py`:

```python
# Add to VALID_ORIGINAL_ITEMS for items that should be extracted
VALID_ORIGINAL_ITEMS.append("NEW-VALID-001")

# Add to INVALID_ORIGINAL_ITEMS for items that should be rejected  
INVALID_ORIGINAL_ITEMS.append("invalid_header_text")

# Add to VALIDATION_TEST_CASES for specific test cases with explanations
VALIDATION_TEST_CASES.append(("TEST-001", True, "Standard test format"))
```

## Focus

These tests are specifically designed to validate the core business logic of determining whether an original item (supplier_item_ids) should be extracted from Google Sheets or not. They avoid complex external dependencies and focus on the essential validation rules.

The validation ensures that only meaningful supplier item codes are extracted while filtering out:
- Empty/whitespace values
- Header text from spreadsheets
- Too-short values that aren't useful item codes
- Non-string data types 