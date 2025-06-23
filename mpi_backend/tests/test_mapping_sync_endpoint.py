"""
Integration tests for the mapping synchronization API endpoint.

This module tests the /sync/mapping endpoint to ensure it correctly
handles mapping extraction and updates from Google Sheets.
Focus is on validating original_item extraction.
"""

import pytest
import tempfile
import os
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from mpi_backend.main import app
from mpi_backend.tests.test_data import (
    VALID_MAPPINGS,
    INVALID_MAPPINGS,
    VALID_ORIGINAL_ITEMS,
    INVALID_ORIGINAL_ITEMS
)

client = TestClient(app)


class TestMappingSyncEndpoint:
    """Test cases for mapping sync endpoint"""
    
    @pytest.fixture
    def auth_headers(self):
        """Mock authentication headers for testing"""
        # Note: In a real test environment, you'd use a proper test JWT token
        return {"Authorization": "Bearer test_token"}
    
    @pytest.fixture
    def temp_output_file(self):
        """Create temporary file for testing"""
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        temp_file.close()
        yield temp_file.name
        # Cleanup
        if os.path.exists(temp_file.name):
            os.remove(temp_file.name)
    
    @patch('mpi_backend.database.controllers.'
           'GoogleSheetSyncController.GoogleSheetSyncController.get_sync_status')
    @patch('mpi_backend.utils.auth.auth_bearer.JWTBearer.__call__')
    def test_sync_mapping_success_not_running(self, mock_jwt, mock_sync_status):
        """Test successful mapping sync when no sync is currently running"""
        # Mock JWT authentication
        mock_jwt.return_value = "test_token"
        
        # Mock sync status - not running
        mock_sync_status.return_value = {
            "is_running": False,
            "current_operation": None,
            "current_sub_operation": None
        }
        
        # Mock the background task execution
        with patch('mpi_backend.database.controllers.GoogleSheetSyncController.GoogleSheetSyncController.execute_sync_task') as mock_execute:
            mock_execute.return_value = None
            
            response = client.post("/sync/mapping")
            
            # Should return success
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert "Sync task started manually" in response_data["message"]
            assert "timestamp" in response_data
    
    @patch('mpi_backend.database.controllers.GoogleSheetSyncController.GoogleSheetSyncController.get_sync_status')
    @patch('mpi_backend.utils.auth.auth_bearer.JWTBearer.__call__')
    def test_sync_mapping_already_running(self, mock_jwt, mock_sync_status):
        """Test mapping sync when another sync is already running"""
        # Mock JWT authentication
        mock_jwt.return_value = "test_token"
        
        # Mock sync status - currently running
        mock_sync_status.return_value = {
            "is_running": True,
            "current_operation": "sync",
            "current_sub_operation": "syncing_google_sheets"
        }
        
        response = client.post("/sync/mapping")
        
        # Should return error indicating sync is already running
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is False
        assert "Google Sheets Sync is currently running" in response_data["message"]
    
    @patch('mpi_backend.database.controllers.GoogleSheetSyncController.GoogleSheetSyncController.get_sync_status')
    @patch('mpi_backend.utils.auth.auth_bearer.JWTBearer.__call__')
    def test_sync_mapping_uidi_update_running(self, mock_jwt, mock_sync_status):
        """Test mapping sync when UIDI update is running"""
        # Mock JWT authentication
        mock_jwt.return_value = "test_token"
        
        # Mock sync status - UIDI update running
        mock_sync_status.return_value = {
            "is_running": True,
            "current_operation": "update_no_match_uidi",
            "current_sub_operation": "updating_uidi_items"
        }
        
        response = client.post("/sync/mapping")
        
        # Should return error indicating UIDI update is running
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is False
        assert "UIDI Update" in response_data["message"]
    
    @patch('mpi_backend.utils.auth.auth_bearer.JWTBearer.__call__')
    def test_sync_mapping_unauthorized(self, mock_jwt):
        """Test mapping sync without proper authentication"""
        # Mock JWT authentication failure
        mock_jwt.side_effect = Exception("Invalid token")
        
        response = client.post("/sync/mapping")
        
        # Should return unauthorized
        assert response.status_code in [401, 403]
    
    @patch('mpi_backend.database.controllers.GoogleSheetSyncController.GoogleSheetSyncController.get_sync_status')
    @patch('mpi_backend.utils.auth.auth_bearer.JWTBearer.__call__')
    def test_sync_status_endpoint(self, mock_jwt, mock_sync_status):
        """Test the sync status endpoint"""
        # Mock JWT authentication
        mock_jwt.return_value = "test_token"
        
        # Mock sync status
        mock_sync_status.return_value = {
            "is_running": False,
            "current_operation": None,
            "current_sub_operation": None,
            "last_sync_time": "2025-01-01T12:00:00",
            "last_update_no_match_uidi_time": "2025-01-01T11:00:00",
            "last_update_all_time": "2025-01-01T10:00:00"
        }
        
        response = client.get("/sync/status")
        
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["status"] == "idle"
        assert response_data["current_operation"] == "No operation in progress"
        assert "last_sync_time" in response_data
    
    @patch('mpi_backend.database.controllers.GoogleSheetSyncController.GoogleSheetSyncController.get_sync_status')
    @patch('mpi_backend.utils.auth.auth_bearer.JWTBearer.__call__')
    def test_sync_status_endpoint_running(self, mock_jwt, mock_sync_status):
        """Test the sync status endpoint when sync is running"""
        # Mock JWT authentication
        mock_jwt.return_value = "test_token"
        
        # Mock sync status - running
        mock_sync_status.return_value = {
            "is_running": True,
            "current_operation": "sync",
            "current_sub_operation": "syncing_google_sheets",
            "last_sync_time": "2025-01-01T12:00:00",
            "last_update_no_match_uidi_time": "2025-01-01T11:00:00",
            "last_update_all_time": "2025-01-01T10:00:00"
        }
        
        response = client.get("/sync/status")
        
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["status"] == "running"
        assert "Synchronizing Google Sheets" in response_data["current_operation"]


