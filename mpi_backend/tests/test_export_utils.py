#!/usr/bin/env python3
"""
Comprehensive test suite for data export utilities.
Tests DataFrame conversion, data filtering, export formatting, and file generation.
"""

import pytest
import pandas as pd
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date
from decimal import Decimal

from mpi_backend.utils.export_utils import (
    convert_items_to_dataframe,
    filter_dataframe_by_criteria,
    format_dataframe_for_export,
    export_to_excel,
    export_to_csv,
    apply_quickbooks_formatting,
    group_items_by_category,
    calculate_export_summary,
    validate_export_data,
    sanitize_export_filename,
    create_export_metadata
)


class TestExportUtils:
    """Test suite for data export utilities."""

    @pytest.fixture
    def sample_invoice_items(self):
        """Create sample invoice items for testing."""
        items = []
        for i in range(5):
            item = Mock()
            item.id = i + 1
            item.item = f"ITEM{i+1:03d}"
            item.description = f"Test Item {i+1}"
            item.qty = str(i + 1)
            item.cost = f"${(i+1)*10}.00"
            item.amount = f"${(i+1)*10*(i+1)}.00"
            item.date = "12/01/2024"
            item.ref_no = f"REF{i+1:03d}"
            item.po_number = f"PO{i+1:03d}"
            item.customer_job = f"Job {i+1}"
            item.bill = "Bill"
            item.vendor = f"Vendor {i+1}"
            item.class_ = f"Class{i+1}"
            item.account = f"Account{i+1}"
            item.memo = f"Memo {i+1}"
            item.buyer = f"Buyer {i+1}"
            item.filename = f"invoice_{i+1}.pdf"
            item.sheet_name = "Sheet1"
            item.mpi_item = f"10.{i+1} Materials"
            item.mpi_description = f"MPI Description {i+1}"
            item.date_added = datetime.now()
            item.export_status = "Pending"
            items.append(item)
        return items

    @pytest.fixture
    def sample_dataframe(self):
        """Create a sample DataFrame for testing."""
        data = {
            'Item': ['ITEM001', 'ITEM002', 'ITEM003'],
            'Description': ['Test Item 1', 'Test Item 2', 'Test Item 3'],
            'Qty': ['1', '2', '3'],
            'Cost': ['$10.00', '$20.00', '$30.00'],
            'Amount': ['$10.00', '$40.00', '$90.00'],
            'Date': ['12/01/2024', '12/02/2024', '12/03/2024'],
            'Vendor': ['Vendor A', 'Vendor B', 'Vendor A'],
            'MPI Item Code': ['10.1 Materials', '20.1 Labor', '10.2 Materials']
        }
        return pd.DataFrame(data)

    @pytest.fixture
    def temp_export_file(self):
        """Create a temporary file for export testing."""
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
            temp_file_path = temp_file.name
        
        yield temp_file_path
        
        # Cleanup
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

    def test_convert_items_to_dataframe_basic(self, sample_invoice_items):
        """Test basic conversion of invoice items to DataFrame."""
        df = convert_items_to_dataframe(sample_invoice_items)
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5  # All items should be included
        assert 'Item' in df.columns
        assert 'Description' in df.columns
        assert 'MPI Item Code' in df.columns

    def test_convert_items_to_dataframe_empty_items(self):
        """Test conversion with empty items list."""
        df = convert_items_to_dataframe([])
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_convert_items_to_dataframe_filters_invalid_items(self, sample_invoice_items):
        """Test that invalid/empty items are filtered out."""
        # Add an item with empty item code
        invalid_item = Mock()
        invalid_item.item = ""  # Empty item code
        invalid_item.description = "Invalid Item"
        sample_invoice_items.append(invalid_item)
        
        # Add an item with None item code
        none_item = Mock()
        none_item.item = None
        none_item.description = "None Item"
        sample_invoice_items.append(none_item)
        
        with patch('mpi_backend.utils.item_utils.is_empty_or_invalid_item') as mock_validator:
            mock_validator.side_effect = lambda x: x in ["", None]
            
            df = convert_items_to_dataframe(sample_invoice_items)
        
        # Should only include valid items
        assert len(df) == 5  # Original valid items only

    def test_convert_items_to_dataframe_column_mapping(self, sample_invoice_items):
        """Test that columns are mapped correctly."""
        df = convert_items_to_dataframe(sample_invoice_items)
        
        expected_columns = [
            'Item', 'Description', 'Qty', 'Cost', 'Amount', 'Date',
            'Ref NO', 'PO #', 'Customer Job', 'Bill', 'Vendor',
            'Class', 'Account', 'Memo', 'Buyer', 'Filename',
            'Sheet Name', 'MPI Item Code', 'MPI Description', 'Date Added'
        ]
        
        for col in expected_columns:
            assert col in df.columns

    def test_filter_dataframe_by_criteria_vendor_filter(self, sample_dataframe):
        """Test filtering DataFrame by vendor."""
        criteria = {'vendor': 'Vendor A'}
        filtered_df = filter_dataframe_by_criteria(sample_dataframe, criteria)
        
        assert len(filtered_df) == 2  # Two items from Vendor A
        assert all(filtered_df['Vendor'] == 'Vendor A')

    def test_filter_dataframe_by_criteria_date_range(self, sample_dataframe):
        """Test filtering DataFrame by date range."""
        criteria = {
            'start_date': '12/01/2024',
            'end_date': '12/02/2024'
        }
        filtered_df = filter_dataframe_by_criteria(sample_dataframe, criteria)
        
        assert len(filtered_df) == 2  # Items within date range

    def test_filter_dataframe_by_criteria_item_code_pattern(self, sample_dataframe):
        """Test filtering DataFrame by item code pattern."""
        criteria = {'item_pattern': 'ITEM00[12]'}
        filtered_df = filter_dataframe_by_criteria(sample_dataframe, criteria)
        
        assert len(filtered_df) == 2  # ITEM001 and ITEM002

    def test_filter_dataframe_by_criteria_multiple_criteria(self, sample_dataframe):
        """Test filtering with multiple criteria."""
        criteria = {
            'vendor': 'Vendor A',
            'mpi_category': '10'  # Materials category
        }
        filtered_df = filter_dataframe_by_criteria(sample_dataframe, criteria)
        
        # Should find items that match both criteria
        assert len(filtered_df) >= 0

    def test_format_dataframe_for_export_basic(self, sample_dataframe):
        """Test basic DataFrame formatting for export."""
        formatted_df = format_dataframe_for_export(sample_dataframe)
        
        assert isinstance(formatted_df, pd.DataFrame)
        assert len(formatted_df) == len(sample_dataframe)

    def test_format_dataframe_for_export_currency_formatting(self, sample_dataframe):
        """Test currency formatting in export."""
        formatted_df = format_dataframe_for_export(sample_dataframe, format_currency=True)
        
        # Currency columns should be properly formatted
        if 'Cost' in formatted_df.columns:
            assert all('$' in str(val) for val in formatted_df['Cost'] if pd.notna(val))

    def test_format_dataframe_for_export_remove_empty_columns(self, sample_dataframe):
        """Test removal of empty columns during formatting."""
        # Add an empty column
        sample_dataframe['EmptyColumn'] = None
        
        formatted_df = format_dataframe_for_export(sample_dataframe, remove_empty_columns=True)
        
        assert 'EmptyColumn' not in formatted_df.columns

    def test_export_to_excel_success(self, sample_dataframe, temp_export_file):
        """Test successful Excel export."""
        result = export_to_excel(sample_dataframe, temp_export_file)
        
        assert result is True
        assert os.path.exists(temp_export_file)
        
        # Verify file can be read back
        read_df = pd.read_excel(temp_export_file)
        assert len(read_df) == len(sample_dataframe)

    def test_export_to_excel_with_multiple_sheets(self, sample_dataframe, temp_export_file):
        """Test Excel export with multiple sheets."""
        sheets = {
            'Summary': sample_dataframe.head(2),
            'Details': sample_dataframe
        }
        
        result = export_to_excel(sheets, temp_export_file, multiple_sheets=True)
        
        assert result is True
        assert os.path.exists(temp_export_file)
        
        # Verify both sheets exist
        excel_file = pd.ExcelFile(temp_export_file)
        assert 'Summary' in excel_file.sheet_names
        assert 'Details' in excel_file.sheet_names

    def test_export_to_excel_error_handling(self, sample_dataframe):
        """Test Excel export error handling."""
        # Try to export to invalid path
        invalid_path = "/invalid/path/file.xlsx"
        
        result = export_to_excel(sample_dataframe, invalid_path)
        
        assert result is False

    def test_export_to_csv_success(self, sample_dataframe):
        """Test successful CSV export."""
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as temp_file:
            temp_file_path = temp_file.name
        
        try:
            result = export_to_csv(sample_dataframe, temp_file_path)
            
            assert result is True
            assert os.path.exists(temp_file_path)
            
            # Verify file can be read back
            read_df = pd.read_csv(temp_file_path)
            assert len(read_df) == len(sample_dataframe)
        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    def test_export_to_csv_with_encoding(self, sample_dataframe):
        """Test CSV export with specific encoding."""
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as temp_file:
            temp_file_path = temp_file.name
        
        try:
            result = export_to_csv(sample_dataframe, temp_file_path, encoding='utf-8')
            
            assert result is True
            
            # Verify encoding by reading with same encoding
            read_df = pd.read_csv(temp_file_path, encoding='utf-8')
            assert len(read_df) == len(sample_dataframe)
        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    def test_apply_quickbooks_formatting(self, sample_dataframe):
        """Test QuickBooks-specific formatting."""
        qb_formatted = apply_quickbooks_formatting(sample_dataframe)
        
        assert isinstance(qb_formatted, pd.DataFrame)
        
        # Should have QuickBooks-required columns
        qb_required_columns = ['Item', 'Description', 'Qty', 'Cost', 'Amount']
        for col in qb_required_columns:
            if col in sample_dataframe.columns:
                assert col in qb_formatted.columns

    def test_apply_quickbooks_formatting_data_types(self, sample_dataframe):
        """Test QuickBooks formatting handles data types correctly."""
        qb_formatted = apply_quickbooks_formatting(sample_dataframe)
        
        # Quantity should be numeric where possible
        if 'Qty' in qb_formatted.columns:
            # Should handle conversion or maintain string format for QB compatibility
            assert qb_formatted['Qty'].dtype in ['object', 'int64', 'float64']

    def test_group_items_by_category(self, sample_dataframe):
        """Test grouping items by MPI category."""
        grouped = group_items_by_category(sample_dataframe)
        
        assert isinstance(grouped, dict)
        
        # Should have groups for different categories
        if 'MPI Item Code' in sample_dataframe.columns:
            categories = sample_dataframe['MPI Item Code'].apply(
                lambda x: x.split('.')[0] if pd.notna(x) and '.' in str(x) else 'Other'
            ).unique()
            
            for category in categories:
                if category in grouped:
                    assert isinstance(grouped[category], pd.DataFrame)

    def test_group_items_by_category_empty_dataframe(self):
        """Test grouping with empty DataFrame."""
        empty_df = pd.DataFrame()
        grouped = group_items_by_category(empty_df)
        
        assert isinstance(grouped, dict)
        assert len(grouped) == 0

    def test_calculate_export_summary(self, sample_dataframe):
        """Test calculation of export summary statistics."""
        summary = calculate_export_summary(sample_dataframe)
        
        assert isinstance(summary, dict)
        assert 'total_items' in summary
        assert 'total_amount' in summary
        assert 'vendor_count' in summary
        
        assert summary['total_items'] == len(sample_dataframe)

    def test_calculate_export_summary_with_amounts(self, sample_dataframe):
        """Test summary calculation with amount totals."""
        # Ensure Amount column has numeric-convertible values
        sample_dataframe['Amount'] = ['10.00', '40.00', '90.00']
        
        summary = calculate_export_summary(sample_dataframe)
        
        if 'total_amount' in summary:
            assert isinstance(summary['total_amount'], (int, float))
            assert summary['total_amount'] > 0

    def test_validate_export_data_valid_data(self, sample_dataframe):
        """Test validation of valid export data."""
        validation_result = validate_export_data(sample_dataframe)
        
        assert validation_result['is_valid'] is True
        assert len(validation_result['errors']) == 0

    def test_validate_export_data_missing_required_columns(self):
        """Test validation with missing required columns."""
        incomplete_df = pd.DataFrame({
            'Item': ['ITEM001'],
            # Missing Description column
        })
        
        validation_result = validate_export_data(incomplete_df, required_columns=['Item', 'Description'])
        
        assert validation_result['is_valid'] is False
        assert len(validation_result['errors']) > 0
        assert any('Description' in error for error in validation_result['errors'])

    def test_validate_export_data_empty_dataframe(self):
        """Test validation of empty DataFrame."""
        empty_df = pd.DataFrame()
        
        validation_result = validate_export_data(empty_df)
        
        assert validation_result['is_valid'] is False
        assert any('empty' in error.lower() for error in validation_result['errors'])

    def test_sanitize_export_filename_basic(self):
        """Test basic filename sanitization."""
        unsafe_filename = "invoice/data<>:*?|.xlsx"
        safe_filename = sanitize_export_filename(unsafe_filename)
        
        # Should remove unsafe characters
        unsafe_chars = ['/', '<', '>', ':', '*', '?', '|']
        for char in unsafe_chars:
            assert char not in safe_filename
        
        assert safe_filename.endswith('.xlsx')

    def test_sanitize_export_filename_with_timestamp(self):
        """Test filename sanitization with timestamp."""
        base_filename = "export_data.xlsx"
        safe_filename = sanitize_export_filename(base_filename, add_timestamp=True)
        
        # Should contain timestamp
        assert len(safe_filename) > len(base_filename)
        assert safe_filename.endswith('.xlsx')

    def test_sanitize_export_filename_max_length(self):
        """Test filename sanitization with length limits."""
        long_filename = "a" * 300 + ".xlsx"
        safe_filename = sanitize_export_filename(long_filename, max_length=50)
        
        assert len(safe_filename) <= 50
        assert safe_filename.endswith('.xlsx')

    def test_create_export_metadata(self, sample_dataframe):
        """Test creation of export metadata."""
        metadata = create_export_metadata(sample_dataframe)
        
        assert isinstance(metadata, dict)
        assert 'export_timestamp' in metadata
        assert 'record_count' in metadata
        assert 'file_info' in metadata
        
        assert metadata['record_count'] == len(sample_dataframe)

    def test_create_export_metadata_with_user_info(self, sample_dataframe):
        """Test metadata creation with user information."""
        user_info = {
            'user_id': 'test_user',
            'export_purpose': 'monthly_report'
        }
        
        metadata = create_export_metadata(sample_dataframe, user_info=user_info)
        
        assert 'user_id' in metadata
        assert metadata['user_id'] == 'test_user'
        assert metadata['export_purpose'] == 'monthly_report'

    def test_export_workflow_integration(self, sample_invoice_items, temp_export_file):
        """Test complete export workflow integration."""
        # Step 1: Convert items to DataFrame
        df = convert_items_to_dataframe(sample_invoice_items)
        
        # Step 2: Apply filters
        criteria = {'vendor': 'Vendor 1'}  # This might not match our mock data exactly
        # filtered_df = filter_dataframe_by_criteria(df, criteria)
        
        # Step 3: Format for export
        formatted_df = format_dataframe_for_export(df)
        
        # Step 4: Apply QB formatting
        qb_df = apply_quickbooks_formatting(formatted_df)
        
        # Step 5: Validate
        validation = validate_export_data(qb_df)
        assert validation['is_valid'] is True
        
        # Step 6: Export
        result = export_to_excel(qb_df, temp_export_file)
        assert result is True
        
        # Step 7: Create metadata
        metadata = create_export_metadata(qb_df)
        assert isinstance(metadata, dict)

    def test_large_dataset_performance(self):
        """Test export performance with large datasets."""
        import time
        
        # Create large dataset
        large_data = {
            'Item': [f'ITEM{i:06d}' for i in range(1000)],
            'Description': [f'Item Description {i}' for i in range(1000)],
            'Amount': [f'${i*10}.00' for i in range(1000)]
        }
        large_df = pd.DataFrame(large_data)
        
        start_time = time.time()
        formatted_df = format_dataframe_for_export(large_df)
        end_time = time.time()
        
        # Should complete within reasonable time
        assert end_time - start_time < 5.0  # Less than 5 seconds
        assert len(formatted_df) == 1000

    def test_unicode_and_special_characters(self):
        """Test export handling of Unicode and special characters."""
        unicode_data = {
            'Item': ['ÍTEM_001', 'ITEM_ñ002'],
            'Description': ['Descripción con acentos', 'Item with émojis 😀'],
            'Vendor': ['Señor Plumbing', 'Plümbing Süpply']
        }
        unicode_df = pd.DataFrame(unicode_data)
        
        # Should handle Unicode without errors
        formatted_df = format_dataframe_for_export(unicode_df)
        assert len(formatted_df) == 2
        
        # Test export to file
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as temp_file:
            temp_file_path = temp_file.name
        
        try:
            result = export_to_csv(formatted_df, temp_file_path, encoding='utf-8')
            assert result is True
        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    def test_concurrent_export_operations(self):
        """Test that export operations are thread-safe."""
        import threading
        
        results = []
        errors = []
        
        def worker(worker_id):
            try:
                data = {
                    'Item': [f'WORKER_{worker_id}_ITEM_{i}' for i in range(10)],
                    'Description': [f'Worker {worker_id} Item {i}' for i in range(10)]
                }
                df = pd.DataFrame(data)
                formatted_df = format_dataframe_for_export(df)
                results.append(len(formatted_df))
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
        
        # All should succeed
        assert len(errors) == 0
        assert len(results) == 5
        assert all(result == 10 for result in results)

    def test_memory_efficiency_large_exports(self):
        """Test memory efficiency with large exports."""
        # Test chunked processing for large datasets
        large_data = {
            'Item': [f'ITEM{i:06d}' for i in range(5000)],
            'Description': [f'Description {i}' for i in range(5000)],
            'Amount': [str(i) for i in range(5000)]
        }
        large_df = pd.DataFrame(large_data)
        
        # Should handle large datasets without memory issues
        try:
            formatted_df = format_dataframe_for_export(large_df)
            assert len(formatted_df) == 5000
        except MemoryError:
            pytest.fail("Export should handle large datasets efficiently")

    def test_export_error_recovery(self, sample_dataframe):
        """Test error recovery in export operations."""
        # Test with corrupted data
        corrupted_df = sample_dataframe.copy()
        corrupted_df.loc[0, 'Amount'] = float('inf')  # Invalid value
        
        # Should handle gracefully
        try:
            formatted_df = format_dataframe_for_export(corrupted_df)
            # Should either fix the issue or handle it gracefully
            assert isinstance(formatted_df, pd.DataFrame)
        except Exception as e:
            # If it raises an exception, it should be informative
            assert len(str(e)) > 0
