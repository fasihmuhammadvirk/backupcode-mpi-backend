"""
Tests for fuzzy correction of OCR/LLM extraction errors.

Tests the entry point `fuzzy_correct_line_items` which internally uses
Levenshtein distance to find close matches in raw PDF text.
"""
import sys
from pathlib import Path

import pytest

# Add scripts path for imports
# Go up from business_logic -> unit -> tests -> mpi_backend -> root
# We need to do this because the backfill invoices script is not part of the `mpi_backend` package yet
# TODO: Move the business logic from scripts/backfill_invoices_data into the mpi_backend package
scripts_path = Path(__file__).parent.parent.parent.parent.parent / "scripts" / "backfill_invoices_data"
sys.path.insert(0, str(scripts_path))

from fuzzy_correction import fuzzy_correct_line_items, fuzzy_correct
from data_validation import validate_line_items_data, validate_header_data
from pdf_utils import normalize_text_to_tokens

pytestmark = pytest.mark.business_logic

def build_extracted_data(item, **overrides):
    """Build extracted data dict with custom item and optional overrides."""
    line_item = {
        "item": item,
        "description": "4 X 10 BLACK SCH40",
        "qty": 35,
        "cost": 105.60,
        "amount": 3696.00,
        **overrides,
    }
    return {"line_items": [line_item]}


def build_header_data(**overrides):
    """Build header data dict with optional overrides."""
    defaults = {
        "date": "8/7/2020",
        "ref_no": "198872",
        "po_no": "SKILLMAN 275",
        "customer_job": "275 SKILLMAN",
        "bill": "MPI PLUMBING CORP",
        "buyer": "MPI PLUMBING CORP",
        "sub_total": "2.73",
        "tax": "0.24",
    }
    return {**defaults, **overrides}


def build_validation_details(missing_item_index=None):
    """Build validation details dict. If missing_item_index is set, marks that item as missing."""
    if missing_item_index is not None:
        return {"missing_fields": [f"item (item {missing_item_index}) - not found in PDF"]}
    return {"missing_fields": []}


# --- Parameterized Correction Tests ---
@pytest.mark.parametrize(
    "input_item,expected_item,should_correct,pdf_text,missing_item_index,_description",
    [
        pytest.param(
            "BWP 4",
            "BWP4",
            True,
            "1 35 35 BWP4 4 X 10 BLACK SCH40 BEVELED END EA 105.60 $3696.00",
            0,
            "extra space in part number",
            id="extra_space_corrected",
        ),
        pytest.param(
            "BWP4",
            "BWP4",
            False,
            "BWP4 4 X 10 BLACK",
            None,
            "already correct - no change needed",
            id="already_correct",
        ),
        pytest.param(
            "TOTALLY_WRONG",
            "TOTALLY_WRONG",
            False,
            "BWP4 FWLLR40 FW4540",
            0,
            "no close match exists in PDF",
            id="no_close_match",
        ),
        pytest.param(
            "F178",
            "FI78",
            True,
            "FI78 7/8 ID SELF SEAL INS 17 2.534 43.08",
            0,
            "OCR confusion: digit 1 vs letter I in short part number",
            id="ocr_I_vs_1_short_part_number",
        ),
    ],
)
def test_fuzzy_correction_scenarios(input_item, expected_item, should_correct, pdf_text, missing_item_index, _description):
    """
    GIVEN extracted data with item field that may need correction
    WHEN fuzzy correction runs against PDF text
    THEN it corrects close matches and skips others
    """
    extracted_data = build_extracted_data(input_item)
    validation_details = build_validation_details(missing_item_index=missing_item_index)

    corrected_data, correction_details = fuzzy_correct_line_items(
        extracted_data, validation_details, pdf_text, ratio_threshold=0.2
    )

    assert corrected_data["line_items"][0]["item"] == expected_item
    if should_correct:
        assert corrected_data["line_items"][0]["item_llm"] == input_item
        assert correction_details["corrections_made"] == 1
    else:
        assert "item_llm" not in corrected_data["line_items"][0]
        assert correction_details["corrections_made"] == 0


def test_bug_validation_passes_when_partial_token_matches():
    """
    GIVEN extracted data with 'BWP 4' (space error) and PDF containing '4' as separate token
    WHEN validation runs
    THEN validation incorrectly passes because '4' matches a PDF token

    Documents the bug where validation has a false positive issue.
    When LLM extracts 'BWP 4' (with space), validation tokenizes it to ['BWP', '4'].
    Since '4' appears elsewhere in PDF (e.g., '4 X 10'), validation passes,
    and fuzzy correction never triggers.
    """
    extracted_data = build_extracted_data("BWP 4")
    # Raw PDF text from 19070c4a331ab813_PH_19_070124_72426158.pdf (ref no 148093, BMW Plumbing Supplies)
    # Contains 'BWP4' (correct) and '4' as separate token (in '4 X 10')
    raw_pdf_text = "1 35 35 BWP4 4 X 10 BLACK SCH40 BEVELED END EA 105.60 $3696.00"
    pdf_normalize_set = set(normalize_text_to_tokens(raw_pdf_text))

    _is_valid, details = validate_line_items_data(extracted_data, pdf_normalize_set)
    corrected_data, correction_details = fuzzy_correct_line_items(extracted_data, details, raw_pdf_text, ratio_threshold=0.2)

    # BUG: There is no correction from BWP 4 to BWP4
    line_item_codes = [x["item"] for x in corrected_data['line_items']]
    assert "BWP4" in line_item_codes
    assert "BWP 4" not in line_item_codes

    # After fix: there should be one correction made
    assert correction_details["corrections_made"] == 1

    # 'line_items': [{'item': 'BWP 4', 'description': '4 X 10 BLACK SCH40', 'qty': 35, 'cost': 105.6, 'amount': 3696.0}]}


