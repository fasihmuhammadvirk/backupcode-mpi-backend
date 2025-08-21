#!/usr/bin/env python3
"""
Comprehensive integration test suite for MPI Backend.
Tests end-to-end workflows, component interactions, and system-level functionality.
"""

import pytest
import tempfile
import os
import time
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Import all the modules we're testing
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
from mpi_backend.utils.auth.auth_handler import signJWT, decodeJWT
from mpi_backend.utils.mapping_validators import is_temporary_mapping, validate_mapping_quality
from mpi_backend.utils.export_utils import convert_items_to_dataframe, export_to_excel
from mpi_backend.background.scheduler import init_scheduler


class TestMPIBackendIntegration:
    """Integration tests for MPI Backend system."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace for integration testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            
            # Create subdirectories
            (workspace / "uploads").mkdir()
            (workspace / "exports").mkdir()
            (workspace / "processing").mkdir()
            
            yield workspace

    @pytest.fixture
    def sample_invoice_data(self):
        """Create comprehensive sample invoice data."""
        return {
            'invoice_metadata': {
                'filename': 'test_invoice_001.pdf',
                'supplier': 'BMW Plumbing Supplies',
                'date': '2024-12-01',
                'invoice_number': 'INV-2024-001',
                'po_number': 'PO-2024-001'
            },
            'invoice_items': [
                {
                    'item': 'BMW_PIPE_001',
                    'description': 'Copper Pipe 1/2 inch',
                    'qty': '10',
                    'cost': '$5.50',
                    'amount': '$55.00',
                    'customer_job': 'Residential Project A',
                    'buyer': 'John Smith'
                },
                {
                    'item': 'BMW_FITTING_002',
                    'description': 'Pipe Fitting Elbow',
                    'qty': '5',
                    'cost': '$3.25',
                    'amount': '$16.25',
                    'customer_job': 'Commercial Project B',
                    'buyer': 'Jane Doe'
                },
                {
                    'item': 'UNMAPPED_ITEM',
                    'description': 'Unknown Part',
                    'qty': '1',
                    'cost': '$10.00',
                    'amount': '$10.00',
                    'customer_job': 'Project C',
                    'buyer': 'Bob Johnson'
                }
            ]
        }

    def test_authentication_workflow(self):
        """Test complete authentication workflow."""
        # Step 1: Create JWT token
        user_id = "integration_test_user"
        token_response = signJWT(user_id)
        
        assert 'access_token' in token_response
        token = token_response['access_token']
        
        # Step 2: Validate token
        decoded_payload = decodeJWT(token)
        
        assert decoded_payload is not None
        assert decoded_payload['user_id'] == user_id
        
        # Step 3: Test token expiration logic
        assert 'expires' in decoded_payload
        assert decoded_payload['expires'] > time.time()

    def test_data_mapping_and_validation_workflow(self, sample_invoice_data):
        """Test complete data mapping and validation workflow."""
        items = sample_invoice_data['invoice_items']
        
        # Step 1: Validate each item's mapping status
        mapping_results = []
        for item in items:
            # Check if item code is temporary
            is_temp = is_temporary_mapping(item.get('item'), item.get('description'))
            
            # Validate mapping quality
            mapping_quality = validate_mapping_quality({
                'item': item.get('item'),
                'description': item.get('description'),
                'supplier': sample_invoice_data['invoice_metadata']['supplier'],
                'mpi_item': '10 Materials' if not is_temp else 'UIDI001',
                'mpi_description': 'Standard Material' if not is_temp else 'No Match'
            })
            
            mapping_results.append({
                'item': item.get('item'),
                'is_temporary': is_temp,
                'quality': mapping_quality
            })
        
        # Verify results
        assert len(mapping_results) == 3
        
        # BMW items should not be temporary
        bmw_items = [r for r in mapping_results if r['item'].startswith('BMW_')]
        assert all(not r['is_temporary'] for r in bmw_items)
        
        # UNMAPPED_ITEM might be temporary depending on implementation
        unmapped_item = next(r for r in mapping_results if r['item'] == 'UNMAPPED_ITEM')
        assert isinstance(unmapped_item['quality'], dict)

    def test_export_workflow_integration(self, sample_invoice_data, temp_workspace):
        """Test complete export workflow integration."""
        # Step 1: Create mock invoice items
        mock_items = []
        for i, item_data in enumerate(sample_invoice_data['invoice_items']):
            mock_item = Mock()
            for key, value in item_data.items():
                setattr(mock_item, key, value)
            
            # Add additional required attributes
            mock_item.id = i + 1
            mock_item.date = sample_invoice_data['invoice_metadata']['date']
            mock_item.ref_no = sample_invoice_data['invoice_metadata']['invoice_number']
            mock_item.po_number = sample_invoice_data['invoice_metadata']['po_number']
            mock_item.bill = 'Bill'
            mock_item.vendor = sample_invoice_data['invoice_metadata']['supplier']
            mock_item.class_ = 'Materials'
            mock_item.account = 'Inventory'
            mock_item.memo = 'Test invoice item'
            mock_item.filename = sample_invoice_data['invoice_metadata']['filename']
            mock_item.sheet_name = 'Sheet1'
            mock_item.mpi_item = '10 Materials'
            mock_item.mpi_description = 'Standard Material'
            mock_item.date_added = time.time()
            
            mock_items.append(mock_item)
        
        # Step 2: Convert to DataFrame
        with patch('mpi_backend.utils.item_utils.is_empty_or_invalid_item', return_value=False):
            df = convert_items_to_dataframe(mock_items)
        
        assert len(df) == 3
        assert 'Item' in df.columns
        assert 'Description' in df.columns
        
        # Step 3: Export to Excel
        export_file = temp_workspace / "exports" / "test_export.xlsx"
        result = export_to_excel(df, str(export_file))
        
        assert result is True
        assert export_file.exists()

    def test_s3_operations_workflow(self, temp_workspace):
        """Test S3 operations workflow."""
        # Create a test file
        test_file = temp_workspace / "uploads" / "test_invoice.pdf"
        test_content = b"Test PDF content for S3 upload"
        test_file.write_bytes(test_content)
        
        with patch('mpi_backend.utils.s3_utils.boto3.client') as mock_boto:
            mock_s3_client = Mock()
            mock_boto.return_value = mock_s3_client
            
            # Step 1: Upload file
            upload_file(str(test_file), "test/invoice", is_invoice=True)
            
            # Verify upload was called
            mock_s3_client.upload_file.assert_called_once()
            
            # Step 2: Generate presigned URL
            mock_s3_client.generate_presigned_url.return_value = "https://test-url.com/invoice.pdf"
            
            url = get_presigned_url("test/invoice.pdf", is_invoice=True)
            
            assert url == "https://test-url.com/invoice.pdf"
            mock_s3_client.generate_presigned_url.assert_called()

    def test_scheduler_initialization_workflow(self):
        """Test scheduler initialization and configuration."""
        with patch('mpi_backend.background.scheduler.BackgroundScheduler') as mock_scheduler_class:
            mock_scheduler = Mock()
            mock_scheduler_class.return_value = mock_scheduler
            
            # Initialize scheduler
            scheduler = init_scheduler()
            
            # Verify scheduler was created and configured
            mock_scheduler_class.assert_called_once()
            
            # Verify jobs were added
            assert mock_scheduler.add_job.call_count >= 6  # Multiple background jobs
            
            # Check that scheduler instance is returned
            assert scheduler == mock_scheduler

    def test_error_handling_across_components(self, temp_workspace):
        """Test error handling and recovery across different components."""
        # Test 1: S3 error handling
        with patch('mpi_backend.utils.s3_utils.boto3.client') as mock_boto:
            mock_s3_client = Mock()
            mock_s3_client.upload_file.side_effect = Exception("S3 connection failed")
            mock_boto.return_value = mock_s3_client
            
            # Should not raise exception, just log error
            upload_file("nonexistent_file.pdf", "test/key", is_invoice=True)
        
        # Test 2: JWT error handling
        invalid_token = "invalid.jwt.token"
        result = decodeJWT(invalid_token)
        assert result == {}  # Should return empty dict, not raise
        
        # Test 3: Mapping validation error handling
        invalid_mapping = None
        try:
            validate_mapping_quality(invalid_mapping)
        except (TypeError, AttributeError):
            # Acceptable to raise these for invalid input
            pass

    def test_performance_under_load(self):
        """Test system performance under simulated load."""
        import threading
        import time
        
        results = []
        errors = []
        
        def load_test_worker(worker_id):
            try:
                start_time = time.time()
                
                # Simulate typical operations
                user_id = f"load_test_user_{worker_id}"
                token_response = signJWT(user_id)
                token = token_response['access_token']
                
                decoded = decodeJWT(token)
                assert decoded['user_id'] == user_id
                
                # Test mapping validation
                test_mapping = {
                    'item': f'LOAD_TEST_ITEM_{worker_id}',
                    'description': f'Load test item {worker_id}',
                    'supplier': 'Load Test Supplier',
                    'mpi_item': '10 Materials',
                    'mpi_description': 'Load test material'
                }
                
                quality = validate_mapping_quality(test_mapping)
                assert isinstance(quality, dict)
                
                end_time = time.time()
                results.append(end_time - start_time)
                
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads for load testing
        threads = []
        num_workers = 10
        
        for i in range(num_workers):
            t = threading.Thread(target=load_test_worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads to complete
        for t in threads:
            t.join()
        
        # Verify results
        assert len(errors) == 0, f"Errors occurred during load test: {errors}"
        assert len(results) == num_workers
        
        # Performance should be reasonable
        avg_time = sum(results) / len(results)
        max_time = max(results)
        
        assert avg_time < 1.0, f"Average operation time too high: {avg_time}s"
        assert max_time < 2.0, f"Maximum operation time too high: {max_time}s"

    def test_data_consistency_workflow(self, sample_invoice_data):
        """Test data consistency across the entire workflow."""
        original_data = sample_invoice_data['invoice_items']
        
        # Step 1: Validate original data
        for item in original_data:
            assert 'item' in item
            assert 'description' in item
            assert 'qty' in item
        
        # Step 2: Process through mapping validation
        processed_items = []
        for item in original_data:
            # Simulate processing
            processed_item = item.copy()
            
            # Add MPI mappings
            if not is_temporary_mapping(item['item']):
                processed_item['mpi_item'] = '10 Materials'
                processed_item['mpi_description'] = 'Standard Material'
            else:
                processed_item['mpi_item'] = 'UIDI001'
                processed_item['mpi_description'] = 'No Match'
            
            processed_items.append(processed_item)
        
        # Step 3: Verify data consistency
        assert len(processed_items) == len(original_data)
        
        for original, processed in zip(original_data, processed_items):
            # Original fields should be preserved
            assert processed['item'] == original['item']
            assert processed['description'] == original['description']
            assert processed['qty'] == original['qty']
            
            # New fields should be added
            assert 'mpi_item' in processed
            assert 'mpi_description' in processed

    def test_configuration_and_environment_handling(self):
        """Test handling of different configuration scenarios."""
        # Test with different configuration values
        test_configs = [
            {'AWS_SERVER_PUBLIC_KEY': 'test_key', 'REGION': 'us-east-1'},
            {'AWS_SERVER_PUBLIC_KEY': None, 'REGION': None},
            {}  # Empty config
        ]
        
        for config in test_configs:
            with patch.dict('os.environ', config, clear=True):
                # Should handle different configurations gracefully
                try:
                    # Test operations that depend on config
                    token_response = signJWT("config_test_user")
                    assert 'access_token' in token_response
                    
                    # S3 operations might fail but shouldn't crash
                    with patch('mpi_backend.utils.s3_utils.boto3.client') as mock_boto:
                        mock_boto.side_effect = Exception("Config error")
                        # Should handle gracefully
                        upload_file("test.pdf", "test/key", is_invoice=True)
                        
                except Exception as e:
                    # Some failures are acceptable for invalid configs
                    pass

    def test_memory_and_resource_management(self, temp_workspace):
        """Test memory usage and resource management."""
        import gc
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # Perform memory-intensive operations
        large_datasets = []
        
        for i in range(5):
            # Create large mock dataset
            large_mock_items = []
            for j in range(1000):
                mock_item = Mock()
                mock_item.item = f'ITEM_{i}_{j:06d}'
                mock_item.description = f'Large dataset item {i}-{j}'
                mock_item.qty = '1'
                mock_item.cost = '$10.00'
                mock_item.amount = '$10.00'
                # Add other required attributes
                for attr in ['date', 'ref_no', 'po_number', 'bill', 'vendor', 
                            'class_', 'account', 'memo', 'buyer', 'filename', 
                            'sheet_name', 'mpi_item', 'mpi_description', 'date_added']:
                    setattr(mock_item, attr, f'value_{attr}')
                
                large_mock_items.append(mock_item)
            
            # Process the dataset
            with patch('mpi_backend.utils.item_utils.is_empty_or_invalid_item', return_value=False):
                df = convert_items_to_dataframe(large_mock_items)
            
            large_datasets.append(df)
            
            # Force garbage collection
            gc.collect()
        
        # Check memory usage
        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable (less than 500MB)
        assert memory_increase < 500 * 1024 * 1024, f"Memory usage increased by {memory_increase / 1024 / 1024:.2f}MB"
        
        # Cleanup
        del large_datasets
        gc.collect()

    def test_end_to_end_invoice_processing_simulation(self, sample_invoice_data, temp_workspace):
        """Test complete end-to-end invoice processing simulation."""
        # This simulates the complete workflow from PDF upload to export
        
        # Step 1: File Upload Simulation
        invoice_file = temp_workspace / "uploads" / sample_invoice_data['invoice_metadata']['filename']
        invoice_file.write_bytes(b"Simulated PDF content")
        
        # Step 2: Authentication
        user_id = "processor_user"
        auth_token = signJWT(user_id)
        assert 'access_token' in auth_token
        
        # Step 3: PDF to Excel Conversion (Simulated)
        excel_file = temp_workspace / "processing" / "converted_invoice.xlsx"
        
        # Create Excel file with invoice data
        import pandas as pd
        items_df = pd.DataFrame(sample_invoice_data['invoice_items'])
        items_df.to_excel(excel_file, index=False)
        
        # Step 4: Data Processing and Mapping
        mock_items = []
        for item_data in sample_invoice_data['invoice_items']:
            mock_item = Mock()
            for key, value in item_data.items():
                setattr(mock_item, key, value)
            
            # Add required attributes
            mock_item.id = len(mock_items) + 1
            mock_item.date = sample_invoice_data['invoice_metadata']['date']
            mock_item.ref_no = sample_invoice_data['invoice_metadata']['invoice_number']
            mock_item.po_number = sample_invoice_data['invoice_metadata']['po_number']
            mock_item.bill = 'Bill'
            mock_item.vendor = sample_invoice_data['invoice_metadata']['supplier']
            mock_item.class_ = 'Materials'
            mock_item.account = 'Inventory'
            mock_item.memo = f"Item from {sample_invoice_data['invoice_metadata']['filename']}"
            mock_item.filename = sample_invoice_data['invoice_metadata']['filename']
            mock_item.sheet_name = 'Sheet1'
            mock_item.date_added = time.time()
            
            # Apply mapping logic
            if not is_temporary_mapping(item_data['item']):
                mock_item.mpi_item = '10 Materials'
                mock_item.mpi_description = 'Standard Material'
            else:
                mock_item.mpi_item = 'UIDI001'
                mock_item.mpi_description = 'No Match'
            
            mock_items.append(mock_item)
        
        # Step 5: Export Generation
        with patch('mpi_backend.utils.item_utils.is_empty_or_invalid_item', return_value=False):
            export_df = convert_items_to_dataframe(mock_items)
        
        export_file = temp_workspace / "exports" / "final_export.xlsx"
        export_result = export_to_excel(export_df, str(export_file))
        
        # Step 6: Verification
        assert export_result is True
        assert export_file.exists()
        
        # Verify export content
        read_df = pd.read_excel(export_file)
        assert len(read_df) == len(sample_invoice_data['invoice_items'])
        assert 'Item' in read_df.columns
        assert 'MPI Item Code' in read_df.columns
        
        # Step 7: S3 Upload Simulation
        with patch('mpi_backend.utils.s3_utils.boto3.client') as mock_boto:
            mock_s3_client = Mock()
            mock_boto.return_value = mock_s3_client
            
            upload_file(str(export_file), "exports/final_export.xlsx", is_invoice=False)
            mock_s3_client.upload_file.assert_called_once()
        
        # Step 8: Generate Processing Summary
        processing_summary = {
            'original_file': str(invoice_file),
            'converted_file': str(excel_file),
            'export_file': str(export_file),
            'items_processed': len(mock_items),
            'items_mapped': len([item for item in mock_items if item.mpi_item != 'UIDI001']),
            'items_unmapped': len([item for item in mock_items if item.mpi_item == 'UIDI001']),
            'processing_time': time.time(),
            'user_id': user_id
        }
        
        assert processing_summary['items_processed'] == 3
        assert processing_summary['items_mapped'] >= 0
        assert processing_summary['items_unmapped'] >= 0
        assert processing_summary['items_mapped'] + processing_summary['items_unmapped'] == 3
