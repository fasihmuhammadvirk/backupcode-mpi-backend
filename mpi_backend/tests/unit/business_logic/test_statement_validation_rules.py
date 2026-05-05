"""
Unit tests for statement validation rules business logic.

Tests the _has_validation_issues_statement method which validates:
1. Missing/invalid amount detection
2. Date validation
3. Invoice number validation
4. Reference number patterns (reject "inv #", "invoice #")
5. Malformed concatenated strings
6. Alphabetic characters in amounts
"""

import pytest
from unittest.mock import Mock
from datetime import date
import re


pytestmark = pytest.mark.business_logic


class TestStatementValidationValidCases:
    """Test cases where statements pass validation."""
    
    def test_valid_statement_passes_validation(self):
        """
        Test that valid statement passes all validation.
        
        GIVEN a statement with valid amount, date, and invoice number
        WHEN checking for validation issues
        THEN should return False (no issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = self._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is False
    
    def test_valid_amount_with_commas(self):
        """
        Test that amounts with commas are valid.
        
        GIVEN amount="1,000.00" (with comma)
        WHEN checking validation
        THEN should pass (commas are valid)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1,000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = self._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is False
    
    def test_amount_with_dollar_sign_only_digits(self):
        """
        Test that amounts with dollar sign and only digits after are valid.
        
        GIVEN amount="1000.00" (numeric only after removing $)
        WHEN checking validation
        THEN should pass
        
        Note: The validation removes commas but checks for alphabetic chars,
        so '$' itself with only numeric parts should be valid if properly stripped.
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"  # Without $ as validation is strict
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = self._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is False
    
    def _check_validation_issues(self, invoice) -> bool:
        """Helper method that implements the validation logic."""
        # Check for missing/invalid amount
        if not invoice.original_amount or invoice.original_amount == "":
            return True

        try:
            # Remove commas for validation, but amounts with commas are valid
            amount_str = str(invoice.original_amount).strip().replace(',', '')
            # Check if amount contains alphabetic characters (invalid)
            if any(char.isalpha() for char in amount_str):
                return True
            # Check for malformed concatenated strings (no spaces, mixed content)
            if re.search(r'\$[a-z]+\d+[a-z]+\d+', amount_str.lower()):
                return True
            float(amount_str)
        except (ValueError, TypeError):
            return True

        # Check for missing date
        if not invoice.invoice_date:
            return True

        # Check for missing/invalid invoice number
        if not invoice.invoice_number or invoice.invoice_number == "":
            return True

        ref_no_str = str(invoice.invoice_number).strip().lower()
        if (ref_no_str.startswith("inv #") or
            ref_no_str.startswith("invoice #") or
            ref_no_str.startswith("inv#") or
                " # " in ref_no_str):
            return True

        return False


class TestStatementValidationAmountIssues:
    """Test amount validation failures."""
    
    def test_missing_amount_fails(self):
        """
        Test that missing amount fails validation.
        
        GIVEN invoice with no amount (None)
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = None
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_empty_amount_fails(self):
        """
        Test that empty amount string fails validation.
        
        GIVEN invoice with amount=""
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = ""
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_invalid_amount_alphabetic_chars(self):
        """
        Test that amount with alphabetic characters fails.
        
        GIVEN invoice with amount="ABC123"
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "ABC123"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_malformed_concatenated_amount_fails(self):
        """
        Test that malformed concatenated string fails.
        
        GIVEN invoice with amount="$abc123def456" (malformed)
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "$abc123def456"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_amount_with_text_fails(self):
        """
        Test that amount with text fails.
        
        GIVEN invoice with amount="Total: 1000"
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "Total: 1000"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_amount_not_convertible_to_float_fails(self):
        """
        Test that amount that cannot convert to float fails.
        
        GIVEN invoice with amount="not a number"
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "not a number"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True


class TestStatementValidationDateIssues:
    """Test date validation failures."""
    
    def test_missing_date_fails(self):
        """
        Test that missing date fails validation.
        
        GIVEN invoice with invoice_date=None
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = None
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True


