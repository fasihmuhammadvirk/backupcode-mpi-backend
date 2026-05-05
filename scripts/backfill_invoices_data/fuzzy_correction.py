"""
Fuzzy matching correction layer for invoice extraction.

This module provides post-validation fuzzy matching to correct OCR/LLM extraction
errors in `item` and `description` fields by comparing against raw PDF text
using Levenshtein distance.
"""
import re
import copy
import logging
from typing import Any

from rapidfuzz.distance import Levenshtein

logger = logging.getLogger(__name__)

# Fields eligible for fuzzy correction (string fields only)
CORRECTABLE_LINE_ITEM_FIELDS = {"item", "description"}
CORRECTABLE_HEADER_FIELDS = {"date"}

# Backwards compatibility alias
CORRECTABLE_FIELDS = CORRECTABLE_LINE_ITEM_FIELDS


def parse_missing_field_entry(entry: str) -> tuple[str, int] | None:
    """
    Parse a missing field entry from validation details.

    Parses entries in the format: 'field (item N) - not found in PDF'

    Args:
        entry: The missing field entry string from validation details.

    Returns:
        tuple[str, int] | None: A tuple of (field_name, item_index) if the entry
            matches the expected format and is a correctable field, None otherwise.

    Examples:
        >>> parse_missing_field_entry("item (item 0) - not found in PDF")
        ('item', 0)
        >>> parse_missing_field_entry("description (item 2) - not found in PDF")
        ('description', 2)
        >>> parse_missing_field_entry("qty (item 0) - not found in PDF")
        None  # qty is not a correctable field
    """
    # Pattern: "field (item N) - not found in PDF"
    pattern = r"^(\w+) \(item (\d+)\) - not found in PDF$"
    match = re.match(pattern, entry)

    if not match:
        return None

    field_name = match.group(1)
    item_idx = int(match.group(2))

    # Only return if field is correctable
    if field_name not in CORRECTABLE_LINE_ITEM_FIELDS:
        return None

    return (field_name, item_idx)


def extract_pdf_candidate_tokens(raw_pdf_text: str, min_length: int = 3) -> list[str]:
    """
    Extract candidate strings from PDF text for fuzzy matching.

    This function extracts various token types from the raw PDF text that could
    potentially match extracted field values:
    - Whitespace-split tokens
    - Alphanumeric sequences with dashes (part numbers like "21504-Z-16-22")
    - Full lines (for descriptions)

    Args:
        raw_pdf_text: Raw text extracted from the PDF.
        min_length: Minimum length for candidate tokens (default 3).
            Tokens shorter than this are filtered out to avoid false matches.

    Returns:
        list[str]: List of unique candidate strings from the PDF, sorted by length
            (longest first) to prefer more specific matches.
    """
    if not raw_pdf_text:
        return []

    candidates = set()

    # Whitespace-split tokens
    for token in raw_pdf_text.split():
        token = token.strip()
        if len(token) >= min_length:
            candidates.add(token)

    # Alphanumeric sequences with dashes (part numbers)
    # Pattern matches things like "21504-Z-16-22", "GRP2D", "B-FPPCP0012"
    part_number_pattern = r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*"
    for match in re.finditer(part_number_pattern, raw_pdf_text):
        token = match.group()
        if len(token) >= min_length:
            candidates.add(token)

    # Full lines (for descriptions) - strip and filter empty/short lines
    for line in raw_pdf_text.split('\n'):
        line = line.strip()
        if len(line) >= min_length:
            candidates.add(line)

    # Sort by length (longest first) to prefer more specific matches
    return sorted(candidates, key=len, reverse=True)


