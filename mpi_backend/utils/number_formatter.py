"""
Utility functions for formatting numbers in API responses.
Provides functions to format cost, amount, and other numeric values
with proper comma separators for thousands.
"""

import locale
from typing import Union


def format_currency(value: Union[float, int, str, None],
                    decimal_places: int = 2) -> str:
    """
    Format a numeric value as currency with comma separators for thousands.
    
    Args:
        value: The numeric value to format
        decimal_places: Number of decimal places to show (default: 2)
        
    Returns:
        Formatted string with commas for thousands
        
    Examples:
        >>> format_currency(6000.89)
        '6,000.89'
        >>> format_currency(1234567.1)
        '1,234,567.10'
        >>> format_currency(1000)
        '1,000.00'
        >>> format_currency(None)
        '0.00'
    """
    if value is None:
        return f"0.{'0' * decimal_places}"
    
    try:
        # Convert to float and handle edge cases
        if isinstance(value, str):
            # Remove commas, currency symbols, and convert to float
            clean_value = float(
                value.replace(',', '').replace('$', '').replace('£', '')
                .replace('€', '')
            )
        else:
            clean_value = float(value)
        
        # Handle infinity and NaN
        if (not (clean_value == clean_value) or 
                abs(clean_value) == float('inf')):
            return f"0.{'0' * decimal_places}"
        
        # Format with locale for proper comma separation
        try:
            # Try to use locale for proper formatting
            locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
            formatted = locale.format_string(
                f"%.{decimal_places}f", clean_value, grouping=True
            )
        except (locale.Error, OSError):
            # Fallback to manual formatting if locale fails
            formatted = _manual_format_currency(clean_value, decimal_places)
        
        return formatted
        
    except (ValueError, TypeError):
        return f"0.{'0' * decimal_places}"


def _manual_format_currency(value: float, decimal_places: int) -> str:
    """
    Manual fallback formatting for currency values.
    
    Args:
        value: The numeric value to format
        decimal_places: Number of decimal places to show
        
    Returns:
        Formatted string with commas for thousands
    """
    # Convert to string with fixed decimal places
    str_value = f"{value:.{decimal_places}f}"
    
    # Split into integer and decimal parts
    if '.' in str_value:
        integer_part, decimal_part = str_value.split('.')
    else:
        integer_part, decimal_part = str_value, '0' * decimal_places
    
    # Add commas to integer part
    if len(integer_part) > 3:
        # Reverse the string, add commas every 3 characters, then reverse back
        reversed_int = integer_part[::-1]
        comma_separated = ','.join(
            reversed_int[i:i+3] for i in range(0, len(reversed_int), 3)
        )
        integer_part = comma_separated[::-1]
    
    # Ensure decimal part has correct number of digits
    decimal_part = decimal_part.ljust(decimal_places, '0')[:decimal_places]
    
    return f"{integer_part}.{decimal_part}"


def format_number(value: Union[float, int, str, None],
                  decimal_places: int = 2) -> str:
    """
    Format a numeric value with comma separators for thousands.
    Similar to format_currency but without currency-specific formatting.
    
    Args:
        value: The numeric value to format
        decimal_places: Number of decimal places to show (default: 2)
        
    Returns:
        Formatted string with commas for thousands
        
    Examples:
        >>> format_number(6000.89)
        '6,000.89'
        >>> format_number(1234567)
        '1,234,567.00'
    """
    return format_currency(value, decimal_places)


def format_quantity(value: Union[int, float, str, None]) -> str:
    """
    Format quantity values (usually integers) with comma separators.
    
    Args:
        value: The quantity value to format
        
    Returns:
        Formatted string with commas for thousands
        
    Examples:
        >>> format_quantity(1000)
        '1,000'
        >>> format_quantity(1234567)
        '1,234,567'
    """
    if value is None:
        return "0"
    
    try:
        if isinstance(value, str):
            clean_value = int(float(value.replace(',', '')))
        else:
            clean_value = int(float(value))
        
        # Handle edge cases
        if (not (clean_value == clean_value) or 
                abs(clean_value) == float('inf')):
            return "0"
        
        # Format with commas
        try:
            locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
            formatted = locale.format_string("%d", clean_value, grouping=True)
        except (locale.Error, OSError):
            formatted = _manual_format_quantity(clean_value)
        
        return formatted
        
    except (ValueError, TypeError):
        return "0"


def _manual_format_quantity(value: int) -> str:
    """
    Manual fallback formatting for quantity values.
    
    Args:
        value: The integer value to format
        
    Returns:
        Formatted string with commas for thousands
    """
    str_value = str(abs(value))
    
    if len(str_value) <= 3:
        return str_value
    
    # Add commas every 3 characters from the right
    result = []
    for i in range(len(str_value) - 1, -1, -3):
        start = max(0, i - 2)
        result.append(str_value[start:i + 1])
    
    formatted = ','.join(reversed(result))
    
    # Add negative sign if needed
    if value < 0:
        formatted = f"-{formatted}"
    
    return formatted


def parse_number(value: Union[float, int, str, None]) -> Union[float, None]:
    """
    Parse a numeric value, removing commas and converting to float.
    Used for database storage where numeric values are expected.
    
    Args:
        value: The value to parse (can be string with commas, number, or None)
        
    Returns:
        Parsed float value or None if parsing fails
        
    Examples:
        >>> parse_number("3,473.75")
        3473.75
        >>> parse_number("1,234,567.89")
        1234567.89
        >>> parse_number(1234.56)
        1234.56
        >>> parse_number(None)
        None
    """
    if value is None:
        return None
    
    try:
        if isinstance(value, str):
            # Remove commas, currency symbols, and convert to float
            clean_value = float(
                value.replace(',', '').replace('$', '').replace('£', '')
                .replace('€', '').strip()
            )
        else:
            clean_value = float(value)
        
        # Handle infinity and NaN
        if (not (clean_value == clean_value) or 
                abs(clean_value) == float('inf')):
            return None
        
        return clean_value
        
    except (ValueError, TypeError):
        return None