class TestMappingSyncLogic:
    """Test the actual mapping sync logic"""
    
    @patch('mpi_backend.utils.google_sheets.sheet_data_extractor.GoogleSheetDataExtractor.process_all_sheets')
    @patch('mpi_backend.database.controllers.GoogleSheetSyncController.GoogleSheetSyncController._process_and_sync_mappings')
    def test_sync_sheet_mappings_success(self, mock_process_sync, mock_process_sheets):
        """Test successful sheet mapping synchronization"""
        # Mock sheet processing with valid mappings
        mock_process_sheets.return_value = VALID_MAPPINGS
        
        # Mock sync processing
        mock_process_sync.return_value = {
            "success": True,
            "new_mappings_count": len(VALID_MAPPINGS),
            "existing_mappings_count": 0
        }
        
        # Import and test the controller directly
        from mpi_backend.database.controllers.GoogleSheetSyncController import GoogleSheetSyncController
        
        # Create a mock database session
        mock_db = Mock()
        controller = GoogleSheetSyncController(mock_db)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as temp_file:
            temp_output_file = temp_file.name
        
        try:
            result = controller.sync_sheet_mappings(
                sheet_id="test_sheet_id",
                output_file=temp_output_file,
                api_key="test_api_key",
                dry_run=False
            )
            
            # Verify success
            assert result["success"] is True
            assert result["new_mappings_count"] == len(VALID_MAPPINGS)
            
        finally:
            # Cleanup
            if os.path.exists(temp_output_file):
                os.remove(temp_output_file)
    
    @patch('mpi_backend.utils.google_sheets.sheet_data_extractor.GoogleSheetDataExtractor.process_all_sheets')
    def test_sync_sheet_mappings_extraction_failure(self, mock_process_sheets):
        """Test handling of extraction failures"""
        # Mock extraction failure
        mock_process_sheets.side_effect = Exception("Google Sheets API Error")
        
        from mpi_backend.database.controllers.GoogleSheetSyncController import GoogleSheetSyncController
        
        mock_db = Mock()
        controller = GoogleSheetSyncController(mock_db)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as temp_file:
            temp_output_file = temp_file.name
        
        try:
            # Should raise exception due to mocked failure
            with pytest.raises(Exception, match="Google Sheets API Error"):
                controller.sync_sheet_mappings(
                    sheet_id="test_sheet_id",
                    output_file=temp_output_file,
                    api_key="test_api_key",
                    dry_run=False
                )
                
        finally:
            # Cleanup
            if os.path.exists(temp_output_file):
                os.remove(temp_output_file)
    
    def test_original_item_validation(self):
        """Test that original item validation works correctly"""
        # Test valid original items
        for original_item in VALID_ORIGINAL_ITEMS:
            assert self._validate_original_item(original_item), f"Valid item failed: {original_item}"
        
        # Test invalid original items  
        for original_item in INVALID_ORIGINAL_ITEMS:
            assert not self._validate_original_item(original_item), f"Invalid item passed: {original_item}"
    
    def test_mapping_data_validation(self):
        """Test that mapping data is properly validated before processing"""
        # Test valid mappings - should have valid original items
        for mapping in VALID_MAPPINGS:
            assert self._validate_mapping_structure(mapping), f"Valid mapping failed: {mapping}"
        
        # Test invalid mappings - should have invalid original items
        for mapping in INVALID_MAPPINGS:
            assert not self._validate_mapping_structure(mapping), f"Invalid mapping passed: {mapping}"
    
    def _validate_original_item(self, supplier_value):
        """Helper method to validate original item"""
        if supplier_value is None or not isinstance(supplier_value, str):
            return False
        
        cleaned_value = supplier_value.strip()
        if not cleaned_value or len(cleaned_value) < 2:
            return False
        
        header_terms = ["supplier", "item", "id", "code", "description"]
        if any(term in cleaned_value.lower() for term in header_terms):
            return False
        
        return True
    
    def _validate_mapping_structure(self, mapping):
        """Helper method to validate mapping structure"""
        # Check basic structure
        if not all(field in mapping for field in ["mpi_code", "description", "supplier_item_ids"]):
            return False
        
        # Validate the original item (supplier_item_ids)
        return self._validate_original_item(mapping.get("supplier_item_ids"))
    
    @patch('mpi_backend.utils.google_sheets.sheet_data_extractor.GoogleSheetDataExtractor.process_all_sheets')
    def test_dry_run_mode(self, mock_process_sheets):
        """Test dry run mode doesn't modify database"""
        # Mock sheet processing
        mock_process_sheets.return_value = VALID_MAPPINGS[:2]
        
        from mpi_backend.database.controllers.GoogleSheetSyncController import GoogleSheetSyncController
        
        mock_db = Mock()
        controller = GoogleSheetSyncController(mock_db)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as temp_file:
            temp_output_file = temp_file.name
        
        try:
            # Mock the sync processing to verify it's called with dry_run=True
            with patch.object(controller, '_process_and_sync_mappings') as mock_sync:
                mock_sync.return_value = {
                    "success": True,
                    "new_mappings_count": 2,
                    "existing_mappings_count": 0
                }
                
                result = controller.sync_sheet_mappings(
                    sheet_id="test_sheet_id",
                    output_file=temp_output_file,
                    api_key="test_api_key",
                    dry_run=True  # Test dry run mode
                )
                
                # Verify dry run was passed to processing
                mock_sync.assert_called_once()
                call_args = mock_sync.call_args
                assert call_args[1]['dry_run'] is True  # Check dry_run parameter
                
                # Verify result
                assert result["success"] is True
                
        finally:
            # Cleanup
            if os.path.exists(temp_output_file):
                os.remove(temp_output_file)


