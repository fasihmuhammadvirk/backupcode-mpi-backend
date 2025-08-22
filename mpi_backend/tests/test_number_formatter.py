"""
Test file for number formatting utility functions.
Tests the formatting of cost, amount, and quantity values with commas.
"""

import pytest
from mpi_backend.utils.number_formatter import (
    format_currency, 
    format_number, 
    format_quantity
)


class TestNumberFormatter:
    """Test cases for number formatting functions."""
    
    def test_format_currency_basic(self):
        """Test basic currency formatting."""
        assert format_currency(6000.89) == "6,000.89"
        assert format_currency(1000) == "1,000.00"
        assert format_currency(1234567.1) == "1,234,567.10"
        assert format_currency(0.99) == "0.99"
    
    def test_format_currency_edge_cases(self):
        """Test edge cases for currency formatting."""
        assert format_currency(None) == "0.00"
        assert format_currency(0) == "0.00"
        assert format_currency("") == "0.00"
        assert format_currency("invalid") == "0.00"
    
    def test_format_currency_large_numbers(self):
        """Test formatting of very large numbers."""
        assert format_currency(999999999.99) == "999,999,999.99"
        assert format_currency(1000000000) == "1,000,000,000.00"
    
    def test_format_currency_decimal_places(self):
        """Test currency formatting with different decimal places."""
        assert format_currency(1234.567, 3) == "1,234.567"
        assert format_currency(1234.5, 1) == "1,234.5"
        assert format_currency(1234, 0) == "1,234"
    
    def test_format_number(self):
        """Test general number formatting."""
        assert format_number(6000.89) == "6,000.89"
        assert format_number(1234567) == "1,234,567.00"
        assert format_number(0.5, 1) == "0.5"
    
    def test_format_quantity(self):
        """Test quantity formatting."""
        assert format_quantity(1000) == "1,000"
        assert format_quantity(1234567) == "1,234,567"
        assert format_quantity(0) == "0"
        assert format_quantity(None) == "0"
        assert format_quantity("") == "0"
    
    def test_format_quantity_negative(self):
        """Test negative quantity formatting."""
        assert format_quantity(-1000) == "-1,000"
        assert format_quantity(-1234567) == "-1,234,567"
    
    def test_format_currency_with_strings(self):
        """Test currency formatting with string inputs."""
        assert format_currency("6000.89") == "6,000.89"
        assert format_currency("1,000") == "1,000.00"
        assert format_currency("$1234.56") == "1,234.56"
    
    def test_format_currency_infinity_nan(self):
        """Test currency formatting with infinity and NaN values."""
        assert format_currency(float('inf')) == "0.00"
        assert format_currency(float('-inf')) == "0.00"
        assert format_currency(float('nan')) == "0.00"


if __name__ == "__main__":
    pytest.main([__file__])
