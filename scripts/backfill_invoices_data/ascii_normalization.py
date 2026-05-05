"""
ASCII normalization utilities for invoice extraction.

This module provides functions to detect and convert non-ASCII characters
(especially lookalike Unicode characters like Greek letters) to their ASCII
equivalents. This prevents mapping failures caused by visually similar but
different character encodings.

Common confusions:
- Greek Nu (N) vs Latin N
- Greek Tau (T) vs Latin T
- Greek Omicron (O) vs Latin O
- Greek Alpha (A) vs Latin A
- Cyrillic characters that look like Latin
- Various Unicode dash types
"""
import copy
import logging
from typing import Any
import unicodedata

logger = logging.getLogger(__name__)

# Comprehensive mapping of lookalike Unicode characters to ASCII equivalents
LOOKALIKE_CHAR_MAP = {
    # Greek uppercase -> Latin uppercase
    '\u0391': 'A',  # Greek Alpha
    '\u0392': 'B',  # Greek Beta
    '\u0395': 'E',  # Greek Epsilon
    '\u0396': 'Z',  # Greek Zeta
    '\u0397': 'H',  # Greek Eta
    '\u0399': 'I',  # Greek Iota
    '\u039A': 'K',  # Greek Kappa
    '\u039C': 'M',  # Greek Mu
    '\u039D': 'N',  # Greek Nu
    '\u039F': 'O',  # Greek Omicron
    '\u03A1': 'P',  # Greek Rho
    '\u03A4': 'T',  # Greek Tau
    '\u03A5': 'Y',  # Greek Upsilon
    '\u03A7': 'X',  # Greek Chi

    # Greek lowercase -> Latin lowercase
    '\u03B1': 'a',  # Greek alpha
    '\u03BF': 'o',  # Greek omicron
    '\u03C5': 'u',  # Greek upsilon

    # Cyrillic uppercase -> Latin uppercase
    '\u0410': 'A',  # Cyrillic A
    '\u0412': 'B',  # Cyrillic Ve
    '\u0415': 'E',  # Cyrillic Ie
    '\u041A': 'K',  # Cyrillic Ka
    '\u041C': 'M',  # Cyrillic Em
    '\u041D': 'H',  # Cyrillic En
    '\u041E': 'O',  # Cyrillic O
    '\u0420': 'P',  # Cyrillic Er
    '\u0421': 'C',  # Cyrillic Es
    '\u0422': 'T',  # Cyrillic Te
    '\u0423': 'Y',  # Cyrillic U
    '\u0425': 'X',  # Cyrillic Ha

    # Cyrillic lowercase -> Latin lowercase
    '\u0430': 'a',  # Cyrillic a
    '\u0435': 'e',  # Cyrillic ie
    '\u043E': 'o',  # Cyrillic o
    '\u0441': 'c',  # Cyrillic es
    '\u0443': 'y',  # Cyrillic u
    '\u0445': 'x',  # Cyrillic ha

    # Various dash and hyphen characters -> standard hyphen
    '\u2010': '-',  # Hyphen
    '\u2011': '-',  # Non-breaking hyphen
    '\u2012': '-',  # Figure dash
    '\u2013': '-',  # En dash
    '\u2014': '-',  # Em dash
    '\u2015': '-',  # Horizontal bar
    '\u2212': '-',  # Minus sign
    '\uFE58': '-',  # Small em dash
    '\uFE63': '-',  # Small hyphen-minus
    '\uFF0D': '-',  # Fullwidth hyphen-minus

    # Various space characters -> standard space
    '\u00A0': ' ',  # Non-breaking space
    '\u2000': ' ',  # En quad
    '\u2001': ' ',  # Em quad
    '\u2002': ' ',  # En space
    '\u2003': ' ',  # Em space
    '\u2009': ' ',  # Thin space
    '\u200A': ' ',  # Hair space
    '\u202F': ' ',  # Narrow no-break space
    '\u3000': ' ',  # Ideographic space

    # Fullwidth digits -> standard digits
    '\uFF10': '0', '\uFF11': '1', '\uFF12': '2', '\uFF13': '3', '\uFF14': '4',
    '\uFF15': '5', '\uFF16': '6', '\uFF17': '7', '\uFF18': '8', '\uFF19': '9',

    # Fullwidth uppercase letters
    '\uFF21': 'A', '\uFF22': 'B', '\uFF23': 'C', '\uFF24': 'D', '\uFF25': 'E',
    '\uFF26': 'F', '\uFF27': 'G', '\uFF28': 'H', '\uFF29': 'I', '\uFF2A': 'J',
    '\uFF2B': 'K', '\uFF2C': 'L', '\uFF2D': 'M', '\uFF2E': 'N', '\uFF2F': 'O',
    '\uFF30': 'P', '\uFF31': 'Q', '\uFF32': 'R', '\uFF33': 'S', '\uFF34': 'T',
    '\uFF35': 'U', '\uFF36': 'V', '\uFF37': 'W', '\uFF38': 'X', '\uFF39': 'Y',
    '\uFF3A': 'Z',

    # Fullwidth lowercase letters
    '\uFF41': 'a', '\uFF42': 'b', '\uFF43': 'c', '\uFF44': 'd', '\uFF45': 'e',
    '\uFF46': 'f', '\uFF47': 'g', '\uFF48': 'h', '\uFF49': 'i', '\uFF4A': 'j',
    '\uFF4B': 'k', '\uFF4C': 'l', '\uFF4D': 'm', '\uFF4E': 'n', '\uFF4F': 'o',
    '\uFF50': 'p', '\uFF51': 'q', '\uFF52': 'r', '\uFF53': 's', '\uFF54': 't',
    '\uFF55': 'u', '\uFF56': 'v', '\uFF57': 'w', '\uFF58': 'x', '\uFF59': 'y',
    '\uFF5A': 'z',

    # Superscript digits
    '\u00B2': '2', '\u00B3': '3', '\u00B9': '1',
    '\u2070': '0', '\u2074': '4', '\u2075': '5',
    '\u2076': '6', '\u2077': '7', '\u2078': '8', '\u2079': '9',
}

