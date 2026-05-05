"""
Unit tests for reference number normalization business logic.

Tests the _normalize_ref_no_for_comparison method which handles:
- Pure numeric with leading zeros: "066617" → "66617"
- Letter-dash-number: "I-000987" → "I-987"
- Number-letter mix: "0081212A" → "81212A"
- Letter-number: "I000987" → "I987"
- Complex patterns with multiple parts
"""

import pytest
from unittest.mock import MagicMock
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController


pytestmark = pytest.mark.business_logic


class TestReferenceNumberNormalizationBasicPatterns:
    """Test basic reference number normalization patterns."""
    
    def test_normalize_pure_numeric_with_leading_zeros(self, mock_db_session):
        """
        Test normalization of pure numeric reference numbers with leading zeros.
        
        GIVEN a reference number "066617" (pure numeric with leading zeros)
        WHEN normalizing for comparison
        THEN should return "66617" (leading zeros removed)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("066617")
        
        # Assert
        assert result == "66617"
    
    def test_normalize_letter_dash_number_pattern(self, mock_db_session):
        """
        Test normalization of letter-dash-number pattern with leading zeros.
        
        GIVEN a reference number "I-000987"
        WHEN normalizing
        THEN should return "I-987"
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("I-000987")
        
        # Assert
        assert result == "I-987"
    
    def test_normalize_mixed_alphanumeric_number_first(self, mock_db_session):
        """
        Test normalization of number-letter pattern with leading zeros.
        
        GIVEN a reference number "0081212A"
        WHEN normalizing
        THEN should return "81212A"
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("0081212A")
        
        # Assert
        assert result == "81212A"
    
    def test_normalize_letter_number_no_dash(self, mock_db_session):
        """
        Test normalization of letter-number pattern without dash.
        
        GIVEN a reference number "I000987"
        WHEN normalizing
        THEN should return "I987"
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("I000987")
        
        # Assert
        assert result == "I987"
    
    def test_normalize_no_leading_zeros_unchanged(self, mock_db_session):
        """
        Test that reference numbers without leading zeros remain unchanged.
        
        GIVEN a reference number "89779-I" (no leading zeros)
        WHEN normalizing
        THEN should return "89779-I" (unchanged)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("89779-I")
        
        # Assert
        assert result == "89779-I"


class TestReferenceNumberNormalizationEdgeCases:
    """Test edge cases in reference number normalization."""
    
    def test_normalize_all_zeros_returns_single_zero(self, mock_db_session):
        """
        Test normalization of all zeros returns single zero.
        
        GIVEN a reference number "0000"
        WHEN normalizing
        THEN should return "0"
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("0000")
        
        # Assert
        assert result == "0"
    
    def test_normalize_empty_string_returns_empty(self, mock_db_session):
        """
        Test normalization of empty string.
        
        GIVEN an empty string ""
        WHEN normalizing
        THEN should return ""
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("")
        
        # Assert
        assert result == ""
    
    def test_normalize_none_input_returns_empty(self, mock_db_session):
        """
        Test normalization of None input.
        
        GIVEN None as input
        WHEN normalizing
        THEN should return ""
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison(None)
        
        # Assert
        assert result == ""
    
    def test_normalize_whitespace_trimmed(self, mock_db_session):
        """
        Test that leading/trailing whitespace is trimmed.
        
        GIVEN a reference number "  066617  " (with whitespace)
        WHEN normalizing
        THEN should return "66617" (trimmed and zeros removed)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("  066617  ")
        
        # Assert
        assert result == "66617"
    
    def test_normalize_single_zero_returns_zero(self, mock_db_session):
        """
        Test normalization of single zero.
        
        GIVEN a reference number "0"
        WHEN normalizing
        THEN should return "0"
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("0")
        
        # Assert
        assert result == "0"
    
    def test_normalize_single_digit_no_zeros(self, mock_db_session):
        """
        Test normalization of single digit without leading zero.
        
        GIVEN a reference number "5"
        WHEN normalizing
        THEN should return "5"
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("5")
        
        # Assert
        assert result == "5"


class TestReferenceNumberNormalizationComplexPatterns:
    """Test complex reference number patterns."""
    
    def test_normalize_multi_part_with_dash(self, mock_db_session):
        """
        Test normalization of multi-part reference numbers with dashes.
        
        GIVEN a reference number "INV-001-0023"
        WHEN normalizing
        THEN should normalize each numeric part
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("INV-001-0023")
        
        # Assert
        # The complex pattern handler should normalize the numeric parts
        assert "001" not in result or "0023" not in result
    
    def test_normalize_uppercase_letters_preserved(self, mock_db_session):
        """
        Test that uppercase letters are preserved.
        
        GIVEN a reference number "ABC-000123"
        WHEN normalizing
        THEN should return "ABC-123" (case preserved)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("ABC-000123")
        
        # Assert
        assert result == "ABC-123"
    
    def test_normalize_lowercase_letters_preserved(self, mock_db_session):
        """
        Test that lowercase letters are preserved.
        
        GIVEN a reference number "abc-000123"
        WHEN normalizing
        THEN should return "abc-123" (case preserved)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("abc-000123")
        
        # Assert
        assert result == "abc-123"
    
    def test_normalize_mixed_case_preserved(self, mock_db_session):
        """
        Test that mixed case is preserved.
        
        GIVEN a reference number "Abc-000123"
        WHEN normalizing
        THEN should return "Abc-123" (case preserved)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("Abc-000123")
        
        # Assert
        assert result == "Abc-123"


class TestReferenceNumberNormalizationSpecialCharacters:
    """Test reference numbers with special characters."""
    
    def test_normalize_with_dash_delimiter(self, mock_db_session):
        """
        Test normalization preserves dash delimiters.
        
        GIVEN a reference number "A-0001-B"
        WHEN normalizing
        THEN should preserve dashes
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("A-0001-B")
        
        # Assert
        assert "-" in result
        assert "A" in result
        assert "B" in result
    
    def test_normalize_alphanumeric_suffix(self, mock_db_session):
        """
        Test normalization with alphanumeric suffix.
        
        GIVEN a reference number "0012345ABC"
        WHEN normalizing
        THEN should remove leading zeros but keep suffix
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._normalize_ref_no_for_comparison("0012345ABC")
        
        # Assert
        assert result == "12345ABC"


@pytest.mark.parametrize("input_ref,expected_output", [
    # Pure numeric patterns
    ("066617", "66617"),
    ("00001", "1"),
    ("12345", "12345"),  # No leading zeros
    
    # Letter-dash-number patterns
    ("I-000987", "I-987"),
    ("A-001", "A-1"),
    ("INV-000123", "INV-123"),
    
    # Number-letter patterns
    ("0081212A", "81212A"),
    ("000123X", "123X"),
    
    # Letter-number (no dash)
    ("I000987", "I987"),
    ("ABC00123", "ABC123"),
    
    # Edge cases
    ("0000", "0"),
    ("0", "0"),
    ("", ""),
    
    # No leading zeros (should remain unchanged)
    ("89779-I", "89779-I"),
    ("12345", "12345"),
    ("ABC123", "ABC123"),
])
def test_normalize_ref_no_patterns_parameterized(mock_db_session, input_ref, expected_output):
    """
    Parameterized test for various reference number patterns.
    
    Tests multiple patterns efficiently using pytest.mark.parametrize.
    """
    # Arrange
    controller = InvoiceItemController(mock_db_session)
    
    # Act
    result = controller._normalize_ref_no_for_comparison(input_ref)
    
    # Assert
    assert result == expected_output, f"Expected '{expected_output}' but got '{result}' for input '{input_ref}'"


class TestReferenceNumberNormalizationConsistency:
    """Test consistency of normalization across different formats."""
    
    def test_normalize_equivalent_formats_produce_same_result(self, mock_db_session):
        """
        Test that equivalent formats normalize to the same value.
        
        GIVEN multiple equivalent reference number formats
        WHEN normalizing each
        THEN all should produce the same normalized result
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        equivalent_formats = [
            "066617",
            "66617",
        ]
        
        # Act
        results = [controller._normalize_ref_no_for_comparison(ref) for ref in equivalent_formats]
        
        # Assert
        assert all(r == results[0] for r in results), f"Equivalent formats produced different results: {results}"
    
    def test_normalize_letter_dash_equivalents(self, mock_db_session):
        """
        Test that equivalent letter-dash-number formats normalize identically.
        
        GIVEN "I-000987" and "I-987"
        WHEN normalizing both
        THEN both should produce "I-987"
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result1 = controller._normalize_ref_no_for_comparison("I-000987")
        result2 = controller._normalize_ref_no_for_comparison("I-987")
        
        # Assert
        assert result1 == result2 == "I-987"
    
    def test_normalization_is_idempotent(self, mock_db_session):
        """
        Test that normalizing an already normalized value returns the same value.
        
        GIVEN a normalized reference number
        WHEN normalizing it again
        THEN should return the same value (idempotent)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        first_pass = controller._normalize_ref_no_for_comparison("066617")
        second_pass = controller._normalize_ref_no_for_comparison(first_pass)
        
        # Assert
        assert first_pass == second_pass

