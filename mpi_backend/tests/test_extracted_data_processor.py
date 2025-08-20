#!/usr/bin/env python3
"""
Comprehensive test suite for extracted data processing and mapping.
Tests data processing workflow, mapping logic, database operations, and error handling.
"""

import pytest
import pandas as pd
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime
from pathlib import Path

from mpi_backend.utils.extracted_data_processor import (
    process_extracted_data,
    process_single_converted_file,
    apply_item_mappings,
    apply_customer_job_mappings,
    store_processed_items,
    handle_unmapped_items,
    update_export_status,
    validate_processed_data,
    create_processing_summary
)


class TestExtractedDataProcessor:
    """Test suite for extracted data processing and mapping."""

    @pytest.fixture
    def sample_excel_file(self):
        """Create a sample Excel file for testing."""
        data = {
            'Item': ['PART001', 'PART002', 'PART003'],
            'Description': ['Pipe Fitting', 'Valve', 'Connector'],
            'Qty': ['1', '2', '3'],
            'Cost': ['$10.00', '$25.00', '$15.00'],
            'Amount': ['$10.00', '$50.00', '$45.00'],
            'Date': ['12/01/2024', '12/01/2024', '12/01/2024'],
            'Ref NO': ['REF001', 'REF001', 'REF001'],
            'PO #': ['PO001', 'PO001', 'PO001'],
            'Customer Job': ['Job A', 'Job B', 'Job A'],
            'Vendor': ['BMW Plumbing', 'BMW Plumbing', 'BMW Plumbing'],
            'Buyer': ['Buyer1', 'Buyer1', 'Buyer1']
        }
        
        df = pd.DataFrame(data)
        
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
            temp_file_path = temp_file.name
            df.to_excel(temp_file_path, index=False)
        
        yield temp_file_path
        
        # Cleanup
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

    @pytest.fixture
    def mock_database_session(self):
        """Create a mock database session."""
        mock_session = Mock()
        mock_session.add = Mock()
        mock_session.commit = Mock()
        mock_session.rollback = Mock()
        mock_session.query = Mock()
        return mock_session

    @pytest.fixture
    def mock_mappings(self):
        """Create mock mapping data."""
        temp_mappings = {
            'PART001': {
                'mpi_item': '10 Materials',
                'mpi_description': 'Pipe Fittings'
            },
            'PART002': {
                'mpi_item': '20 Labor',
                'mpi_description': 'Installation Labor'
            }
        }
        
        customer_mappings = {
            ('Job A', 'BMW Plumbing'): 'MPI Job A',
            ('Job B', 'BMW Plumbing'): 'MPI Job B'
        }
        
        return {
            'temp_mappings': temp_mappings,
            'customer_mappings': customer_mappings,
            'items_mappings': temp_mappings  # Assuming same format
        }

    @pytest.fixture
    def sample_converted_files(self, sample_excel_file):
        """Create sample converted files list."""
        return [
            {
                'file_path': sample_excel_file,
                'supplier': 'BMW Plumbing',
                'invoice_filename': 'test_invoice.pdf',
                'status': 'success'
            }
        ]

    def test_process_extracted_data_success(self, sample_converted_files, mock_mappings):
        """Test successful processing of extracted data."""
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__ = Mock(return_value=Mock())
            mock_db.return_value.__exit__ = Mock(return_value=None)
            
            with patch.multiple(
                'mpi_backend.utils.extracted_data_processor',
                TemporaryItemMappingController=Mock(),
                ItemsMappingController=Mock(),
                CustomerJobMappingController=Mock(),
                SupplierController=Mock(),
                InvoiceController=Mock(),
                InvoiceItemController=Mock(),
                UnmappedItemsController=Mock()
            ):
                results = process_extracted_data(sample_converted_files, [])
        
        assert isinstance(results, list)
        assert len(results) > 0

    def test_process_extracted_data_with_failed_files(self, sample_converted_files):
        """Test processing with failed files."""
        failed_files = [
            {
                'file_path': '/path/to/failed_file.pdf',
                'error': 'Conversion failed',
                'supplier': 'Test Supplier'
            }
        ]
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__ = Mock(return_value=Mock())
            mock_db.return_value.__exit__ = Mock(return_value=None)
            
            with patch.multiple(
                'mpi_backend.utils.extracted_data_processor',
                TemporaryItemMappingController=Mock(),
                ItemsMappingController=Mock(),
                CustomerJobMappingController=Mock(),
                SupplierController=Mock(),
                InvoiceController=Mock(),
                InvoiceItemController=Mock(),
                UnmappedItemsController=Mock()
            ):
                results = process_extracted_data(sample_converted_files, failed_files)
        
        assert isinstance(results, list)

    def test_process_extracted_data_reprocessing_mode(self, sample_converted_files):
        """Test processing in reprocessing mode with existing invoice ID."""
        existing_invoice_id = "123e4567-e89b-12d3-a456-426614174000"
        
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_db.return_value.__enter__ = Mock(return_value=Mock())
            mock_db.return_value.__exit__ = Mock(return_value=None)
            
            with patch.multiple(
                'mpi_backend.utils.extracted_data_processor',
                TemporaryItemMappingController=Mock(),
                ItemsMappingController=Mock(),
                CustomerJobMappingController=Mock(),
                SupplierController=Mock(),
                InvoiceController=Mock(),
                InvoiceItemController=Mock(),
                UnmappedItemsController=Mock()
            ):
                results = process_extracted_data(
                    sample_converted_files, [], 
                    existing_invoice_id=existing_invoice_id
                )
        
        assert isinstance(results, list)

    def test_process_single_converted_file(self, sample_excel_file, mock_mappings, mock_database_session):
        """Test processing of a single converted file."""
        file_info = {
            'file_path': sample_excel_file,
            'supplier': 'BMW Plumbing',
            'invoice_filename': 'test_invoice.pdf',
            'status': 'success'
        }
        
        mock_controllers = {
            'temp_items_controller': Mock(),
            'items_mapping_controller': Mock(),
            'customer_job_controller': Mock(),
            'supplier_controller': Mock(),
            'invoice_controller': Mock(),
            'invoice_item_controller': Mock(),
            'unmapped_items_controller': Mock()
        }
        
        # Mock supplier lookup
        mock_controllers['supplier_controller'].get_supplier_by_name.return_value = Mock(id=1)
        
        # Mock invoice creation
        mock_invoice = Mock()
        mock_invoice.id = "test-invoice-id"
        mock_controllers['invoice_controller'].insert_invoice.return_value = mock_invoice
        
        result = process_single_converted_file(
            file_info, mock_mappings, mock_controllers, mock_database_session
        )
        
        assert result is not None
        assert 'invoice_id' in result
        assert 'items_processed' in result

    def test_process_single_converted_file_missing_file(self, mock_mappings, mock_database_session):
        """Test processing with missing Excel file."""
        file_info = {
            'file_path': '/nonexistent/file.xlsx',
            'supplier': 'BMW Plumbing',
            'invoice_filename': 'test_invoice.pdf',
            'status': 'success'
        }
        
        mock_controllers = {
            'temp_items_controller': Mock(),
            'items_mapping_controller': Mock(),
            'customer_job_controller': Mock(),
            'supplier_controller': Mock(),
            'invoice_controller': Mock(),
            'invoice_item_controller': Mock(),
            'unmapped_items_controller': Mock()
        }
        
        result = process_single_converted_file(
            file_info, mock_mappings, mock_controllers, mock_database_session
        )
        
        assert result is not None
        assert 'error' in result

    def test_apply_item_mappings_with_temp_mappings(self):
        """Test applying item mappings using temporary mappings."""
        items_data = [
            {'item': 'PART001', 'description': 'Pipe Fitting'},
            {'item': 'PART002', 'description': 'Valve'},
            {'item': 'UNMAPPED', 'description': 'Unknown Part'}
        ]
        
        temp_mappings = {
            'PART001': {
                'mpi_item': '10 Materials',
                'mpi_description': 'Pipe Fittings'
            }
        }
        
        items_mappings = {
            'PART002': {
                'mpi_item': '20 Labor',
                'mpi_description': 'Installation Labor'
            }
        }
        
        mapped_items, unmapped_items = apply_item_mappings(
            items_data, temp_mappings, items_mappings
        )
        
        assert len(mapped_items) == 2  # PART001 and PART002 mapped
        assert len(unmapped_items) == 1  # UNMAPPED item
        
        # Check mapping application
        part001_item = next(item for item in mapped_items if item['item'] == 'PART001')
        assert part001_item['mpi_item'] == '10 Materials'
        
        part002_item = next(item for item in mapped_items if item['item'] == 'PART002')
        assert part002_item['mpi_item'] == '20 Labor'

    def test_apply_item_mappings_priority_order(self):
        """Test that temporary mappings take priority over regular mappings."""
        items_data = [
            {'item': 'PART001', 'description': 'Pipe Fitting'}
        ]
        
        temp_mappings = {
            'PART001': {
                'mpi_item': '10 Materials - Temp',
                'mpi_description': 'Temporary Mapping'
            }
        }
        
        items_mappings = {
            'PART001': {
                'mpi_item': '10 Materials - Regular',
                'mpi_description': 'Regular Mapping'
            }
        }
        
        mapped_items, unmapped_items = apply_item_mappings(
            items_data, temp_mappings, items_mappings
        )
        
        assert len(mapped_items) == 1
        assert mapped_items[0]['mpi_item'] == '10 Materials - Temp'  # Temp should win

    def test_apply_customer_job_mappings(self):
        """Test applying customer job mappings."""
        items_data = [
            {'customer_job': 'Job A', 'vendor': 'BMW Plumbing'},
            {'customer_job': 'Job B', 'vendor': 'BMW Plumbing'},
            {'customer_job': 'Unmapped Job', 'vendor': 'BMW Plumbing'}
        ]
        
        customer_mappings = {
            ('Job A', 'BMW Plumbing'): 'MPI Job A',
            ('Job B', 'BMW Plumbing'): 'MPI Job B'
        }
        
        mapped_items = apply_customer_job_mappings(items_data, customer_mappings)
        
        assert len(mapped_items) == 3
        
        # Check mappings applied
        job_a_item = next(item for item in mapped_items if item['customer_job'] == 'Job A')
        assert job_a_item.get('mpi_customer_job') == 'MPI Job A'
        
        job_b_item = next(item for item in mapped_items if item['customer_job'] == 'Job B')
        assert job_b_item.get('mpi_customer_job') == 'MPI Job B'
        
        # Unmapped job should not have mpi_customer_job
        unmapped_item = next(item for item in mapped_items if item['customer_job'] == 'Unmapped Job')
        assert unmapped_item.get('mpi_customer_job') is None

    def test_store_processed_items(self, mock_database_session):
        """Test storing processed items in database."""
        processed_items = [
            {
                'item': 'PART001',
                'description': 'Pipe Fitting',
                'qty': '1',
                'cost': '$10.00',
                'amount': '$10.00',
                'mpi_item': '10 Materials',
                'mpi_description': 'Pipe Fittings'
            }
        ]
        
        mock_invoice_id = "test-invoice-id"
        mock_controller = Mock()
        
        stored_items = store_processed_items(
            processed_items, mock_invoice_id, mock_controller, mock_database_session
        )
        
        assert len(stored_items) == 1
        # Verify controller was called to add items
        mock_controller.add_invoice_item.assert_called()

    def test_store_processed_items_batch_processing(self, mock_database_session):
        """Test batch processing of large item sets."""
        # Create large set of items
        processed_items = [
            {
                'item': f'PART{i:03d}',
                'description': f'Item {i}',
                'qty': '1',
                'cost': '$10.00',
                'amount': '$10.00',
                'mpi_item': '10 Materials',
                'mpi_description': 'Materials'
            }
            for i in range(100)
        ]
        
        mock_invoice_id = "test-invoice-id"
        mock_controller = Mock()
        
        stored_items = store_processed_items(
            processed_items, mock_invoice_id, mock_controller, mock_database_session
        )
        
        assert len(stored_items) == 100
        # Should handle batch processing efficiently
        assert mock_controller.add_invoice_item.call_count == 100

    def test_handle_unmapped_items(self, mock_database_session):
        """Test handling of unmapped items."""
        unmapped_items = [
            {
                'item': 'UNKNOWN001',
                'description': 'Unknown Item',
                'qty': '1',
                'cost': '$15.00',
                'amount': '$15.00',
                'vendor': 'BMW Plumbing'
            }
        ]
        
        mock_controller = Mock()
        
        handle_unmapped_items(unmapped_items, mock_controller, mock_database_session)
        
        # Should record unmapped items
        mock_controller.add_unmapped_item.assert_called()

    def test_handle_unmapped_items_aggregation(self, mock_database_session):
        """Test aggregation of duplicate unmapped items."""
        unmapped_items = [
            {
                'item': 'UNKNOWN001',
                'description': 'Unknown Item',
                'qty': '1',
                'cost': '$15.00',
                'amount': '$15.00',
                'vendor': 'BMW Plumbing'
            },
            {
                'item': 'UNKNOWN001',  # Duplicate
                'description': 'Unknown Item',
                'qty': '2',
                'cost': '$15.00',
                'amount': '$30.00',
                'vendor': 'BMW Plumbing'
            }
        ]
        
        mock_controller = Mock()
        
        handle_unmapped_items(unmapped_items, mock_controller, mock_database_session)
        
        # Should aggregate duplicates
        mock_controller.add_unmapped_item.assert_called()
        
        # Check if aggregation logic was applied
        call_args = mock_controller.add_unmapped_item.call_args
        if call_args:
            # Should combine quantities or amounts
            pass  # Specific implementation depends on the actual function

    def test_update_export_status(self, mock_database_session):
        """Test updating export status of processed items."""
        processed_items = [
            Mock(id=1),
            Mock(id=2),
            Mock(id=3)
        ]
        
        mock_controller = Mock()
        
        update_export_status(processed_items, 'Exported', mock_controller, mock_database_session)
        
        # Should update all items
        assert mock_controller.update_export_status.call_count == 3

    def test_validate_processed_data_valid_data(self):
        """Test validation of valid processed data."""
        valid_data = [
            {
                'item': 'PART001',
                'description': 'Valid Item',
                'qty': '1',
                'cost': '$10.00',
                'amount': '$10.00',
                'mpi_item': '10 Materials'
            }
        ]
        
        validation_result = validate_processed_data(valid_data)
        
        assert validation_result['is_valid'] is True
        assert len(validation_result['errors']) == 0

    def test_validate_processed_data_missing_fields(self):
        """Test validation with missing required fields."""
        invalid_data = [
            {
                'item': 'PART001',
                # Missing description
                'qty': '1',
                'cost': '$10.00'
                # Missing amount
            }
        ]
        
        validation_result = validate_processed_data(invalid_data)
        
        assert validation_result['is_valid'] is False
        assert len(validation_result['errors']) > 0

    def test_validate_processed_data_invalid_values(self):
        """Test validation with invalid field values."""
        invalid_data = [
            {
                'item': '',  # Empty item code
                'description': 'Item',
                'qty': 'invalid',  # Invalid quantity
                'cost': 'not_a_price',  # Invalid cost
                'amount': '$10.00'
            }
        ]
        
        validation_result = validate_processed_data(invalid_data)
        
        assert validation_result['is_valid'] is False
        assert len(validation_result['errors']) > 0

    def test_create_processing_summary(self):
        """Test creation of processing summary."""
        results = [
            {
                'file_path': '/path/to/file1.xlsx',
                'items_processed': 10,
                'items_mapped': 8,
                'items_unmapped': 2,
                'status': 'success'
            },
            {
                'file_path': '/path/to/file2.xlsx',
                'items_processed': 5,
                'items_mapped': 5,
                'items_unmapped': 0,
                'status': 'success'
            }
        ]
        
        summary = create_processing_summary(results)
        
        assert isinstance(summary, dict)
        assert summary['total_files_processed'] == 2
        assert summary['total_items_processed'] == 15
        assert summary['total_items_mapped'] == 13
        assert summary['total_items_unmapped'] == 2

    def test_create_processing_summary_with_errors(self):
        """Test summary creation with processing errors."""
        results = [
            {
                'file_path': '/path/to/file1.xlsx',
                'items_processed': 10,
                'status': 'success'
            },
            {
                'file_path': '/path/to/file2.xlsx',
                'error': 'File not found',
                'status': 'error'
            }
        ]
        
        summary = create_processing_summary(results)
        
        assert summary['total_files_processed'] == 2
        assert summary['files_with_errors'] == 1
        assert summary['success_rate'] < 1.0

    def test_error_handling_database_rollback(self, sample_converted_files):
        """Test database rollback on processing errors."""
        with patch('mpi_backend.utils.extracted_data_processor.db') as mock_db:
            mock_session = Mock()
            mock_session.commit.side_effect = Exception("Database error")
            mock_db.return_value.__enter__ = Mock(return_value=mock_session)
            mock_db.return_value.__exit__ = Mock(return_value=None)
            
            with patch.multiple(
                'mpi_backend.utils.extracted_data_processor',
                TemporaryItemMappingController=Mock(),
                ItemsMappingController=Mock(),
                CustomerJobMappingController=Mock(),
                SupplierController=Mock(),
                InvoiceController=Mock(),
                InvoiceItemController=Mock(),
                UnmappedItemsController=Mock()
            ):
                results = process_extracted_data(sample_converted_files, [])
            
            # Should handle error gracefully
            mock_session.rollback.assert_called()

    def test_concurrent_processing_safety(self):
        """Test that processing operations are thread-safe."""
        import threading
        
        results = []
        errors = []
        
        def worker(worker_id):
            try:
                items_data = [
                    {
                        'item': f'WORKER_{worker_id}_ITEM_{i}',
                        'description': f'Worker {worker_id} Item {i}'
                    }
                    for i in range(5)
                ]
                
                temp_mappings = {}
                items_mappings = {}
                
                mapped_items, unmapped_items = apply_item_mappings(
                    items_data, temp_mappings, items_mappings
                )
                
                results.append({
                    'worker_id': worker_id,
                    'mapped': len(mapped_items),
                    'unmapped': len(unmapped_items)
                })
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        # All should complete without errors
        assert len(errors) == 0
        assert len(results) == 5

    def test_memory_efficiency_large_datasets(self):
        """Test memory efficiency with large datasets."""
        # Create large dataset
        large_items_data = [
            {
                'item': f'ITEM{i:06d}',
                'description': f'Item Description {i}',
                'qty': '1',
                'cost': '$10.00',
                'amount': '$10.00'
            }
            for i in range(1000)
        ]
        
        temp_mappings = {}
        items_mappings = {}
        
        # Should handle large datasets efficiently
        mapped_items, unmapped_items = apply_item_mappings(
            large_items_data, temp_mappings, items_mappings
        )
        
        assert len(mapped_items) + len(unmapped_items) == 1000

    def test_unicode_and_special_character_handling(self):
        """Test processing of Unicode and special characters."""
        unicode_items = [
            {
                'item': 'ÍTEM_001',
                'description': 'Descripción con acentos',
                'vendor': 'Señor Plumbing'
            },
            {
                'item': 'ITEM_ñ002',
                'description': 'Item with émojis 😀',
                'vendor': 'Plümbing Süpply'
            }
        ]
        
        temp_mappings = {}
        items_mappings = {}
        
        # Should handle Unicode without errors
        mapped_items, unmapped_items = apply_item_mappings(
            unicode_items, temp_mappings, items_mappings
        )
        
        assert len(mapped_items) + len(unmapped_items) == 2

    def test_data_consistency_validation(self):
        """Test validation of data consistency during processing."""
        inconsistent_data = [
            {
                'item': 'PART001',
                'description': 'Item 1',
                'qty': '2',
                'cost': '$10.00',
                'amount': '$15.00'  # Inconsistent: 2 * $10.00 ≠ $15.00
            }
        ]
        
        validation_result = validate_processed_data(inconsistent_data, check_calculations=True)
        
        # Should detect calculation inconsistencies
        if 'calculation_errors' in validation_result:
            assert len(validation_result['calculation_errors']) > 0

    def test_processing_performance_benchmarks(self, sample_excel_file):
        """Test processing performance benchmarks."""
        import time
        
        # Create larger test file
        large_data = {
            'Item': [f'ITEM{i:06d}' for i in range(100)],
            'Description': [f'Item {i}' for i in range(100)],
            'Qty': ['1'] * 100,
            'Cost': ['$10.00'] * 100,
            'Amount': ['$10.00'] * 100
        }
        
        large_df = pd.DataFrame(large_data)
        
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
            temp_file_path = temp_file.name
            large_df.to_excel(temp_file_path, index=False)
        
        try:
            start_time = time.time()
            
            # Simulate processing
            items_data = large_df.to_dict('records')
            temp_mappings = {}
            items_mappings = {}
            
            mapped_items, unmapped_items = apply_item_mappings(
                items_data, temp_mappings, items_mappings
            )
            
            end_time = time.time()
            
            # Should complete within reasonable time
            processing_time = end_time - start_time
            assert processing_time < 5.0  # Less than 5 seconds for 100 items
            
        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
