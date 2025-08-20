#!/usr/bin/env python3
"""
Comprehensive test suite for S3 utility functions.
Tests file upload, download, URL generation, and deletion operations.
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch
from botocore.exceptions import ClientError, NoCredentialsError
import boto3
from moto import mock_s3

from mpi_backend.utils.s3_utils import (
    upload_file,
    get_presigned_url,
    delete_file_from_s3
)


class TestS3Utils:
    """Test suite for S3 utility functions."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration values for testing."""
        with patch.multiple(
            'mpi_backend.utils.s3_utils',
            AWS_SERVER_PUBLIC_KEY='test_access_key',
            AWS_SERVER_SECRET_KEY='test_secret_key',
            REGION='us-east-1',
            BUCKET_NAME='test-mpi-bucket'
        ):
            yield

    @pytest.fixture
    def temp_pdf_file(self):
        """Create a temporary PDF file for testing uploads."""
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(b'%PDF-1.4\nFake PDF content for testing')
            temp_file_path = temp_file.name
        
        yield temp_file_path
        
        # Cleanup
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

    @pytest.fixture
    def temp_excel_file(self):
        """Create a temporary Excel file for testing uploads."""
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
            temp_file.write(b'PK\x03\x04Fake Excel content for testing')
            temp_file_path = temp_file.name
        
        yield temp_file_path
        
        # Cleanup
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

    @mock_s3
    def test_upload_file_invoice_success(self, mock_config, temp_pdf_file):
        """Test successful invoice file upload to S3."""
        # Create mock S3 bucket
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket='test-mpi-bucket')
        
        # Test upload
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=s3_client):
            upload_file(temp_pdf_file, 'test/invoice', is_invoice=True)
        
        # Verify file was uploaded
        objects = s3_client.list_objects_v2(Bucket='test-mpi-bucket')
        assert 'Contents' in objects
        assert objects['Contents'][0]['Key'] == 'test/invoice.pdf'

    @mock_s3
    def test_upload_file_with_pdf_extension_handling(self, mock_config, temp_pdf_file):
        """Test upload with proper PDF extension handling."""
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket='test-mpi-bucket')
        
        test_cases = [
            ('test/invoice', 'test/invoice.pdf'),  # No extension
            ('test/invoice.pdf', 'test/invoice.pdf'),  # Already has extension
            ('test/invoice.PDF', 'test/invoice.PDF'),  # Uppercase extension
        ]
        
        for file_key, expected_key in test_cases:
            with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=s3_client):
                upload_file(temp_pdf_file, file_key, is_invoice=True)
            
            objects = s3_client.list_objects_v2(Bucket='test-mpi-bucket')
            uploaded_keys = [obj['Key'] for obj in objects.get('Contents', [])]
            assert expected_key in uploaded_keys

    @mock_s3
    def test_upload_file_non_invoice(self, mock_config, temp_excel_file):
        """Test non-invoice file upload (no special PDF handling)."""
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket='test-mpi-bucket')
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=s3_client):
            upload_file(temp_excel_file, 'test/spreadsheet.xlsx', is_invoice=False)
        
        objects = s3_client.list_objects_v2(Bucket='test-mpi-bucket')
        assert 'Contents' in objects
        assert objects['Contents'][0]['Key'] == 'test/spreadsheet.xlsx'

    def test_upload_file_exception_handling(self, mock_config, temp_pdf_file):
        """Test upload file exception handling."""
        mock_client = Mock()
        mock_client.upload_file.side_effect = ClientError(
            {'Error': {'Code': 'NoSuchBucket', 'Message': 'Bucket does not exist'}},
            'upload_file'
        )
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            # Should not raise exception, just log error
            upload_file(temp_pdf_file, 'test/invoice', is_invoice=True)
        
        # Verify upload was attempted
        mock_client.upload_file.assert_called_once()

    def test_upload_file_missing_credentials(self, temp_pdf_file):
        """Test upload with missing AWS credentials."""
        mock_client = Mock()
        mock_client.upload_file.side_effect = NoCredentialsError()
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            upload_file(temp_pdf_file, 'test/invoice', is_invoice=True)
        
        mock_client.upload_file.assert_called_once()

    @mock_s3
    def test_get_presigned_url_success(self, mock_config):
        """Test successful presigned URL generation."""
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket='test-mpi-bucket')
        
        # Create a test object
        s3_client.put_object(
            Bucket='test-mpi-bucket',
            Key='test/invoice.pdf',
            Body=b'test content'
        )
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=s3_client):
            url = get_presigned_url('test/invoice.pdf', expiration_time=300)
        
        assert url is not None
        assert 'test-mpi-bucket' in url
        assert 'test/invoice.pdf' in url

    @mock_s3
    def test_get_presigned_url_multiple_key_attempts(self, mock_config):
        """Test presigned URL generation with multiple key pattern attempts."""
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket='test-mpi-bucket')
        
        # Create object with uppercase PDF extension
        s3_client.put_object(
            Bucket='test-mpi-bucket',
            Key='test/invoice.PDF',
            Body=b'test content'
        )
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=s3_client):
            # Request with lowercase - should find uppercase version
            url = get_presigned_url('test/invoice.pdf', is_invoice=True)
        
        assert url is not None

    @mock_s3
    def test_get_presigned_url_double_extension_handling(self, mock_config):
        """Test presigned URL generation with double extension files."""
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket='test-mpi-bucket')
        
        # Create object with double extension
        s3_client.put_object(
            Bucket='test-mpi-bucket',
            Key='test/invoice.PDF.pdf',
            Body=b'test content'
        )
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=s3_client):
            url = get_presigned_url('test/invoice.PDF', is_invoice=True)
        
        assert url is not None

    def test_get_presigned_url_no_key_found(self, mock_config):
        """Test presigned URL generation when no matching key exists."""
        mock_client = Mock()
        mock_client.generate_presigned_url.side_effect = ClientError(
            {'Error': {'Code': 'NoSuchKey', 'Message': 'Key does not exist'}},
            'generate_presigned_url'
        )
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            url = get_presigned_url('nonexistent/file.pdf', is_invoice=True)
        
        assert url is None

    def test_get_presigned_url_non_invoice(self, mock_config):
        """Test presigned URL generation for non-invoice files."""
        mock_client = Mock()
        mock_client.generate_presigned_url.return_value = 'https://test-url.com/file.xlsx'
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            url = get_presigned_url('test/file.xlsx', is_invoice=False)
        
        assert url == 'https://test-url.com/file.xlsx'
        mock_client.generate_presigned_url.assert_called_once()

    def test_get_presigned_url_exception_handling(self, mock_config):
        """Test presigned URL generation exception handling."""
        mock_client = Mock()
        mock_client.generate_presigned_url.side_effect = Exception("General S3 error")
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            url = get_presigned_url('test/file.pdf', is_invoice=True)
        
        assert url is None

    @mock_s3
    def test_delete_file_from_s3_success(self, mock_config):
        """Test successful file deletion from S3."""
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket='test-mpi-bucket')
        
        # Create test object
        s3_client.put_object(
            Bucket='test-mpi-bucket',
            Key='test/invoice.pdf',
            Body=b'test content'
        )
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=s3_client):
            result = delete_file_from_s3('test/invoice.pdf', is_invoice=True)
        
        assert result is True
        
        # Verify file was deleted
        with pytest.raises(ClientError):
            s3_client.get_object(Bucket='test-mpi-bucket', Key='test/invoice.pdf')

    @mock_s3
    def test_delete_file_multiple_variants(self, mock_config):
        """Test deletion of multiple file variants (PDF extensions)."""
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket='test-mpi-bucket')
        
        # Create multiple variants
        variants = [
            'test/invoice.pdf',
            'test/invoice.PDF',
            'test/invoice.PDF.pdf'
        ]
        
        for variant in variants:
            s3_client.put_object(
                Bucket='test-mpi-bucket',
                Key=variant,
                Body=b'test content'
            )
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=s3_client):
            result = delete_file_from_s3('test/invoice', is_invoice=True)
        
        assert result is True

    def test_delete_file_no_key_found(self, mock_config):
        """Test deletion when file doesn't exist."""
        mock_client = Mock()
        mock_client.delete_object.side_effect = ClientError(
            {'Error': {'Code': 'NoSuchKey', 'Message': 'Key does not exist'}},
            'delete_object'
        )
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            result = delete_file_from_s3('nonexistent/file.pdf', is_invoice=True)
        
        assert result is False

    def test_delete_file_non_invoice(self, mock_config):
        """Test deletion of non-invoice files."""
        mock_client = Mock()
        mock_client.delete_object.return_value = {}
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            result = delete_file_from_s3('test/file.xlsx', is_invoice=False)
        
        assert result is True
        mock_client.delete_object.assert_called_once_with(
            Bucket='test-mpi-bucket',
            Key='test/file.xlsx'
        )

    def test_delete_file_exception_handling(self, mock_config):
        """Test deletion exception handling."""
        mock_client = Mock()
        mock_client.delete_object.side_effect = Exception("General S3 error")
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            result = delete_file_from_s3('test/file.pdf', is_invoice=True)
        
        assert result is False

    def test_s3_utils_integration_workflow(self, mock_config, temp_pdf_file):
        """Test complete workflow: upload, get URL, delete."""
        mock_s3_client = Mock()
        
        # Mock successful operations
        mock_s3_client.upload_file.return_value = None
        mock_s3_client.generate_presigned_url.return_value = 'https://test-url.com'
        mock_s3_client.delete_object.return_value = {}
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_s3_client):
            # Upload
            upload_file(temp_pdf_file, 'workflow/test', is_invoice=True)
            
            # Get URL
            url = get_presigned_url('workflow/test.pdf', is_invoice=True)
            
            # Delete
            deleted = delete_file_from_s3('workflow/test.pdf', is_invoice=True)
        
        # Verify all operations were called
        mock_s3_client.upload_file.assert_called_once()
        mock_s3_client.generate_presigned_url.assert_called()
        mock_s3_client.delete_object.assert_called()
        
        assert url == 'https://test-url.com'
        assert deleted is True

    def test_edge_cases_and_special_characters(self, mock_config):
        """Test handling of edge cases and special characters in file paths."""
        mock_client = Mock()
        mock_client.generate_presigned_url.return_value = 'https://test-url.com'
        
        special_cases = [
            'path with spaces/file.pdf',
            'path/with/unicode-файл.pdf',
            'path/with-special-chars!@#$%^&*().pdf',
            'very/long/path/that/might/cause/issues/file.pdf'
        ]
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            for test_path in special_cases:
                url = get_presigned_url(test_path, is_invoice=True)
                assert url == 'https://test-url.com'

    def test_concurrent_operations_safety(self, mock_config):
        """Test that S3 operations are safe for concurrent use."""
        import threading
        import time
        
        mock_client = Mock()
        mock_client.generate_presigned_url.return_value = 'https://test-url.com'
        
        results = []
        errors = []
        
        def worker(file_id):
            try:
                with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
                    url = get_presigned_url(f'concurrent/file_{file_id}.pdf', is_invoice=True)
                    results.append(url)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads to complete
        for t in threads:
            t.join()
        
        # Verify no errors and all operations completed
        assert len(errors) == 0
        assert len(results) == 5
        assert all(url == 'https://test-url.com' for url in results)

    def test_large_file_handling_simulation(self, mock_config):
        """Test behavior with large files (simulated)."""
        import time
        mock_client = Mock()
        
        # Simulate large file upload
        def slow_upload(*args, **kwargs):
            time.sleep(0.1)  # Simulate network delay
            return None
        
        mock_client.upload_file.side_effect = slow_upload
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            # This should complete without timeout
            upload_file('/fake/large/file.pdf', 'large/file', is_invoice=True)
        
        mock_client.upload_file.assert_called_once()

    def test_configuration_validation(self):
        """Test behavior when configuration is missing or invalid."""
        # Test missing configuration
        with patch.multiple(
            'mpi_backend.utils.s3_utils',
            AWS_SERVER_PUBLIC_KEY=None,
            AWS_SERVER_SECRET_KEY=None,
            REGION=None,
            BUCKET_NAME=None
        ):
            # These should not crash, but may not work properly
            url = get_presigned_url('test/file.pdf')
            # In real implementation, this might return None or raise an exception
            # Here we just ensure it doesn't crash

    def test_logging_and_error_reporting(self, mock_config, caplog):
        """Test that operations properly log their actions and errors."""
        import logging
        
        mock_client = Mock()
        mock_client.upload_file.side_effect = Exception("Test error")
        
        with patch('mpi_backend.utils.s3_utils.boto3.client', return_value=mock_client):
            upload_file('/fake/file.pdf', 'test/file', is_invoice=True)
        
        # Check that error was logged
        assert any('Failed during upload to S3 Bucket' in record.message 
                  for record in caplog.records if record.levelno >= logging.ERROR)