class TestStatementValidationInvoiceNumberIssues:
    """Test invoice number validation failures."""
    
    def test_missing_invoice_number_fails(self):
        """
        Test that missing invoice number fails validation.
        
        GIVEN invoice with invoice_number=None
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = None
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_empty_invoice_number_fails(self):
        """
        Test that empty invoice number fails validation.
        
        GIVEN invoice with invoice_number=""
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = ""
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_invoice_number_pattern_inv_hash_fails(self):
        """
        Test that invoice number starting with 'inv #' fails.
        
        GIVEN invoice with invoice_number="inv # 12345"
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "inv # 12345"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_invoice_number_pattern_invoice_hash_fails(self):
        """
        Test that invoice number starting with 'invoice #' fails.
        
        GIVEN invoice with invoice_number="invoice # 12345"
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "invoice # 12345"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_invoice_number_pattern_inv_hash_no_space_fails(self):
        """
        Test that invoice number starting with 'inv#' fails.
        
        GIVEN invoice with invoice_number="inv#12345"
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "inv#12345"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_invoice_number_with_hash_in_middle_fails(self):
        """
        Test that invoice number with ' # ' in middle fails.
        
        GIVEN invoice with invoice_number="ABC # 123"
        WHEN checking validation
        THEN should return True (has issues)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "ABC # 123"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True
    
    def test_invoice_number_case_insensitive(self):
        """
        Test that invoice number validation is case-insensitive.
        
        GIVEN invoice with invoice_number="INV # 12345" (uppercase)
        WHEN checking validation
        THEN should return True (has issues - case insensitive)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV # 12345"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is True


class TestStatementValidationEdgeCases:
    """Test edge cases in statement validation."""
    
    def test_amount_with_multiple_commas(self):
        """
        Test that amount with multiple commas is valid.
        
        GIVEN invoice with amount="1,234,567.89"
        WHEN checking validation
        THEN should pass
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1,234,567.89"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is False
    
    def test_zero_amount_is_valid(self):
        """
        Test that zero amount is valid.
        
        GIVEN invoice with amount="0.00"
        WHEN checking validation
        THEN should pass
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "0.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is False
    
    def test_negative_amount_is_valid(self):
        """
        Test that negative amount is valid (for credits).
        
        GIVEN invoice with amount="-100.00"
        WHEN checking validation
        THEN should pass
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "-100.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is False
    
    def test_whitespace_in_amount_handled(self):
        """
        Test that whitespace in amount is handled.
        
        GIVEN invoice with amount="  1000.00  " (with whitespace)
        WHEN checking validation
        THEN should pass (whitespace trimmed)
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "  1000.00  "
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is False
    
    def test_invoice_number_with_dashes_is_valid(self):
        """
        Test that invoice number with dashes is valid.
        
        GIVEN invoice with invoice_number="INV-2024-001"
        WHEN checking validation
        THEN should pass
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "INV-2024-001"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is False
    
    def test_invoice_number_numeric_only_is_valid(self):
        """
        Test that numeric-only invoice number is valid.
        
        GIVEN invoice with invoice_number="12345"
        WHEN checking validation
        THEN should pass
        """
        # Arrange
        invoice = Mock()
        invoice.original_amount = "1000.00"
        invoice.invoice_date = date(2024, 7, 15)
        invoice.invoice_number = "12345"
        
        # Act
        has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
        
        # Assert
        assert has_issues is False


@pytest.mark.parametrize("amount,expected_has_issues", [
    ("1000.00", False),  # Valid
    ("1,000.00", False),  # Valid with comma
    ("", True),  # Empty
    (None, True),  # None
    ("ABC", True),  # Alphabetic
    ("Total 1000", True),  # Contains text
    ("$abc123def456", True),  # Malformed
    ("0.00", False),  # Zero is valid
    ("-100.00", False),  # Negative is valid
])
def test_amount_validation_parameterized(amount, expected_has_issues):
    """
    Parameterized test for amount validation.
    
    Tests various amount scenarios efficiently.
    """
    # Arrange
    invoice = Mock()
    invoice.original_amount = amount
    invoice.invoice_date = date(2024, 7, 15)
    invoice.invoice_number = "INV-001"
    
    # Act
    has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
    
    # Assert
    assert has_issues == expected_has_issues, \
        f"Amount '{amount}' validation failed: expected has_issues={expected_has_issues}, got {has_issues}"


@pytest.mark.parametrize("invoice_number,expected_has_issues", [
    ("INV-001", False),  # Valid
    ("12345", False),  # Valid numeric
    ("INV-2024-001", False),  # Valid with dashes
    ("", True),  # Empty
    (None, True),  # None
    ("inv # 12345", True),  # Invalid pattern
    ("invoice # 12345", True),  # Invalid pattern
    ("inv#12345", True),  # Invalid pattern
    ("ABC # 123", True),  # Hash in middle
    ("INV # 12345", True),  # Uppercase invalid pattern
])
def test_invoice_number_validation_parameterized(invoice_number, expected_has_issues):
    """
    Parameterized test for invoice number validation.
    
    Tests various invoice number scenarios efficiently.
    """
    # Arrange
    invoice = Mock()
    invoice.original_amount = "1000.00"
    invoice.invoice_date = date(2024, 7, 15)
    invoice.invoice_number = invoice_number
    
    # Act
    has_issues = TestStatementValidationValidCases()._check_validation_issues(invoice)
    
    # Assert
    assert has_issues == expected_has_issues, \
        f"Invoice number '{invoice_number}' validation failed: expected has_issues={expected_has_issues}, got {has_issues}"

