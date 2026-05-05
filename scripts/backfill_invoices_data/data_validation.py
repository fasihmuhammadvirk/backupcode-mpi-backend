"""
Data validation utilities for invoice extraction.

This module provides validation functions to ensure extracted invoice data
meets supplier-specific requirements and can be verified against the source PDF.
"""
import re
from typing import Dict, Any, Tuple
import logging
from pdf_utils import normalize_text_to_tokens, _normalize_numeric_string

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^(\d{1,2})([/-])(\d{1,2})\2(\d{2,4})$")


def _date_variants(value: str) -> set[str]:
    """Generate equivalent date string representations.

    Given a date like "02/18/2022", returns all combinations of:
    - leading zero / no leading zero on month and day
    - 2-digit / 4-digit year
    preserving the original separator ("/" or "-").

    Returns an empty set if *value* doesn't look like M/D/Y or M-D-Y.
    """
    m = _DATE_RE.match(value.strip())
    if not m:
        return set()

    month_str, sep, day_str, year_str = m.group(1), m.group(2), m.group(3), m.group(4)
    month = int(month_str)
    day = int(day_str)

    # Build year variants (short / long)
    if len(year_str) == 4:
        year_long = year_str
        year_short = year_str[2:]
    else:
        year_short = year_str
        year_long = f"20{year_str.zfill(2)}"

    variants: set[str] = set()
    for m_s in {str(month), f"{month:02d}"}:
        for d_s in {str(day), f"{day:02d}"}:
            for y_s in (year_short, year_long):
                variants.add(f"{m_s}{sep}{d_s}{sep}{y_s}")

    # Named-month variants: "Feb 18 2022", "Feb 18, 2022", "February 18 2022", etc.
    _MONTH_ABBR = [
        "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    _MONTH_FULL = [
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    for month_name in (_MONTH_ABBR[month], _MONTH_FULL[month]):
        for d_s in (str(day), f"{day:02d}"):
            for y_s in (year_short, year_long):
                variants.add(f"{month_name} {d_s} {y_s}")
                variants.add(f"{month_name} {d_s}, {y_s}")

    return variants

# Field configuration templates
_STANDARD_CONFIG = {
    # Standard field configuration for most suppliers.
    # Defines required and optional fields for invoice line items. Most suppliers
    # use this configuration, which requires all core fields except buyer.
    "required": [
        "item", "description", "qty", "cost", "amount"
        ],
}

_FEE_CONFIG = {
    # Relaxed field configuration for fee/surcharge line items (e.g., "Gas Surcharge",
    # "Delivery Fee"). These rows legitimately lack item codes, quantities, and unit costs.
    "required": ["description", "amount"],
}

_PE_CONFIG = {
    # Plumbing Exchange invoices do not include product item codes.
    "required": ["description", "qty", "cost", "amount"],
}

# A line item is classified as "fee" when qty AND cost are both empty/blank/None.
# The item field is NOT checked because some models duplicate the fee description
# into the item field (e.g., item="Gas Surcharge", description="Gas Surcharge").
_FEE_EMPTY_FIELDS = ("qty", "cost")


_NEGATIVE_RE = re.compile(r"^-(.+)$")


def _tokens_match_pdf(
    tokens: list[str],
    pdf_set: set[str],
    *,
    require_all: bool = False,
    raw_value: str | None = None,
) -> bool:
    """Check if tokens match the PDF set, with absolute-value fallback for negatives.

    Credit/return invoices have negative values (e.g., qty="-16", amount="-916.80")
    but the PDF shows positive numbers. When a negative token doesn't match,
    we try the absolute value (strip the leading minus sign).

    ``raw_value`` is the original field string *before* token-normalization.
    It's needed because normalization strips trailing zeros (e.g. "-916.80" -->
    "-916.8") but the PDF may contain "916.80-" (trailing-minus notation with
    the original formatting preserved).
    """
    if not tokens:
        return False

    def _token_in_pdf(token: str) -> bool:
        if token in pdf_set:
            return True
        m = _NEGATIVE_RE.match(token)
        if m:
            abs_token = _normalize_numeric_string(m.group(1))
            if abs_token in pdf_set:
                return True
            # PDF may show trailing-minus notation (e.g., "916.80-").
            if f"{abs_token}-" in pdf_set:
                return True
            # Normalization strips trailing zeros ("-916.80" -> "-916.8"),
            # so also check the original (pre-normalization) absolute value
            # with trailing minus (e.g., "916.80-").
            if raw_value is not None:
                raw_m = _NEGATIVE_RE.match(raw_value.strip())
                if raw_m and f"{raw_m.group(1)}-" in pdf_set:
                    return True
        return False

    if require_all:
        return all(_token_in_pdf(t) for t in tokens)
    return any(_token_in_pdf(t) for t in tokens)


def _classify_line_item(item: dict) -> str:
    """Classify a line item as 'product' or 'fee' based on structural signals.

    A line item is 'fee' when qty and cost are both empty/blank/None.
    This covers surcharges, delivery fees, and similar non-product rows
    regardless of whether the model populated the item field.
    """
    for field in _FEE_EMPTY_FIELDS:
        value = item.get(field)
        if value is not None and (not isinstance(value, str) or value.strip() != ""):
            return "product"
    return "fee"


def validate_line_items_data(
    extracted_data: Dict[str, Any],
    pdf_normalize_set: set[str] | None = None,
    raw_pdf_text: str | None = None,
) -> tuple[bool, dict]:
    """
    Validate extracted invoice line items data against requirements and PDF content.

    This function performs comprehensive validation of extracted invoice line items:
    1. Checks that line_items exist and are non-empty
    2. Validates all required fields are present and non-empty in each line item
    3. Verifies field values can be found in the PDF (hallucination check)
    4. Ensures at least one product line item exists (excluding "10 Materials")

    Args:
        extracted_data: Dictionary containing extracted invoice data. Must have
            a 'line_items' key containing a list of line item dictionaries.
            Each line item should contain fields like item, description, qty,
            cost, amount, date, ref_no, customer_job, vendor, etc.
        pdf_normalize_set: Optional set of normalized text tokens from the PDF
            file. Used to verify that extracted field values actually exist in
            the source document (hallucination detection). If None or empty,
            validation will fail immediately.

    Returns:
        tuple[bool, dict]: A tuple containing:
            - bool: True if validation passes, False otherwise
            - dict: Validation details with keys:
                - 'fields_checked': Number of fields checked (across all line items)
                - 'fields_passed': Number of fields that passed validation
                - 'missing_fields': List of field names that failed validation

    Validation Rules:
        1. Must have 'line_items' key with non-empty list
        2. All required fields (supplier-specific) must be present and non-empty
        3. For non-vendor fields, values must be found in pdf_normalize_set
           (numeric values are normalized before comparison)
        4. At least one product line item must exist (item != "10 Materials"
           with valid qty, cost, and amount)

    Note:
        The vendor field is exempt from PDF content verification. Field values
        are normalized using the same normalization function as PDF text to ensure
        consistent comparison (e.g., "1,234.50" -> "1234.5").
    """

    if not extracted_data or "line_items" not in extracted_data:
        logger.info("Line items data validation result: False, missing fields: ['line_items']")
        return False, {'fields_checked': 0, 'fields_passed': 0, 'missing_fields': ['line_items']}

    if not extracted_data["line_items"] or len(extracted_data["line_items"]) == 0:
        logger.info("Line items data validation result: False, missing fields: ['line_items (empty)']")
        return False, {'fields_checked': 0, 'fields_passed': 0, 'missing_fields': ['line_items (empty)']}

    supplier_config = _STANDARD_CONFIG
    vendor_name = (extracted_data.get("vendor") or "").strip().upper()
    if vendor_name == "PLUMBING EXCHANGE":
        supplier_config = _PE_CONFIG

    if not pdf_normalize_set or len(pdf_normalize_set) == 0:
        logger.warning("PDF normalization returned empty set - cannot validate field values against PDF")
        return False, {'fields_checked': 0, 'fields_passed': 0, 'missing_fields': ['pdf_normalize_set (empty)']}

    required_fields = supplier_config["required"]
    missing_fields = []
    fields_checked = 0
    fields_passed = 0

    # Precompute uppercase PDF tokens once for item field validation
    pdf_tokens_upper = {t.upper() for t in pdf_normalize_set}
    # Uppercase raw text for item field fallback (token normalization strips
    # letter suffixes from product codes like 14400N -> 14400, so we also
    # check the raw PDF text for an exact substring match)
    raw_pdf_upper = raw_pdf_text.upper() if raw_pdf_text else ""

    for idx, item in enumerate(extracted_data["line_items"]):
        item_type = _classify_line_item(item)
        if item_type == "fee":
            item_required = _FEE_CONFIG["required"]
        elif required_fields == _STANDARD_CONFIG["required"] and not (item.get("item") or "").strip():
            # Line item has no product code -- don't require the item field
            # (some suppliers like Plumbing Exchange never include item codes)
            item_required = _PE_CONFIG["required"]
        else:
            item_required = required_fields
        for field in item_required:
            field_value = item.get(field)
            fields_checked += 1

            if field_value is None or (isinstance(field_value, str) and field_value.strip() == ""):
                missing_fields.append(f"{field} (item {idx})")

            elif field != "vendor" and field_value:
                matched = False

                # For 'item' field (part numbers), check token set first then
                # fall back to raw PDF text. The token set normalizes values like
                # "14400N" -> "14400" which breaks product code matching.
                if field == "item":
                    field_value_upper = str(field_value).strip().upper()
                    if field_value_upper in pdf_tokens_upper:
                        matched = True
                    elif field_value_upper in raw_pdf_upper:
                        matched = True
                else:
                    normalized_tokens = normalize_text_to_tokens(str(field_value))
                    if field == "description" and item_type == "fee":
                        # Fee rows: description is the main anti-hallucination signal
                        # (item/qty/cost are absent). Require ALL tokens to match so
                        # e.g. "Fuel Surcharge" is not accepted when the PDF only
                        # contains "Gas Surcharge" (shared "surcharge" token).
                        matched = _tokens_match_pdf(
                            normalized_tokens, pdf_normalize_set, require_all=True
                        )
                    else:
                        matched = _tokens_match_pdf(
                            normalized_tokens, pdf_normalize_set,
                            raw_value=str(field_value),
                        )

                if matched:
                    fields_passed += 1
                else:
                    missing_fields.append(f"{field} (item {idx}) - not found in PDF")
            elif field == "vendor":
                # Vendor field is exempt from PDF check, count as passed if present
                fields_passed += 1
            else:
                fields_passed += 1

    has_product_items = False
    for item in extracted_data["line_items"]:
        item_code = (item.get("item") or "").strip()
        if not item_code or item_code != "10 Materials":
            if item.get("qty") and item.get("cost") and item.get("amount"):
                has_product_items = True
                break

    if not has_product_items:
        missing_fields.append("product_line_items")

    is_valid = len(missing_fields) == 0
    details = {
        'fields_checked': fields_checked,
        'fields_passed': fields_passed,
        'missing_fields': missing_fields
    }

    logger.info(f"Line items data validation result: {is_valid}, missing fields: {missing_fields}")
    return is_valid, details

def _date_in_pdf(value: str, pdf_set: set[str]) -> bool:
    """Check if a date value matches the PDF token set in any recognized format.

    Tries single-token variants first (e.g., "04/15/2021"), then multi-word
    variants where each token is checked individually (e.g., "Apr 15 2021"
    -> {"apr", "15", "2021"} all present in pdf_set).
    """
    variants = _date_variants(value)
    if not variants:
        return False
    if variants & pdf_set:
        return True
    for variant in variants:
        variant_tokens = normalize_text_to_tokens(str(variant))
        if variant_tokens and all(t in pdf_set for t in variant_tokens):
            return True
    return False


def validate_header_data(extracted_data: Dict[str, Any], normalize_set: set[str]) -> tuple[bool, dict]:
    """
    Validate extracted invoice header data against PDF content.

    This function validates that header fields (non-line-item fields) from the
    extracted invoice data can be found in the normalized PDF text. This serves
    as a hallucination check to ensure the AI model didn't invent values that
    don't exist in the source document.

    Args:
        extracted_data: Dictionary containing extracted invoice data with header
            fields such as date, ref_no, po_no, customer_job, bill, sub_total, tax,
            vendor, buyer, etc.
        normalize_set: Set of normalized text tokens from the PDF file. Used to
            verify that extracted field values actually exist in the source document.
            Must be non-empty for validation to pass.

    Returns:
        tuple[bool, dict]: A tuple containing:
            - bool: True if all header fields are found in PDF, False otherwise
            - dict: Validation details with keys:
                - 'fields_checked': Number of fields checked
                - 'fields_passed': Number of fields that passed validation
                - 'missing_fields': List of field names that failed validation

    Validation Rules:
        1. Fields 'vendor', 'line_items', 'confidence_score', 'prompt_hash', and 'doc_type'
           are exempt from PDF content verification (vendor may not be in PDF, line_items
           is a list, confidence_score is AI-generated, prompt_hash is metadata, doc_type
           is a classification not extracted text)
        2. All other fields with non-empty values must have their values found in
           the normalized PDF text
        3. Field values are normalized before comparison (numeric values, whitespace, etc.)

    Note:
        This function only validates that field values exist in the PDF, not that
        they are correct. It's a hallucination detection mechanism to catch cases
        where the AI model generates values not present in the source document.
    """
    if not normalize_set:
        logger.info("Header data validation result: False, missing fields: ['normalize_set (empty)']")
        return False, {'fields_checked': 0, 'fields_passed': 0, 'missing_fields': ['normalize_set (empty)']}

    if not extracted_data:
        logger.info("Header data validation result: False, missing fields: ['extracted_data (empty)']")
        return False, {'fields_checked': 0, 'fields_passed': 0, 'missing_fields': ['extracted_data (empty)']}

    missing_fields = []
    fields_checked = 0
    fields_passed = 0

    for field, field_value in extracted_data.items():
        if field in ["date", "ref_no", "po_no", "customer_job", "bill", "buyer", "sub_total", "tax", "freight", "total"] and field_value:
            fields_checked += 1
            matched = False

            if field == "date":
                matched = _date_in_pdf(str(field_value), normalize_set)

            # Freight field: .00 should be as valid as 0.00 and its variants
            if field == "freight":
                zero_patt = r"^0?\.?0*$"
                if re.match(zero_patt, field_value):
                    matched = True

            # Default token-based matching (also used as fallback when date doesn't parse)
            # Includes absolute-value fallback for credit/return invoices where
            # the model extracts negative values but the PDF shows positive numbers.
            if not matched:
                normalized_tokens = normalize_text_to_tokens(str(field_value))
                matched = _tokens_match_pdf(
                    normalized_tokens, normalize_set, raw_value=str(field_value)
                )

            # po_no fallback: slash-separated compound values.
            # AF Supply PO numbers combine a job number and SAP order number
            # (e.g. "3992482/8001126807"). The model extracts them joined with
            # "/" but in the PDF the two numbers sit on separate lines, so the
            # tokenizer produces two independent tokens. The PDF text often
            # renders as "3992482 /8001126807" (space-slash-number), so the
            # tokenizer produces "/8001126807" with a leading slash. We strip
            # slashes from both sides when comparing to handle this.
            if not matched and field == "po_no" and "/" in str(field_value):
                parts = [p.strip() for p in str(field_value).split("/") if p.strip()]
                slash_stripped_set = {t.strip("/") for t in normalize_set}
                if parts and all(
                    any(t.strip("/") in slash_stripped_set for t in normalize_text_to_tokens(part))
                    for part in parts
                ):
                    matched = True

            if matched:
                fields_passed += 1
            else:
                missing_fields.append(f"{field} - not found in PDF")

    is_valid = len(missing_fields) == 0
    details = {
        'fields_checked': fields_checked,
        'fields_passed': fields_passed,
        'missing_fields': missing_fields
    }

    logger.info(f"Header data validation result: {is_valid}, missing fields: {missing_fields}")
    return is_valid, details


def _parse_dollar(value) -> Tuple[bool, float]:
    """Parse a dollar string like '$1,234.56' into a float. Returns (success, amount)."""
    if value is None:
        return False, 0.0
    s = str(value).strip()
    if s == '':
        return False, 0.0
    # Strip $, commas, whitespace
    s = re.sub(r'[$,\s]', '', s)
    try:
        return True, float(s)
    except (ValueError, TypeError):
        return False, 0.0


def validate_financial_totals(extracted_data: Dict[str, Any], tolerance: float = 0.02) -> Tuple[bool, dict]:
    """Validate that extracted financial fields are internally consistent.

    Sums the actual components: line_items amounts + misc_charges + tax + freight
    and checks that the result matches the extracted total. This avoids ambiguity
    about whether sub_total already includes misc charges.

    Args:
        extracted_data: Extracted invoice data dict.
        tolerance: Maximum allowed absolute difference between expected and actual total.

    Returns:
        (is_valid, details) where details contains expected_total, actual_total,
        difference, breakdown, and an optional message if parsing failed.
    """
    details: Dict[str, Any] = {
        'expected_total': None,
        'actual_total': None,
        'difference': None,
        'breakdown': {},
        'message': None,
    }

    # Parse total (required)
    ok_total, total = _parse_dollar(extracted_data.get('total'))
    if not ok_total:
        details['message'] = 'total could not be parsed'
        logger.info(f"Financial validation result: False, {details['message']}")
        return False, details

    # Sum line item amounts
    line_items = extracted_data.get('line_items', []) or []
    line_items_sum = 0.0
    for item in line_items:
        if isinstance(item, dict):
            _, amt = _parse_dollar(item.get('amount'))
            line_items_sum += amt

    # Parse optional fields -- default to 0
    _, tax = _parse_dollar(extracted_data.get('tax'))
    _, freight = _parse_dollar(extracted_data.get('freight'))

    # Sum misc charges
    misc_charges = extracted_data.get('misc_charges', []) or []
    misc_sum = 0.0
    for charge in misc_charges:
        if isinstance(charge, dict):
            _, amt = _parse_dollar(charge.get('amount'))
            misc_sum += amt

    expected_total = line_items_sum + misc_sum + tax + freight
    difference = abs(expected_total - total)

    details['expected_total'] = round(expected_total, 2)
    details['actual_total'] = round(total, 2)
    details['difference'] = round(difference, 2)
    details['breakdown'] = {
        'line_items_sum': round(line_items_sum, 2),
        'tax': round(tax, 2),
        'freight': round(freight, 2),
        'misc_charges_sum': round(misc_sum, 2),
    }

    is_valid = difference <= tolerance
    logger.info(
        f"Financial validation result: {is_valid}, "
        f"expected={expected_total:.2f}, actual={total:.2f}, diff={difference:.2f}"
    )
    return is_valid, details