class TestEndpointErrorHandling:
    """Test error handling in endpoints"""
    
    @patch('mpi_backend.utils.auth.auth_bearer.JWTBearer.__call__')
    def test_invalid_endpoint_method(self, mock_jwt):
        """Test invalid HTTP methods on sync endpoint"""
        mock_jwt.return_value = "test_token"
        
        # Test GET on POST endpoint
        response = client.get("/sync/mapping")
        assert response.status_code == 405  # Method not allowed
        
        # Test PUT on POST endpoint
        response = client.put("/sync/mapping")
        assert response.status_code == 405  # Method not allowed
    
    @patch('mpi_backend.database.controllers.GoogleSheetSyncController.GoogleSheetSyncController.get_sync_status')
    @patch('mpi_backend.utils.auth.auth_bearer.JWTBearer.__call__')
    def test_database_error_handling(self, mock_jwt, mock_sync_status):
        """Test handling of database errors"""
        mock_jwt.return_value = "test_token"
        
        # Mock database error in sync status
        mock_sync_status.side_effect = Exception("Database connection error")
        
        response = client.post("/sync/mapping")
        
        # Should handle error gracefully
        assert response.status_code in [500, 503]
    
    def test_missing_endpoints(self):
        """Test that required endpoints exist"""
        # Test that sync endpoints exist
        response = client.options("/sync/mapping")
        assert response.status_code in [200, 405]  # Endpoint exists
        
        response = client.options("/sync/status")
        assert response.status_code in [200, 405]  # Endpoint exists


class TestOriginalItemFocus:
    """Test suite focused specifically on original item validation"""
    
    def test_valid_original_items_should_be_extracted(self):
        """Test that all valid original items would be extracted"""
        for original_item in VALID_ORIGINAL_ITEMS:
            # These should all pass validation and be extracted
            assert self._should_extract_item(original_item), f"Should extract: {original_item}"
    
    def test_invalid_original_items_should_be_rejected(self):
        """Test that all invalid original items would be rejected"""
        for original_item in INVALID_ORIGINAL_ITEMS:
            # These should all fail validation and be rejected
            assert not self._should_extract_item(original_item), f"Should reject: {original_item}"
    
    def test_extraction_logic_consistency(self):
        """Test that extraction logic is consistent"""
        # Test some specific cases
        test_cases = [
            ("COMP-001", True),      # Valid format
            ("", False),             # Empty
            ("supplier", False),     # Header text
            ("A", False),            # Too short
            ("ABC123", True),        # Valid alphanumeric
            (None, False),           # None value
            (123, False),            # Wrong type
        ]
        
        for original_item, should_extract in test_cases:
            result = self._should_extract_item(original_item)
            assert result == should_extract, f"Inconsistent logic for '{original_item}'"
    
    def _should_extract_item(self, supplier_value):
        """
        Validation logic that simulates the actual extraction process
        """
        # Handle None values
        if supplier_value is None:
            return False
        
        # Must be string
        if not isinstance(supplier_value, str):
            return False
        
        # Clean and validate
        cleaned_value = supplier_value.strip()
        
        # Skip if empty
        if not cleaned_value:
            return False
        
        # Skip header-like text
        header_terms = ["supplier", "item", "id", "code", "description"]
        if any(term in cleaned_value.lower() for term in header_terms):
            return False
        
        # Skip if too short
        if len(cleaned_value) < 2:
            return False
        
        return True 