# --- Header Field Correction Tests ---

# Realistic BMW invoice PDF template based on actual invoices
BMW_INVOICE_PDF_TEMPLATE = """
Invoice | Date | 8/7/2020 | Invoice # | 198872 | Bill To | MPI PLUMBING CORP |
Ship To | 275 SKILLMAN | BMW PLUMBING SUPPLIES NY INC. | 199 Lee Ave. #678 |
BROOKLYN, NY 11211 | P.O. No. | Ship Date | 8/7/2020 | Project | SKILLMAN 275 |
Phone # | 718-387-1887 | Total | Balance Due | Sales Tax (8.875%) |
Payments/Credits | Item | Description | Qty | Price each | Amount |
CT3412 | 3/4 X 1/2 CCC TEE | 3 | 0.91 | 2.73T | $2.97 | $2.97 | $0.24 | $0.00 |
"""


def test_date_variant_passes_validation_no_fuzzy_correction_needed():
    """
    Date variant matching in the validator now handles zero-padded dates.

    GIVEN model extracts zero-padded date '08/07/2020'
    AND PDF shows short format '8/7/2020'
    WHEN validation runs
    THEN date passes via _date_variants (no fuzzy correction needed)
    AND the extracted format is preserved as-is (semantically correct)
    """
    extracted_data = {
        "date": "08/07/2020",
        "ref_no": "198872",
        "line_items": [
            {"item": "CT3412", "description": "3/4 X 1/2 CCC TEE", "qty": 3, "cost": 0.91, "amount": 2.73}
        ],
    }

    pdf_text = BMW_INVOICE_PDF_TEMPLATE
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    # Validation passes directly via date variant matching
    header_valid, header_details = validate_header_data(extracted_data, pdf_normalize_set)
    assert header_valid is True
    assert "date - not found in PDF" not in header_details["missing_fields"]

    # Fuzzy correction has nothing to fix -- date already passed validation
    _line_items_valid, line_items_details = validate_line_items_data(extracted_data, pdf_normalize_set)
    corrected_data, correction_details = fuzzy_correct(
        extracted_data,
        line_items_details,
        header_details,
        pdf_text,
        ratio_threshold=0.2
    )

    # Date is preserved as extracted (semantically correct, just formatted differently)
    assert corrected_data["date"] == "08/07/2020"
    assert "date_llm" not in corrected_data


@pytest.mark.parametrize(
    "extracted_date,pdf_date,_description",
    [
        pytest.param(
            "08/07/2020",
            "8/7/2020",
            "zero-padded date passes via variant matching, no correction needed",
            id="zero_padded_to_short",
        ),
        pytest.param(
            "01/01/2021",
            "1/1/2021",
            "both month and day zero-padded passes via variant matching",
            id="both_zero_padded",
        ),
        pytest.param(
            "12/25/2020",
            "12/25/2020",
            "exact match passes directly",
            id="exact_match_no_change",
        ),
        pytest.param(
            "08/07/2020",
            "08/07/2020",
            "exact match with zero padding passes directly",
            id="exact_match_zero_padded",
        ),
    ],
)
def test_date_variant_matching_no_correction_needed(extracted_date, pdf_date, _description):
    """
    GIVEN extracted date that may differ from PDF format
    WHEN validation runs
    THEN date passes via _date_variants (fuzzy correction not needed)
    AND the extracted format is preserved as-is
    """
    extracted_data = {
        "date": extracted_date,
        "ref_no": "198872",
        "line_items": [
            {"item": "CT3412", "description": "3/4 X 1/2 CCC TEE", "qty": 3, "cost": 0.91, "amount": 2.73}
        ],
    }

    pdf_text = f"Invoice | Date | {pdf_date} | Invoice # | 198872 | CT3412 3/4 X 1/2 CCC TEE 3 0.91 2.73"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    # Date passes validation directly via variant matching
    header_valid, header_details = validate_header_data(extracted_data, pdf_normalize_set)
    assert header_valid is True
    assert "date - not found in PDF" not in header_details["missing_fields"]

    # Fuzzy correction preserves the extracted format (no correction triggered)
    _line_items_valid, line_items_details = validate_line_items_data(extracted_data, pdf_normalize_set)
    corrected_data, _correction_details = fuzzy_correct(
        extracted_data,
        line_items_details,
        header_details,
        pdf_text,
        ratio_threshold=0.2
    )
    assert corrected_data["date"] == extracted_date


def test_amount_with_negative_credit_memo_format():
    """
    Test that negative amounts in credit memo format are handled properly.

    GIVEN PDF shows negative amount as '$-57.75' or '-$57.75'
    AND model extracts '-57.75'
    WHEN fuzzy correction runs
    THEN amount should validate/correct properly
    """
    extracted_data = {
        "date": "8/7/2020",
        "ref_no": "198872",
        "line_items": [
            {"item": "CREDIT", "description": "RETURN CREDIT", "qty": 1, "cost": -57.75, "amount": -57.75}
        ],
    }

    # PDF shows negative in various formats
    pdf_text = "Invoice | Date | 8/7/2020 | Invoice # | 198872 | CREDIT RETURN CREDIT 1 $-57.75 -57.75"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(extracted_data, pdf_normalize_set)

    # Negative amounts should be found in PDF
    assert is_valid is True
    assert len(details["missing_fields"]) == 0