# Build translation table for efficient batch replacement
_TRANSLATION_TABLE = str.maketrans(LOOKALIKE_CHAR_MAP)


def contains_non_ascii(text: str) -> bool:
    """
    Check if a string contains any non-ASCII characters.

    Args:
        text: String to check.

    Returns:
        bool: True if the string contains non-ASCII characters.
    """
    if not text:
        return False
    try:
        text.encode('ascii')
        return False
    except UnicodeEncodeError:
        return True


def find_non_ascii_chars(text: str) -> list[tuple[int, str, str, int]]:
    """
    Find all non-ASCII characters in a string with their positions and Unicode info.

    Args:
        text: String to analyze.

    Returns:
        list[tuple]: List of tuples (position, character, unicode_name, codepoint)
    """
    if not text:
        return []

    non_ascii = []
    for i, char in enumerate(text):
        if ord(char) > 127:
            try:
                name = unicodedata.name(char, 'UNKNOWN')
            except ValueError:
                name = 'UNKNOWN'
            non_ascii.append((i, char, name, ord(char)))

    return non_ascii


def normalize_to_ascii(text: str) -> str:
    """
    Convert a string to ASCII by replacing lookalike characters.

    This function:
    1. Replaces known lookalike characters (Greek, Cyrillic, fullwidth, etc.)
    2. Uses Unicode normalization (NFKD) to decompose accented characters
    3. Removes any remaining non-ASCII characters

    Args:
        text: String to normalize.

    Returns:
        str: ASCII-only string with lookalikes replaced.
    """
    if not text:
        return text

    # Step 1: Replace known lookalike characters
    result = text.translate(_TRANSLATION_TABLE)

    # Step 2: Unicode NFKD normalization (decomposes accented chars)
    result = unicodedata.normalize('NFKD', result)

    # Step 3: Keep only ASCII characters
    result = result.encode('ascii', 'ignore').decode('ascii')

    return result


def normalize_to_ascii_with_details(text: str) -> tuple[str, dict[str, Any]]:
    """
    Normalize string to ASCII and return details about changes made.

    Args:
        text: String to normalize.

    Returns:
        tuple[str, dict]: (normalized_text, details)
    """
    if not text:
        return text, {'had_non_ascii': False, 'chars_replaced': 0, 'replacements': []}

    details = {
        'had_non_ascii': False,
        'chars_replaced': 0,
        'replacements': []
    }

    for i, char in enumerate(text):
        if ord(char) > 127:
            details['had_non_ascii'] = True
            replacement = LOOKALIKE_CHAR_MAP.get(char)
            if replacement:
                details['replacements'].append({
                    'position': i,
                    'original': char,
                    'original_name': unicodedata.name(char, 'UNKNOWN'),
                    'original_codepoint': hex(ord(char)),
                    'replacement': replacement
                })
                details['chars_replaced'] += 1

    normalized = normalize_to_ascii(text)
    return normalized, details