def find_best_fuzzy_match(
    query: str,
    candidates: list[str],
    ratio_threshold: float
) -> tuple[str | None, float]:
    """
    Find the closest match to query using Levenshtein distance.

    Searches through candidates to find the best match based on Levenshtein
    distance ratio. The ratio is calculated as:
        distance / max(len(query), len(candidate))

    A ratio of 0.0 means exact match, 0.2 means ~80% similar.

    Args:
        query: The string to find a match for.
        candidates: List of candidate strings from the PDF.
        ratio_threshold: Maximum acceptable ratio for a match (e.g., 0.2).
            Matches with ratio > threshold are rejected.

    Returns:
        tuple[str | None, float]: A tuple of (best_match, ratio).
            - best_match: The candidate with lowest ratio, or None if no match
              meets the threshold.
            - ratio: The Levenshtein ratio of the best match (0.0 = exact match).

    Note:
        Comparison is case-insensitive to handle OCR case differences, but the
        original case of the candidate is preserved in the result.
    """
    if not query or not candidates:
        return (None, 1.0)

    query_lower = query.lower()
    best_match = None
    best_ratio = 1.0

    for candidate in candidates:
        candidate_lower = candidate.lower()

        # Calculate Levenshtein distance
        distance = Levenshtein.distance(query_lower, candidate_lower)
        max_len = max(len(query), len(candidate))

        if max_len == 0:
            continue

        ratio = distance / max_len

        # Check for exact match (case-insensitive)
        if ratio == 0.0:
            return (candidate, 0.0)

        # Single-character edits in short strings are almost always OCR
        # confusion (I/1, O/0, l/1). Without this, "F178" vs "FI78" gives
        # ratio=0.25 exceeding the 0.2 threshold.
        if distance <= 1 and max_len >= 3:
            effective_ratio = min(ratio, ratio_threshold)
        else:
            effective_ratio = ratio

        # Track best match within threshold
        if effective_ratio <= ratio_threshold and ratio < best_ratio:
            best_ratio = ratio
            best_match = candidate

    return (best_match, best_ratio)


