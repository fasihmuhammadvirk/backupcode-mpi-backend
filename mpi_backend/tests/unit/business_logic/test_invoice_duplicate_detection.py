"""
Unit tests for invoice duplicate detection business logic.

Tests the check_invoice_duplicate_status method which handles:
1. Exact duplicate detection (same ref_no, vendor, date, amount, customer_job)
2. Updated invoice detection (different amount/customer_job)
3. New invoice detection (different date)
"""

import pytest
from unittest.mock import MagicMock, Mock
from datetime import date
from uuid import uuid4
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.tests.fixtures.invoice_data import InvoiceItemFactory, InvoiceScenarios


pytestmark = pytest.mark.business_logic


class TestInvoiceDuplicateDetectionExactDuplicates:
    """Test exact duplicate detection scenarios."""
    
    def test_exact_duplicate_with_matching_all_fields(self, mock_db_session, mock_query_result):
        """
        Test exact duplicate detection when all fields match.
        
        GIVEN an existing invoice with ref_no, vendor, date, amount, customer_job
        WHEN a new invoice with identical fields is processed
        THEN status should be 'exact_duplicate' with existing invoice details
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Create existing invoice item
        existing_item = Mock()
        existing_item.invoice_id = str(uuid4())
        existing_item.ref_no = "INV-001"
        existing_item.vendor = "BMW Plumbing Supplies"
        existing_item.date = date(2024, 7, 15)
        existing_item.amount = "1000.00"
        existing_item.customer_job = "Site A"
        existing_item.is_active = True
        existing_item.date_added = date(2024, 7, 10)
        
        # Mock database query to return existing item
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = [existing_item]
        
        # Act
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-001",
            vendor="BMW Plumbing Supplies",
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="Site A"
        )
        
        # Assert
        assert result['status'] == 'exact_duplicate'
        assert result['existing_invoice_id'] == existing_item.invoice_id
        assert 'duplicate' in result['message'].lower()
    
    def test_exact_duplicate_with_amount_within_tolerance(self, mock_db_session):
        """
        Test exact duplicate when amount difference is within tolerance (±$0.01).
        
        GIVEN an existing invoice with amount 1000.00
        WHEN a new invoice with amount 1000.01 (within tolerance)
        THEN status should be 'exact_duplicate'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        existing_item = Mock()
        existing_item.invoice_id = str(uuid4())
        existing_item.ref_no = "INV-002"
        existing_item.vendor = "Flow Mark"
        existing_item.date = date(2024, 7, 15)
        existing_item.amount = "1000.00"
        existing_item.customer_job = "Site B"
        existing_item.is_active = True
        existing_item.date_added = date(2024, 7, 10)
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = [existing_item]
        
        # Act - Amount differs by 0.01 (within tolerance)
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-002",
            vendor="Flow Mark",
            date=date(2024, 7, 15),
            amount="1000.01",  # Within tolerance
            customer_job="Site B"
        )
        
        # Assert
        assert result['status'] == 'exact_duplicate'
    
    def test_exact_duplicate_ignores_inactive_invoices(self, mock_db_session):
        """
        Test that inactive invoices are properly filtered out.
        
        GIVEN an existing inactive invoice (is_active=False)
        WHEN checking for duplicates
        THEN the inactive invoice should be ignored
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock query returns no items (inactive filtered out in query)
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = []
        
        # Act
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-003",
            vendor="Supreme Plumbing",
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="Site C"
        )
        
        # Assert
        assert result['status'] == 'not_found'
    
    def test_exact_duplicate_case_insensitive_customer_job(self, mock_db_session):
        """
        Test that customer job comparison is case-insensitive.
        
        GIVEN an existing invoice with customer_job "Site A"
        WHEN a new invoice with customer_job "site a"
        THEN status should be 'exact_duplicate'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        existing_item = Mock()
        existing_item.invoice_id = str(uuid4())
        existing_item.ref_no = "INV-004"
        existing_item.vendor = "World Wide Plumbing"
        existing_item.date = date(2024, 7, 15)
        existing_item.amount = "1000.00"
        existing_item.customer_job = "Site A"  # Mixed case
        existing_item.is_active = True
        existing_item.date_added = date(2024, 7, 10)
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = [existing_item]
        
        # Act - Different case
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-004",
            vendor="World Wide Plumbing",
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="site a"  # Lower case
        )
        
        # Assert
        assert result['status'] == 'exact_duplicate'


