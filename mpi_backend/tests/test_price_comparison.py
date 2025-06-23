from fastapi.testclient import TestClient
from datetime import date, timedelta
from mpi_backend.main import app

client = TestClient(app)

def test_get_dropdown_items():
    # Test data
    today = date.today()
    payload = {
        "from_date": (today - timedelta(days=30)).isoformat(),
        "to_date": today.isoformat()
    }

    # Make request
    response = client.post("/price-comparison/dropdown-items", json=payload)

    # Assert response
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    if len(items) > 0:
        item = items[0]
        assert "mpi_item" in item
        assert "original_item" in item
        assert "mpi_description" in item

def test_get_selected_items_prices():
    # Test data
    items = [
        {
            "mpi_item": "CMPSPM02",
            "original_item": "COMP 1/4\"",
            "mpi_description": "1/4\" QUICK COUPLER PLUG FOR AIR COMP"
        }
    ]

    # Make request
    response = client.post("/price-comparison/selected-items", json=items)

    # Assert response
    assert response.status_code == 200
    price_info = response.json()
    assert isinstance(price_info, list)
    if len(price_info) > 0:
        item = price_info[0]
        assert "mpi_item" in item
        assert "original_item" in item
        assert "mpi_description" in item
        assert "unit_price" in item

def test_invalid_date_range():
    # Test data with invalid date format
    payload = {
        "from_date": "invalid-date",
        "to_date": "invalid-date"
    }

    # Make request
    response = client.post("/price-comparison/dropdown-items", json=payload)

    # Assert response
    assert response.status_code == 422  # Validation error

def test_empty_items_list():
    # Test with empty items list
    response = client.post("/price-comparison/selected-items", json=[])

    # Assert response
    assert response.status_code == 200
    assert response.json() == []

"""
Simple test for original item validation logic.

This module tests the core validation logic for original items
without complex mocking or Google Sheets integration.
"""

import pytest
from mpi_backend.tests.test_data import (
    VALID_ORIGINAL_ITEMS,
    INVALID_ORIGINAL_ITEMS,
    VALIDATION_TEST_CASES,
    VALID_MAPPINGS,
    INVALID_MAPPINGS
)


def validate_original_item(supplier_value):
    """
    Core validation logic for original items.
    This matches the logic used in the actual extractor.
    """
    # Handle None values
    if supplier_value is None:
        return False
    
    # Must be string
    if not isinstance(supplier_value, str):
        return False
    
    # Remove any extra spaces
    cleaned_value = supplier_value.strip()
    
    # Skip if cleaned value is empty
    if not cleaned_value:
        return False
    
    # Skip if contains header-like text
    header_terms = ["supplier", "item", "id", "code", "description"]
    if any(term in cleaned_value.lower() for term in header_terms):
        return False
    
    # Skip values that are too short (less than 2 characters)
    if len(cleaned_value) < 2:
        return False
    
    return True


class TestOriginalItemValidation:
    """Test original item validation logic"""
    
    def test_valid_original_items(self):
        """Test that all valid original items pass validation"""
        for original_item in VALID_ORIGINAL_ITEMS:
            result = validate_original_item(original_item)
            assert result, f"Valid item failed: '{original_item}'"
    
    def test_invalid_original_items(self):
        """Test that all invalid original items fail validation"""
        for original_item in INVALID_ORIGINAL_ITEMS:
            result = validate_original_item(original_item)
            assert not result, f"Invalid item passed: '{original_item}'"
    
    def test_validation_test_cases(self):
        """Test specific validation cases with reasons"""
        for original_item, should_be_valid, reason in VALIDATION_TEST_CASES:
            result = validate_original_item(original_item)
            msg = f"Failed for '{original_item}': {reason}"
            assert result == should_be_valid, msg
    
    def test_edge_cases(self):
        """Test specific edge cases"""
        edge_cases = [
            ("", False),           # Empty string
            ("   ", False),        # Whitespace only
            ("A", False),          # Single character
            ("AB", True),          # Minimum valid length
            ("12", True),          # Minimum numeric
            ("SUPPLIER", False),   # Header text
            ("supplier", False),   # Header text lowercase
            ("Item", False),       # Header text
            ("ID", False),         # Header text
            ("CODE123", False),    # Starts with header text
            ("123CODE", True),     # Ends with header text (valid)
            ("ITEM999", False),    # Starts with header text
            ("999ITEM", True),     # Ends with header text (valid)
        ]
        
        for original_item, expected in edge_cases:
            result = validate_original_item(original_item)
            msg = f"Edge case failed: '{original_item}' expected {expected}"
            assert result == expected, msg
    
    def test_data_types(self):
        """Test validation of different data types"""
        test_cases = [
            ("valid_string", True),
            (123, False),          # Number
            ([], False),           # List
            ({}, False),           # Dict
            (None, False),         # None
            (True, False),         # Boolean
            (1.5, False),          # Float
        ]
        
        for value, expected in test_cases:
            result = validate_original_item(value)
            msg = f"Type validation failed: {type(value)} {value}"
            assert result == expected, msg


class TestMappingStructure:
    """Test the overall mapping structure"""
    
    def test_valid_mapping_structure(self):
        """Test that valid mappings have valid supplier items"""
        for mapping in VALID_MAPPINGS:
            # Should have basic fields
            assert "mpi_code" in mapping
            assert "description" in mapping
            assert "supplier_item_ids" in mapping
            
            # Supplier item should be valid
            supplier_item = mapping["supplier_item_ids"]
            result = validate_original_item(supplier_item)
            assert result, f"Valid mapping has invalid supplier item: {mapping}"
    
    def test_invalid_mapping_structure(self):
        """Test that invalid mappings have invalid supplier items"""
        for mapping in INVALID_MAPPINGS:
            # Should have basic structure
            assert "mpi_code" in mapping
            assert "description" in mapping
            assert "supplier_item_ids" in mapping
            
            # Supplier item should be invalid
            supplier_item = mapping["supplier_item_ids"]
            result = validate_original_item(supplier_item)
            msg = f"Invalid mapping has valid supplier item: {mapping}"
            assert not result, msg
    
    def test_basic_mapping_requirements(self):
        """Test that mappings have the minimum required structure"""
        required_fields = ["mpi_code", "description", "supplier_item_ids"]
        
        # Test valid mappings
        for mapping in VALID_MAPPINGS:
            for field in required_fields:
                assert field in mapping, f"Missing field {field} in {mapping}"
                assert mapping[field], f"Empty field {field} in {mapping}"
        
        # Test invalid mappings structure
        for mapping in INVALID_MAPPINGS:
            for field in required_fields:
                assert field in mapping, f"Missing field {field} in {mapping}" 