def fuzzy_correct_line_items(
    extracted_data: dict[str, Any],
    validation_details: dict[str, Any],
    raw_pdf_text: str,
    ratio_threshold: float = 0.2
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Apply fuzzy corrections to failed string fields in line items.

    This function identifies fields that failed validation (not found in PDF)
    and attempts to find close matches in the raw PDF text using Levenshtein
    distance. If a match is found within the threshold, the field is corrected
    and the original LLM value is preserved in a `<field>_llm` field.

    Args:
        extracted_data: Dictionary containing extracted invoice data with line_items.
        validation_details: Validation details from validate_line_items_data(),
            must contain 'missing_fields' list with entries like
            "item (item 0) - not found in PDF".
        raw_pdf_text: Raw text extracted from the PDF for candidate matching.
        ratio_threshold: Maximum Levenshtein ratio for accepting a match (default 0.2).
            Ratio = distance / max_length. Lower = stricter.

    Returns:
        tuple[dict, dict]: A tuple containing:
            - corrected_data: Copy of extracted_data with corrections applied.
            - correction_details: Dictionary with:
                - 'corrections_made': Number of corrections applied
                - 'corrections': List of correction records, each with:
                    - 'item_idx': Line item index
                    - 'field': Field name that was corrected
                    - 'original': Original LLM-extracted value
                    - 'corrected': Corrected value from PDF
                    - 'ratio': Levenshtein ratio of the match

    Example:
        >>> corrected, details = fuzzy_correct_line_items(data, validation, pdf_text)
        >>> details
        {
            'corrections_made': 1,
            'corrections': [
                {'item_idx': 0, 'field': 'item', 'original': '21504-2-16-22',
                 'corrected': '21504-Z-16-22', 'ratio': 0.07}
            ]
        }
    """

    # Initialize result structures
    corrected_data = copy.deepcopy(extracted_data)
    correction_details = {
        'corrections_made': 0,
        'corrections': []
    }

    # Validate inputs
    if not raw_pdf_text:
        logger.warning("No PDF text provided for fuzzy correction")
        return corrected_data, correction_details

    missing_fields = validation_details.get('missing_fields', [])
    if not missing_fields:
        return corrected_data, correction_details

    line_items = corrected_data.get('line_items', [])
    if not line_items:
        return corrected_data, correction_details

    # Extract candidate tokens from PDF
    candidates = extract_pdf_candidate_tokens(raw_pdf_text)
    if not candidates:
        logger.warning("No candidate tokens extracted from PDF")
        return corrected_data, correction_details

    # Parse missing fields and identify correctable entries
    fields_to_correct = []
    for entry in missing_fields:
        parsed = parse_missing_field_entry(entry)
        if parsed:
            fields_to_correct.append(parsed)

    if not fields_to_correct:
        logger.debug("No correctable fields found in missing_fields")
        return corrected_data, correction_details

    logger.info(f"Attempting fuzzy correction for {len(fields_to_correct)} fields")

    # Apply corrections
    for field_name, item_idx in fields_to_correct:
        if item_idx >= len(line_items):
            logger.warning(f"Item index {item_idx} out of range for line_items")
            continue

        item = line_items[item_idx]
        original_value = item.get(field_name)

        # Skip empty values
        if not original_value or (isinstance(original_value, str) and not original_value.strip()):
            continue

        original_str = str(original_value).strip()

        # Find best fuzzy match
        best_match, ratio = find_best_fuzzy_match(original_str, candidates, ratio_threshold)

        if best_match is not None:
            # Apply correction
            item[field_name] = best_match
            item[f"{field_name}_llm"] = original_value

            correction_record = {
                'item_idx': item_idx,
                'field': field_name,
                'original': original_value,
                'corrected': best_match,
                'ratio': round(ratio, 4)
            }
            correction_details['corrections'].append(correction_record)
            correction_details['corrections_made'] += 1

            logger.info(
                f"Fuzzy corrected {field_name} in item {item_idx}: "
                f"'{original_value}' -> '{best_match}' (ratio={ratio:.4f})"
            )

    return corrected_data, correction_details


def parse_missing_header_field_entry(entry: str) -> str | None:
    """
    Parse a missing header field entry from validation details.

    Parses entries in the format: 'field - not found in PDF'

    Args:
        entry: The missing field entry string from validation details.

    Returns:
        str | None: The field name if the entry matches the expected format
            and is a correctable header field, None otherwise.

    Examples:
        >>> parse_missing_header_field_entry("date - not found in PDF")
        'date'
        >>> parse_missing_header_field_entry("sub_total - not found in PDF")
        None  # sub_total is not a correctable header field
    """
    # Pattern: "field - not found in PDF"
    pattern = r"^(\w+) - not found in PDF$"
    match = re.match(pattern, entry)

    if not match:
        return None

    field_name = match.group(1)

    # Only return if field is correctable
    if field_name not in CORRECTABLE_HEADER_FIELDS:
        return None

    return field_name


def fuzzy_correct(
    extracted_data: dict[str, Any],
    line_items_details: dict[str, Any],
    header_details: dict[str, Any],
    raw_pdf_text: str,
    ratio_threshold: float = 0.2
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Apply fuzzy corrections to failed fields in both header and line items.

    This function identifies fields that failed validation (not found in PDF)
    and attempts to find close matches in the raw PDF text using Levenshtein
    distance. If a match is found within the threshold, the field is corrected
    and the original LLM value is preserved in a `<field>_llm` field.

    Args:
        extracted_data: Dictionary containing extracted invoice data with header
            fields and line_items.
        line_items_details: Validation details from validate_line_items_data(),
            must contain 'missing_fields' list with entries like
            "item (item 0) - not found in PDF".
        header_details: Validation details from validate_header_data(),
            must contain 'missing_fields' list with entries like
            "date - not found in PDF".
        raw_pdf_text: Raw text extracted from the PDF for candidate matching.
        ratio_threshold: Maximum Levenshtein ratio for accepting a match (default 0.2).
            Ratio = distance / max_length. Lower = stricter.

    Returns:
        tuple[dict, dict]: A tuple containing:
            - corrected_data: Copy of extracted_data with corrections applied.
            - correction_details: Dictionary with:
                - 'corrections_made': Number of corrections applied
                - 'corrections': List of correction records, each with:
                    - 'field': Field name that was corrected
                    - 'original': Original LLM-extracted value
                    - 'corrected': Corrected value from PDF
                    - 'ratio': Levenshtein ratio of the match
                    - 'item_idx': (line items only) Line item index

    Example:
        >>> corrected, details = fuzzy_correct(data, line_details, header_details, pdf_text)
        >>> details
        {
            'corrections_made': 2,
            'corrections': [
                {'field': 'date', 'original': '08/07/2020', 'corrected': '8/7/2020', 'ratio': 0.1},
                {'item_idx': 0, 'field': 'item', 'original': '21504-2-16-22',
                 'corrected': '21504-Z-16-22', 'ratio': 0.07}
            ]
        }
    """
    # Initialize result structures
    corrected_data = copy.deepcopy(extracted_data)
    correction_details = {
        'corrections_made': 0,
        'corrections': []
    }

    # Validate inputs
    if not raw_pdf_text:
        logger.warning("No PDF text provided for fuzzy correction")
        return corrected_data, correction_details

    # Extract candidate tokens from PDF
    candidates = extract_pdf_candidate_tokens(raw_pdf_text)
    if not candidates:
        logger.warning("No candidate tokens extracted from PDF")
        return corrected_data, correction_details

    # 1. Correct header fields
    header_missing_fields = header_details.get('missing_fields', [])
    for entry in header_missing_fields:
        field_name = parse_missing_header_field_entry(entry)
        if not field_name:
            continue

        original_value = corrected_data.get(field_name)
        if not original_value or (isinstance(original_value, str) and not original_value.strip()):
            continue

        original_str = str(original_value).strip()

        # Find best fuzzy match
        best_match, ratio = find_best_fuzzy_match(original_str, candidates, ratio_threshold)

        if best_match is not None:
            # Apply correction
            corrected_data[field_name] = best_match
            corrected_data[f"{field_name}_llm"] = original_value

            correction_record = {
                'field': field_name,
                'original': original_value,
                'corrected': best_match,
                'ratio': round(ratio, 4)
            }
            correction_details['corrections'].append(correction_record)
            correction_details['corrections_made'] += 1

            logger.info(
                f"Fuzzy corrected header {field_name}: "
                f"'{original_value}' -> '{best_match}' (ratio={ratio:.4f})"
            )

    # 2. Correct line item fields
    line_items_missing_fields = line_items_details.get('missing_fields', [])
    line_items = corrected_data.get('line_items', [])

    if line_items_missing_fields and line_items:
        fields_to_correct = []
        for entry in line_items_missing_fields:
            parsed = parse_missing_field_entry(entry)
            if parsed:
                fields_to_correct.append(parsed)

        for field_name, item_idx in fields_to_correct:
            if item_idx >= len(line_items):
                logger.warning(f"Item index {item_idx} out of range for line_items")
                continue

            item = line_items[item_idx]
            original_value = item.get(field_name)

            if not original_value or (isinstance(original_value, str) and not original_value.strip()):
                continue

            original_str = str(original_value).strip()

            # Find best fuzzy match
            best_match, ratio = find_best_fuzzy_match(original_str, candidates, ratio_threshold)

            if best_match is not None:
                # Apply correction
                item[field_name] = best_match
                item[f"{field_name}_llm"] = original_value

                correction_record = {
                    'item_idx': item_idx,
                    'field': field_name,
                    'original': original_value,
                    'corrected': best_match,
                    'ratio': round(ratio, 4)
                }
                correction_details['corrections'].append(correction_record)
                correction_details['corrections_made'] += 1

                logger.info(
                    f"Fuzzy corrected line item {field_name} in item {item_idx}: "
                    f"'{original_value}' -> '{best_match}' (ratio={ratio:.4f})"
                )

    return corrected_data, correction_details