class TestInvoiceDuplicateDetectionUpdatedInvoices:
    """Test updated invoice detection scenarios."""
    
    def test_updated_invoice_different_amount(self, mock_db_session):
        """
        Test updated invoice detection when amount differs.
        
        GIVEN an existing invoice with ref_no, vendor, date, amount=1000
        WHEN a new invoice with same ref/vendor/date but amount=1100
        THEN status should be 'updated_invoice'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        existing_item = Mock()
        existing_item.invoice_id = str(uuid4())
        existing_item.ref_no = "INV-005"
        existing_item.vendor = "AF Supply"
        existing_item.date = date(2024, 7, 15)
        existing_item.amount = "1000.00"  # Original amount
        existing_item.customer_job = "Site D"
        existing_item.is_active = True
        existing_item.date_added = date(2024, 7, 10)
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = [existing_item]
        
        # Act - Different amount (beyond tolerance)
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-005",
            vendor="AF Supply",
            date=date(2024, 7, 15),
            amount="1100.00",  # Updated amount
            customer_job="Site D"
        )
        
        # Assert
        assert result['status'] == 'updated_invoice'
        assert result['existing_invoice_id'] == existing_item.invoice_id
        assert 'updated' in result['message'].lower()
    
    def test_updated_invoice_different_customer_job(self, mock_db_session):
        """
        Test updated invoice when customer_job differs.
        
        GIVEN an existing invoice with customer_job "Site D"
        WHEN a new invoice with same ref/vendor/date/amount but customer_job "Site E"
        THEN status should be 'updated_invoice'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        existing_item = Mock()
        existing_item.invoice_id = str(uuid4())
        existing_item.ref_no = "INV-006"
        existing_item.vendor = "BMW Plumbing Supplies"
        existing_item.date = date(2024, 7, 15)
        existing_item.amount = "1000.00"
        existing_item.customer_job = "Site D"  # Original customer job
        existing_item.is_active = True
        existing_item.date_added = date(2024, 7, 10)
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = [existing_item]
        
        # Act - Different customer job
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-006",
            vendor="BMW Plumbing Supplies",
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="Site E"  # Updated customer job
        )
        
        # Assert
        assert result['status'] == 'updated_invoice'
    
    def test_updated_invoice_different_amount_and_customer_job(self, mock_db_session):
        """
        Test updated invoice when both amount and customer_job differ.
        
        GIVEN an existing invoice
        WHEN a new invoice with different amount AND customer_job
        THEN status should be 'updated_invoice'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        existing_item = Mock()
        existing_item.invoice_id = str(uuid4())
        existing_item.ref_no = "INV-007"
        existing_item.vendor = "Flow Mark"
        existing_item.date = date(2024, 7, 15)
        existing_item.amount = "1000.00"
        existing_item.customer_job = "Site F"
        existing_item.is_active = True
        existing_item.date_added = date(2024, 7, 10)
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = [existing_item]
        
        # Act - Both different
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-007",
            vendor="Flow Mark",
            date=date(2024, 7, 15),
            amount="1200.00",  # Different amount
            customer_job="Site G"  # Different customer job
        )
        
        # Assert
        assert result['status'] == 'updated_invoice'


class TestInvoiceDuplicateDetectionNewInvoices:
    """Test new invoice detection scenarios."""
    
    def test_new_invoice_different_date(self, mock_db_session):
        """
        Test new invoice detection when date differs.
        
        GIVEN an existing invoice with date 2024-07-15
        WHEN a new invoice with same ref/vendor but date 2024-07-20
        THEN status should be 'new_invoice'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        existing_item = Mock()
        existing_item.invoice_id = str(uuid4())
        existing_item.ref_no = "INV-008"
        existing_item.vendor = "Supreme Plumbing"
        existing_item.date = date(2024, 7, 15)  # Original date
        existing_item.amount = "1000.00"
        existing_item.customer_job = "Site H"
        existing_item.is_active = True
        existing_item.date_added = date(2024, 7, 10)
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = [existing_item]
        
        # Act - Different date
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-008",
            vendor="Supreme Plumbing",
            date=date(2024, 7, 20),  # New date
            amount="1000.00",
            customer_job="Site H"
        )
        
        # Assert
        assert result['status'] == 'new_invoice'
        assert 'new' in result['message'].lower()
    
    def test_new_invoice_same_date_different_vendor(self, mock_db_session):
        """
        Test that same ref_no with different vendor is treated as new.
        
        GIVEN an existing invoice with ref_no "INV-009" and vendor "A"
        WHEN a new invoice with ref_no "INV-009" but vendor "B"
        THEN status should be 'not_found' (different vendor means no match)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock returns no items (vendor filter excludes it)
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = []
        
        # Act
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-009",
            vendor="Different Vendor",  # Different vendor
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="Site I"
        )
        
        # Assert
        assert result['status'] == 'not_found'


class TestInvoiceDuplicateDetectionEdgeCases:
    """Test edge cases and error handling."""
    
    def test_missing_reference_number(self, mock_db_session):
        """
        Test handling of missing reference number.
        
        GIVEN no reference number provided (None or empty)
        WHEN checking for duplicates
        THEN status should be 'not_found' with appropriate message
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller.check_invoice_duplicate_status(
            reference_no="",  # Empty ref_no
            vendor="Some Vendor",
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="Site J"
        )
        
        # Assert
        assert result['status'] == 'not_found'
        assert 'missing' in result['message'].lower()
    
    def test_missing_vendor(self, mock_db_session):
        """
        Test handling of missing vendor.
        
        GIVEN no vendor provided (None or empty)
        WHEN checking for duplicates
        THEN status should be 'not_found' with appropriate message
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-010",
            vendor="",  # Empty vendor
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="Site K"
        )
        
        # Assert
        assert result['status'] == 'not_found'
        assert 'missing' in result['message'].lower()
    
    def test_invalid_amount_format(self, mock_db_session):
        """
        Test handling of invalid amount format.
        
        GIVEN an amount with invalid format (e.g., letters)
        WHEN checking for duplicates
        THEN should handle gracefully and use 0.0 as fallback
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock returns no existing items
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = []
        
        # Act - Invalid amount
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-011",
            vendor="Test Vendor",
            date=date(2024, 7, 15),
            amount="invalid_amount",  # Invalid format
            customer_job="Site L"
        )
        
        # Assert - Should not crash
        assert result['status'] == 'not_found'
    
    def test_null_customer_job(self, mock_db_session):
        """
        Test handling of None/null customer_job.
        
        GIVEN invoices with None customer_job
        WHEN comparing for duplicates
        THEN should handle None values correctly
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        existing_item = Mock()
        existing_item.invoice_id = str(uuid4())
        existing_item.ref_no = "INV-012"
        existing_item.vendor = "Test Vendor"
        existing_item.date = date(2024, 7, 15)
        existing_item.amount = "1000.00"
        existing_item.customer_job = None  # Null customer job
        existing_item.is_active = True
        existing_item.date_added = date(2024, 7, 10)
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = [existing_item]
        
        # Act - Also None customer job
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-012",
            vendor="Test Vendor",
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job=None  # Null customer job
        )
        
        # Assert - Should match as exact duplicate
        assert result['status'] == 'exact_duplicate'
    
    def test_multiple_existing_invoices_same_ref_chooses_most_recent(self, mock_db_session):
        """
        Test that when multiple invoices exist with same ref, most recent is chosen.
        
        GIVEN multiple existing invoices with same ref_no
        WHEN checking for duplicates
        THEN should choose the most recently added invoice
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Create multiple items with same ref but different dates_added
        older_item = Mock()
        older_item.invoice_id = "older-uuid"
        older_item.ref_no = "INV-013"
        older_item.vendor = "Test Vendor"
        older_item.date = date(2024, 7, 15)
        older_item.amount = "1000.00"
        older_item.customer_job = "Site M"
        older_item.is_active = True
        older_item.date_added = date(2024, 7, 1)  # Older
        
        newer_item = Mock()
        newer_item.invoice_id = "newer-uuid"
        newer_item.ref_no = "INV-013"
        newer_item.vendor = "Test Vendor"
        newer_item.date = date(2024, 7, 15)
        newer_item.amount = "1000.00"
        newer_item.customer_job = "Site M"
        newer_item.is_active = True
        newer_item.date_added = date(2024, 7, 10)  # Newer
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = [older_item, newer_item]
        
        # Act
        result = controller.check_invoice_duplicate_status(
            reference_no="INV-013",
            vendor="Test Vendor",
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="Site M"
        )
        
        # Assert - Should reference the newer invoice
        assert result['status'] == 'exact_duplicate'
        assert result['existing_invoice_id'] == "newer-uuid"
    
    def test_whitespace_handling_in_inputs(self, mock_db_session):
        """
        Test that whitespace is properly trimmed from inputs.
        
        GIVEN inputs with leading/trailing whitespace
        WHEN checking for duplicates
        THEN whitespace should be trimmed for comparison
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        existing_item = Mock()
        existing_item.invoice_id = str(uuid4())
        existing_item.ref_no = "INV-014"
        existing_item.vendor = "Test Vendor"
        existing_item.date = date(2024, 7, 15)
        existing_item.amount = "1000.00"
        existing_item.customer_job = "Site N"
        existing_item.is_active = True
        existing_item.date_added = date(2024, 7, 10)
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.all.return_value = [existing_item]
        
        # Act - With whitespace
        result = controller.check_invoice_duplicate_status(
            reference_no="  INV-014  ",  # Leading/trailing spaces
            vendor="  Test Vendor  ",
            date=date(2024, 7, 15),
            amount="  1000.00  ",
            customer_job="  Site N  "
        )
        
        # Assert - Should match despite whitespace
        assert result['status'] == 'exact_duplicate'

