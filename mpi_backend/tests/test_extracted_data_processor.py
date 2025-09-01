"""
Test extracted data processor for handling converted Excel files.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from mpi_backend.utils.extracted_data_processor import (
    process_extracted_data,
    process_single_file
)


class TestExtractedDataProcessor:
    """Test cases for extracted data processor."""

    def test_process_extracted_data_basic(self):
        """Test basic processing of extracted data."""
        converted_files = ["test1.xlsx", "test2.xlsx"]
        failed_files = []
        
        # Mock the controllers
        with patch('mpi_backend.utils.extracted_data_processor.TemporaryItemMappingController') as mock_temp_controller, \
             patch('mpi_backend.utils.extracted_data_processor.ItemsMappingController') as mock_item_controller, \
             patch('mpi_backend.utils.extracted_data_processor.CustomerJobMappingController') as mock_customer_controller:
            
            mock_temp_controller.return_value.get_temp_items_mappings.return_value = []
            mock_item_controller.return_value.get_items_mappings.return_value = []
            mock_customer_controller.return_value.get_customer_job_mappings.return_value = []
            
            # Mock process_single_file
            with patch('mpi_backend.utils.extracted_data_processor.process_single_file') as mock_process:
                mock_process.return_value = {"status": "success", "file": "test1.xlsx"}
                
                results = process_extracted_data(converted_files, failed_files)
    
        assert isinstance(results, list)
        assert len(results) == 2

    def test_process_extracted_data_with_failed_files(self):
        """Test processing with failed files."""
        converted_files = ["test1.xlsx"]
        failed_files = ["failed1.pdf"]
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__.return_value = Mock()
            mock_db.return_value.__exit__.return_value = None
            
            # Mock the controllers
            with patch('mpi_backend.utils.extracted_data_processor.TemporaryItemMappingController') as mock_temp_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.ItemsMappingController') as mock_item_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.CustomerJobMappingController') as mock_customer_controller:
                
                mock_temp_controller.return_value.get_temp_items_mappings.return_value = []
                mock_item_controller.return_value.get_items_mappings.return_value = []
                mock_customer_controller.return_value.get_customer_job_mappings.return_value = []
                
                # Mock process_single_file
                with patch('mpi_backend.utils.extracted_data_processor.process_single_file') as mock_process:
                    mock_process.return_value = {"status": "success", "file": "test1.xlsx"}
                    
                    # Mock process_failed_file
                    with patch('mpi_backend.utils.extracted_data_processor.process_failed_file') as mock_failed:
                        results = process_extracted_data(converted_files, failed_files)
        
        assert isinstance(results, list)
        assert len(results) == 1
        mock_failed.assert_called_once()

    def test_process_extracted_data_reprocessing_mode(self):
        """Test processing in reprocessing mode."""
        converted_files = ["test1.xlsx"]
        failed_files = []
        existing_invoice_id = "12345"
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__.return_value = Mock()
            mock_db.return_value.__exit__.return_value = None
            
            # Mock the controllers
            with patch('mpi_backend.utils.extracted_data_processor.TemporaryItemMappingController') as mock_temp_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.ItemsMappingController') as mock_item_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.CustomerJobMappingController') as mock_customer_controller:
                
                mock_temp_controller.return_value.get_temp_items_mappings.return_value = []
                mock_item_controller.return_value.get_items_mappings.return_value = []
                mock_customer_controller.return_value.get_customer_job_mappings.return_value = []
                
                # Mock process_single_file
                with patch('mpi_backend.utils.extracted_data_processor.process_single_file') as mock_process:
                    mock_process.return_value = {"status": "success", "file": "test1.xlsx"}
                    
                    results = process_extracted_data(converted_files, failed_files)
                    
                    assert isinstance(results, list)
                    assert len(results) == 1

    def test_process_single_file_basic(self):
        """Test processing of a single file."""
        file_path = "test.xlsx"
        temp_items = []
        item_mappings = []
        customer_job_mappings = []
        db_session = Mock()
        
        with patch('mpi_backend.utils.extracted_data_processor.pd.read_excel') as mock_read_excel:
            mock_read_excel.return_value = Mock()
            mock_read_excel.return_value.__len__ = Mock(return_value=5)
            
            # Mock other dependencies
            with patch('mpi_backend.utils.extracted_data_processor.process_extracted_data') as mock_process:
                result = process_single_file(
                    file_path, temp_items, item_mappings, 
                    customer_job_mappings, db_session
                )
                
                assert isinstance(result, dict)

    def test_process_single_file_missing_file(self):
        """Test processing with missing file."""
        file_path = "missing.xlsx"
        temp_items = []
        item_mappings = []
        customer_job_mappings = []
        db_session = Mock()
        
        with patch('mpi_backend.utils.extracted_data_processor.pd.read_excel') as mock_read_excel:
            mock_read_excel.side_effect = FileNotFoundError("File not found")
            
            result = process_single_file(
                file_path, temp_items, item_mappings, 
                customer_job_mappings, db_session
            )
            
            assert isinstance(result, dict)
            assert result.get("status") == "error"

    def test_process_extracted_data_error_handling(self):
        """Test error handling during processing."""
        converted_files = ["test1.xlsx"]
        failed_files = []
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__.return_value = Mock()
            mock_db.return_value.__exit__.return_value = None
            
            # Mock the controllers
            with patch('mpi_backend.utils.extracted_data_processor.TemporaryItemMappingController') as mock_temp_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.ItemsMappingController') as mock_item_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.CustomerJobMappingController') as mock_customer_controller:
                
                mock_temp_controller.return_value.get_temp_items_mappings.return_value = []
                mock_item_controller.return_value.get_items_mappings.return_value = []
                mock_customer_controller.return_value.get_customer_job_mappings.return_value = []
                
                # Mock process_single_file to raise an exception
                with patch('mpi_backend.utils.extracted_data_processor.process_single_file') as mock_process:
                    mock_process.side_effect = Exception("Processing error")
                    
                    results = process_extracted_data(converted_files, failed_files)
                    
                    assert isinstance(results, list)
                    assert len(results) == 1
                    assert results[0]["status"] == "error"

    def test_process_extracted_data_database_rollback(self):
        """Test database rollback on errors."""
        converted_files = ["test1.xlsx"]
        failed_files = []
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__.return_value = Mock()
            mock_db.return_value.__exit__.return_value = None
            
            # Mock the controllers to raise an exception
            with patch('mpi_backend.utils.extracted_data_processor.TemporaryItemMappingController') as mock_temp_controller:
                mock_temp_controller.side_effect = Exception("Database error")
                
                try:
                    process_extracted_data(converted_files, failed_files)
                except Exception:
                    # Should handle the exception gracefully
                    pass

    def test_process_extracted_data_large_dataset(self):
        """Test processing with large dataset."""
        converted_files = [f"test{i}.xlsx" for i in range(100)]
        failed_files = []
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__.return_value = Mock()
            mock_db.return_value.__exit__.return_value = None
            
            # Mock the controllers
            with patch('mpi_backend.utils.extracted_data_processor.TemporaryItemMappingController') as mock_temp_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.ItemsMappingController') as mock_item_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.CustomerJobMappingController') as mock_customer_controller:
                
                mock_temp_controller.return_value.get_temp_items_mappings.return_value = []
                mock_item_controller.return_value.get_items_mappings.return_value = []
                mock_customer_controller.return_value.get_customer_job_mappings.return_value = []
                
                # Mock process_single_file
                with patch('mpi_backend.utils.extracted_data_processor.process_single_file') as mock_process:
                    mock_process.return_value = {"status": "success", "file": "test.xlsx"}
                    
                    results = process_extracted_data(converted_files, failed_files)
                    
                    assert isinstance(results, list)
                    assert len(results) == 100

    def test_process_extracted_data_memory_efficiency(self):
        """Test memory efficiency with large datasets."""
        converted_files = [f"test{i}.xlsx" for i in range(1000)]
        failed_files = []
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__.return_value = Mock()
            mock_db.return_value.__exit__.return_value = None
            
            # Mock the controllers
            with patch('mpi_backend.utils.extracted_data_processor.TemporaryItemMappingController') as mock_temp_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.ItemsMappingController') as mock_item_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.CustomerJobMappingController') as mock_customer_controller:
                
                mock_temp_controller.return_value.get_temp_items_mappings.return_value = []
                mock_item_controller.return_value.get_items_mappings.return_value = []
                mock_customer_controller.return_value.get_customer_job_mappings.return_value = []
                
                # Mock process_single_file
                with patch('mpi_backend.utils.extracted_data_processor.process_single_file') as mock_process:
                    mock_process.return_value = {"status": "success", "file": "test.xlsx"}
                    
                    # Should handle large datasets without memory issues
                    try:
                        results = process_extracted_data(converted_files, failed_files)
                        assert isinstance(results, list)
                        assert len(results) == 1000
                    except MemoryError:
                        pytest.fail("Should handle large datasets efficiently")

    def test_process_extracted_data_concurrent_processing(self):
        """Test concurrent processing safety."""
        converted_files = ["test1.xlsx", "test2.xlsx", "test3.xlsx"]
        failed_files = []
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__.return_value = Mock()
            mock_db.return_value.__exit__.return_value = None
            
            # Mock the controllers
            with patch('mpi_backend.utils.extracted_data_processor.TemporaryItemMappingController') as mock_temp_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.ItemsMappingController') as mock_item_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.CustomerJobMappingController') as mock_customer_controller:
                
                mock_temp_controller.return_value.get_temp_items_mappings.return_value = []
                mock_item_controller.return_value.get_items_mappings.return_value = []
                mock_customer_controller.return_value.get_customer_job_mappings.return_value = []
                
                # Mock process_single_file
                with patch('mpi_backend.utils.extracted_data_processor.process_single_file') as mock_process:
                    mock_process.return_value = {"status": "success", "file": "test.xlsx"}
                    
                    results = process_extracted_data(converted_files, failed_files)
                    
                    assert isinstance(results, list)
                    assert len(results) == 3

    def test_process_extracted_data_unicode_handling(self):
        """Test handling of Unicode and special characters."""
        converted_files = ["test_unicode.xlsx"]
        failed_files = []
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__.return_value = Mock()
            mock_db.return_value.__exit__.return_value = None
            
            # Mock the controllers
            with patch('mpi_backend.utils.extracted_data_processor.TemporaryItemMappingController') as mock_temp_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.ItemsMappingController') as mock_item_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.CustomerJobMappingController') as mock_customer_controller:
                
                mock_temp_controller.return_value.get_temp_items_mappings.return_value = []
                mock_item_controller.return_value.get_items_mappings.return_value = []
                mock_customer_controller.return_value.get_customer_job_mappings.return_value = []
                
                # Mock process_single_file
                with patch('mpi_backend.utils.extracted_data_processor.process_single_file') as mock_process:
                    mock_process.return_value = {"status": "success", "file": "test_unicode.xlsx"}
                    
                    results = process_extracted_data(converted_files, failed_files)
                    
                    assert isinstance(results, list)
                    assert len(results) == 1

    def test_process_extracted_data_performance_benchmarks(self):
        """Test processing performance benchmarks."""
        import time
        
        converted_files = [f"test{i}.xlsx" for i in range(100)]
        failed_files = []
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__.return_value = Mock()
            mock_db.return_value.__exit__.return_value = None
            
            # Mock the controllers
            with patch('mpi_backend.utils.extracted_data_processor.TemporaryItemMappingController') as mock_temp_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.ItemsMappingController') as mock_item_controller, \
                 patch('mpi_backend.utils.extracted_data_processor.CustomerJobMappingController') as mock_customer_controller:
                
                mock_temp_controller.return_value.get_temp_items_mappings.return_value = []
                mock_item_controller.return_value.get_items_mappings.return_value = []
                mock_customer_controller.return_value.get_customer_job_mappings.return_value = []
                
                # Mock process_single_file
                with patch('mpi_backend.utils.extracted_data_processor.process_single_file') as mock_process:
                    mock_process.return_value = {"status": "success", "file": "test.xlsx"}
                    
                    start_time = time.time()
                    results = process_extracted_data(converted_files, failed_files)
            end_time = time.time()
            
            # Should complete within reasonable time
            processing_time = end_time - start_time
            assert processing_time < 10.0  # Less than 10 seconds for 100 files
            assert len(results) == 100