def normalize_extracted_data(
    data: dict[str, Any],
    fields: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Normalize string fields in extracted invoice data to ASCII.

    Args:
        data: Extracted invoice data dictionary.
        fields: Optional list of field names to normalize.
            - If provided: only these fields are normalized, both at the
              top level and inside line_items[] / invoices[].line_items[].
              Example: ['item', 'description', 'po_no']
            - If not provided: preserves the original default behavior —
              top-level normalizes ['item', 'description', 'vendor', 'buyer',
              'customer_job', 'ref_no', 'po_no', 'bill', 'date'] and
              line items normalize ['item', 'description'].

    Returns:
        tuple[dict, dict]: (normalized_data, normalization_report)
            normalization_report keys:
                fields_normalized    – number of field values changed
                total_chars_replaced – number of characters substituted
                field_details        – per-field replacement details
    """
    if not data:
        return data, {'fields_normalized': 0, 'total_chars_replaced': 0, 'field_details': {}}

    normalized_data = copy.deepcopy(data)
    report = {
        'fields_normalized': 0,
        'total_chars_replaced': 0,
        'field_details': {}
    }

    # Determine which fields to target based on whether caller supplied a list
    if fields is not None:
        # Caller-specified: use the same list for top-level AND line items
        top_level_fields = fields
        line_item_fields = fields
    else:
        # Original default behaviour
        top_level_fields = ['item', 'description', 'vendor', 'buyer', 'customer_job',
                            'ref_no', 'po_no', 'bill', 'date']
        line_item_fields = ['item', 'description']

    # Normalize top-level fields
    for field in top_level_fields:
        if field in normalized_data and isinstance(normalized_data[field], str):
            original = normalized_data[field]
            normalized, details = normalize_to_ascii_with_details(original)
            if details['chars_replaced'] > 0:
                normalized_data[field] = normalized
                normalized_data[f'{field}_original'] = original
                report['fields_normalized'] += 1
                report['total_chars_replaced'] += details['chars_replaced']
                report['field_details'][field] = details
                logger.info(f"Normalized {field}: '{original}' -> '{normalized}'")

    # Normalize line_items
    target_lists = []
    if 'line_items' in normalized_data and isinstance(normalized_data['line_items'], list):
        target_lists.append((normalized_data['line_items'], 'line_items'))
    
    if 'invoices' in normalized_data and isinstance(normalized_data['invoices'], list):
        for inv_idx, invoice in enumerate(normalized_data['invoices']):
            if isinstance(invoice, dict) and 'line_items' in invoice and isinstance(invoice['line_items'], list):
                target_lists.append((invoice['line_items'], f'invoices[{inv_idx}].line_items'))

    for line_items_list, path_prefix in target_lists:
        for idx, item in enumerate(line_items_list):
            if not isinstance(item, dict):
                continue
            for field in line_item_fields:
                if field in item and isinstance(item[field], str):
                    original = item[field]
                    normalized, details = normalize_to_ascii_with_details(original)
                    if details['chars_replaced'] > 0:
                        item[field] = normalized
                        item[f'{field}_original'] = original
                        report['fields_normalized'] += 1
                        report['total_chars_replaced'] += details['chars_replaced']
                        field_key = f'{path_prefix}[{idx}].{field}'
                        report['field_details'][field_key] = details
                        logger.info(f"Normalized {field_key}: '{original}' -> '{normalized}'")

    return normalized_data, report


def validate_ascii_only(text: str, field_name: str = 'value') -> tuple[bool, str | None]:
    """
    Validate that a string contains only ASCII characters.

    Args:
        text: String to validate.
        field_name: Name of the field for error messages.

    Returns:
        tuple[bool, str | None]: (is_valid, error_message)
    """
    if not text:
        return True, None

    non_ascii = find_non_ascii_chars(text)
    if non_ascii:
        chars_info = ', '.join([
            f"'{char}' (U+{cp:04X} {name})"
            for _, char, name, cp in non_ascii[:5]
        ])
        error_msg = f"{field_name} contains non-ASCII characters: {chars_info}"
        if len(non_ascii) > 5:
            error_msg += f" and {len(non_ascii) - 5} more"
        return False, error_msg

    return True, None
