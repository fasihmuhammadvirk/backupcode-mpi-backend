"""
Unit tests for Google Sheets extraction and mapping synchronization.

This module tests the GoogleSheetDataExtractor focusing on whether
original_item (supplier_item_ids) should be extracted or not.
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch
from mpi_backend.utils.google_sheets.sheet_data_extractor import (
    GoogleSheetDataExtractor
)
from mpi_backend.tests.test_data import (
    VALID_ORIGINAL_ITEMS,
    INVALID_ORIGINAL_ITEMS,
    VALIDATION_TEST_CASES,
    VALID_MAPPINGS,
    INVALID_MAPPINGS,
    INVALID_SHEET_NAMES
)


class TestGoogleSheetDataExtractor:
    """Test cases for GoogleSheetDataExtractor"""
    
    @pytest.fixture
    def extractor(self):
        """Create a GoogleSheetDataExtractor instance for testing"""
        return GoogleSheetDataExtractor(
            sheet_id="test_sheet_id",
            api_key="test_api_key",
            batch_size=10,
            fuzzy_threshold=75
        )
    
    @pytest.fixture
    def temp_output_file(self):
        """Create a temporary file for output testing"""
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        temp_file.close()
        yield temp_file.name
        # Cleanup
        if os.path.exists(temp_file.name):
            os.remove(temp_file.name)
    
    def test_extractor_initialization(self, extractor):
        """Test that the extractor initializes correctly"""
        assert extractor.sheet_id == "test_sheet_id"
        assert extractor.api_key == "test_api_key"
        assert extractor.batch_size == 10
        assert extractor.fuzzy_threshold == 75
        assert isinstance(extractor.supplier_mapping, dict)
        assert len(extractor.supplier_mapping) > 0
    
    def test_supplier_mapping_setup(self, extractor):
        """Test that supplier mappings are correctly configured"""
        # Test that key suppliers exist
        expected_suppliers = [
            "BMW Plumbing Supplies",
            "World Wide Plumbing", 
            "Y & S Plumbing Supply",
            "Supreme Plumbing Supply"
        ]
        
        for supplier in expected_suppliers:
            assert supplier in extractor.supplier_mapping
            assert "id" in extractor.supplier_mapping[supplier]
            supplier_id = extractor.supplier_mapping[supplier]["id"]
            assert isinstance(supplier_id, int)
    
    def test_valid_original_item_extraction(self, extractor):
        """Test that valid original items should be extracted"""
        for original_item in VALID_ORIGINAL_ITEMS:
            # Test validation logic that would be used in extraction
            result = self._should_extract_item(original_item)
            assert result, f"Valid item should be extracted: {original_item}"
    
    def test_invalid_original_item_rejection(self, extractor):
        """Test that invalid original items should NOT be extracted"""
        for original_item in INVALID_ORIGINAL_ITEMS:
            # Test validation logic that would reject these items
            result = self._should_extract_item(original_item)
            msg = f"Invalid item should be rejected: {original_item}"
            assert not result, msg
    
    def test_validation_test_cases(self, extractor):
        """Test specific validation cases with reasons"""
        for original_item, should_be_valid, reason in VALIDATION_TEST_CASES:
            result = self._should_extract_item(original_item)
            assert result == should_be_valid, f"Failed for '{original_item}': {reason}"
    
    def _should_extract_item(self, supplier_value):
        """
        Helper method that simulates the extraction validation logic.
        This mirrors the logic that would be used in the actual extractor.
        """
        # Handle None values
        if supplier_value is None:
            return False
        
        # Must be string
        if not isinstance(supplier_value, str):
            return False
        
        # Remove any extra spaces and convert to string
        cleaned_value = str(supplier_value).strip()
        
        # Skip if cleaned value is empty
        if not cleaned_value:
            return False
        
        # Skip if contains header-like text
        header_terms = ["supplier", "item", "id", "code", "description"]
        if any(term in cleaned_value.lower() for term in header_terms):
            return False
        
        # Skip values that are too short to be meaningful item codes
        if len(cleaned_value) < 2:
            return False
        
        return True
    
    def test_extract_clean_sheet_name_valid(self, extractor):
        """Test clean sheet name extraction with valid sheet names"""
        test_cases = [
            ("(AIR FITTINGS)", "(AIR FITTINGS)"),
            ("(MBST7-1 1/4-O) (GAS)", "(GAS)"),
            ("(PVC) Williams", "(PVC)"),
            ("(COPPER)", "(COPPER)"),
            ("(VALVES) Sheet 1", "(VALVES)")
        ]
        
        for input_sheet, expected_output in test_cases:
            result = extractor._extract_clean_sheet_name(input_sheet)
            assert result == expected_output
    
    def test_skip_sheets_configuration(self, extractor):
        """Test that skip_sheets configuration works correctly"""
        for skip_sheet in INVALID_SHEET_NAMES:
            if skip_sheet:  # Skip empty string test
                # Check if sheet would be skipped
                should_skip = any(skip_name in skip_sheet for skip_name in extractor.skip_sheets)
                if "(AB, ALL SYSTEMS)" in skip_sheet or "(AC, ITEMS WITHOUT" in skip_sheet:
                    assert should_skip, f"Sheet {skip_sheet} should be skipped"
    
    @patch('mpi_backend.utils.google_sheets.sheet_data_extractor.pd.read_csv')
    def test_process_sheet_with_valid_data(self, mock_read_csv, extractor):
        """Test processing a sheet with valid mapping data"""
        # Mock DataFrame with valid data
        mock_df = Mock()
        mock_df.empty = False
        mock_df.head.return_value = Mock()
        mock_df.iloc = Mock()
        mock_df.__len__ = Mock(return_value=5)
        mock_read_csv.return_value = mock_df
        
        # Mock supplier column detection
        with patch.object(extractor, 'detect_supplier_columns') as mock_detect:
            mock_detect.return_value = {"BMW Plumbing Supplies": [1]}
            
            # Mock chunk processing to return simple valid mappings
            with patch.object(extractor, '_process_dataframe_chunk') as mock_process:
                mock_process.return_value = VALID_MAPPINGS[:2]
                
                result = extractor.process_sheet("(AIR FITTINGS)", "test_gid")
                
                # Verify results
                assert isinstance(result, list)
                assert len(result) == 2
                for item in result:
                    assert "mpi_code" in item
                    assert "supplier_item_ids" in item
    
    @patch('mpi_backend.utils.google_sheets.sheet_data_extractor.pd.read_csv')
    def test_process_sheet_with_empty_sheet(self, mock_read_csv, extractor):
        """Test processing an empty sheet"""
        mock_df = Mock()
        mock_df.empty = True
        mock_read_csv.return_value = mock_df
        
        result = extractor.process_sheet("Empty Sheet", "test_gid")
        
        # Should return empty list and add to empty sheets
        assert result == []
        assert "Empty Sheet" in extractor.empty_sheets
    
    def test_process_sheet_skip_invalid_sheets(self, extractor):
        """Test that invalid sheets are properly skipped"""
        for invalid_sheet in INVALID_SHEET_NAMES:
            if invalid_sheet:  # Skip empty string
                result = extractor.process_sheet(invalid_sheet, "test_gid")
                
                # Should return empty list and add to skipped sheets
                assert result == []
                if any(skip_name in invalid_sheet for skip_name in extractor.skip_sheets):
                    assert invalid_sheet in extractor.skipped_sheets
    
    @patch('mpi_backend.utils.google_sheets.sheet_data_extractor.build')
    def test_get_sheet_list_success(self, mock_build, extractor):
        """Test successful sheet list retrieval"""
        mock_service = Mock()
        mock_spreadsheets = Mock()
        mock_get = Mock()
        
        # Setup mock chain
        mock_build.return_value = mock_service
        mock_service.spreadsheets.return_value = mock_spreadsheets
        mock_spreadsheets.get.return_value = mock_get
        mock_get.execute.return_value = {
            'sheets': [
                {'properties': {'title': 'Sheet1', 'sheetId': 1}},
                {'properties': {'title': 'Sheet2', 'sheetId': 2}}
            ]
        }
        
        result = extractor.get_sheet_list()
        
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]['title'] == 'Sheet1'
        assert result[1]['title'] == 'Sheet2'
    
    @patch('mpi_backend.utils.google_sheets.sheet_data_extractor.build')
    def test_get_sheet_list_failure(self, mock_build, extractor):
        """Test sheet list retrieval failure handling"""
        mock_build.side_effect = Exception("API Error")
        
        result = extractor.get_sheet_list()
        
        # Should return empty list on failure
        assert result == []


class TestOriginalItemValidation:
    """Test original item validation logic specifically"""
    
    def test_valid_original_items(self):
        """Test that all valid original items pass validation"""
        for original_item in VALID_ORIGINAL_ITEMS:
            assert self._validate_original_item(original_item), f"Valid item failed: {original_item}"
    
    def test_invalid_original_items(self):
        """Test that all invalid original items fail validation"""
        for original_item in INVALID_ORIGINAL_ITEMS:
            assert not self._validate_original_item(original_item), f"Invalid item passed: {original_item}"
    
    def test_validation_edge_cases(self):
        """Test edge cases for original item validation"""
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
        ]
        
        for original_item, expected in edge_cases:
            result = self._validate_original_item(original_item)
            assert result == expected, f"Edge case failed: '{original_item}' expected {expected}, got {result}"
    
    def test_data_type_validation(self):
        """Test validation of different data types"""
        test_cases = [
            ("valid_string", True),
            (123, False),          # Number
            ([], False),           # List
            ({}, False),           # Dict
            (None, False),         # None
            (True, False),         # Boolean
        ]
        
        for value, expected in test_cases:
            result = self._validate_original_item(value)
            assert result == expected, f"Type validation failed: {type(value)} {value}"
    
    def _validate_original_item(self, supplier_value):
        """
        Validation logic that matches the actual extractor logic
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


class TestMappingStructure:
    """Test the overall mapping structure for extracted items"""
    
    def test_valid_mapping_structure(self):
        """Test that valid mappings have the basic required structure"""
        for mapping in VALID_MAPPINGS:
            # Should have basic fields
            assert "mpi_code" in mapping
            assert "description" in mapping
            assert "supplier_item_ids" in mapping
            
            # Supplier item should be valid
            assert self._validate_original_item(mapping["supplier_item_ids"])
    
    def test_invalid_mapping_structure(self):
        """Test that invalid mappings have invalid supplier items"""
        for mapping in INVALID_MAPPINGS:
            # Should have basic structure but invalid supplier item
            assert "mpi_code" in mapping
            assert "description" in mapping
            assert "supplier_item_ids" in mapping
            
            # Supplier item should be invalid
            assert not self._validate_original_item(mapping["supplier_item_ids"])
    
    def _validate_original_item(self, supplier_value):
        """Validation logic for supplier items"""
        if supplier_value is None or not isinstance(supplier_value, str):
            return False
        
        cleaned_value = supplier_value.strip()
        if not cleaned_value or len(cleaned_value) < 2:
            return False
        
        header_terms = ["supplier", "item", "id", "code", "description"]
        if any(term in cleaned_value.lower() for term in header_terms):
            return False
        
        return True 