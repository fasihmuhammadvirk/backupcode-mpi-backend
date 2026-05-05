"""Tests for data validation of extracted invoice data."""
import sys
from pathlib import Path

import pytest

# We need to do this because the backfill invoices script is not part of the `mpi_backend` package yet
# TODO: Move the business logic from scripts/backfill_invoices_data into the mpi_backend package
scripts_path = Path(__file__).parent.parent.parent.parent.parent / "scripts" / "backfill_invoices_data"
sys.path.insert(0, str(scripts_path))

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


@pytest.mark.parametrize(
    "input_item,pdf_text,expected_valid,_description",
    [
        pytest.param(
            "BWP4",
            "1 35 35 BWP4 4 X 10 BLACK SCH40 105.60 3696.00",
            True,
            "exact match passes",
            id="exact_match",
        ),
        pytest.param(
            "BWP 4",
            "1 35 35 BWP4 4 X 10 BLACK SCH40 105.60 3696.00",
            False,
            "item with extra space fails (partial token '4' should not pass)",
            id="extra_space_fails",
        ),
        pytest.param(
            "TOTALLY_WRONG",
            "BWP4 FWLLR40 FW4540",
            False,
            "no match fails",
            id="no_match",
        ),
    ],
)
def test_item_field_validation(input_item, pdf_text, expected_valid, _description):
    """
    GIVEN extracted data with item field
    WHEN validation runs against PDF tokens
    THEN item field requires complete value match (not partial token match)
    """
    extracted_data = build_extracted_data(input_item)
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, _details = validate_line_items_data(extracted_data, pdf_normalize_set)

    assert is_valid == expected_valid


def test_amounts_present_in_pdf_with_suffix_T():
    """
    BUG: Validation fails when PDF contains amount with `T` indicating that is a taxable amount,
    causing the validation score to be low (<80)

    GIVEN extracted data with amounts
    WHEN the validation is run
    THEN validation fails for amount fields
    """
    extracted_data = {
        "line_items": [
            {
                "qty": 2,
                "cost": 185.68,
                "item": "006-ST4",
                "amount": 371.36, # It is 371.36T in the PDF
                "description": "3/4 IPS BRZ THRD CIRCULATOR",
            },
            {
                "qty": 4,
                "cost": 1.41,
                "item": "CM1234",
                "amount": 5.64, # It is 5.64T in the PDF
                "description": "1/2 X 3/4 CM ADAPTER",
            },
            {
                "qty": 3,
                "cost": 1.81,
                "item": "OA-90220",
                "amount": 5.43,
                "description": "DEEP JHONI RING WAX SEAL",
            },
        ]
    }

    # PDF contains items, descriptions, qtys, costs - but NOT the calculated amounts
    pdf_text = """
    2 185.68 371.36T 006-ST4 3/4 IPS BRZ THRD CIRCULATOR
    4 CM1234 1/2 X 3/4 CM ADAPTER 1.41 5.64T
    3 1.81 5.43T OA-90220 DEEP JHONI RING WAX SEAL
    """
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(extracted_data, pdf_normalize_set)

    # Validation should be true
    assert is_valid is True
    assert details["fields_checked"] == 15  # 5 fields * 3 items
    assert details["fields_passed"] == 15  # item, description, qty, cost pass for all 3
    assert len(details["missing_fields"]) == 0 # BUG: There were 3 missing fields, all amounts


def build_fee_line_item(**overrides):
    """Build a fee/surcharge line item with only description and amount."""
    return {
        "item": "",
        "description": "Gas Surcharge",
        "qty": "",
        "cost": "",
        "amount": 35.00,
        **overrides,
    }


def test_fee_only_invoice_fails_product_items_check():
    """
    GIVEN an invoice with ONLY fee line items (no product items)
    WHEN validation runs
    THEN it fails because has_product_items is False
    AND fee fields themselves pass (no missing item/qty/cost)
    """
    extracted_data = {"line_items": [build_fee_line_item()]}
    pdf_text = "Gas Surcharge 35"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(extracted_data, pdf_normalize_set)

    assert is_valid is False
    assert "product_line_items" in details["missing_fields"]
    assert not any("item (item" in f for f in details["missing_fields"])
    assert not any("qty (item" in f for f in details["missing_fields"])
    assert not any("cost (item" in f for f in details["missing_fields"])


def test_mixed_product_and_fee_items_validation():
    """
    GIVEN an invoice with product line items AND a fee/surcharge line item
    WHEN validation runs
    THEN validation passes (fee row does not penalize score)
    AND fields_checked reflects reduced checks for fee rows (5 product + 2 fee = 7)
    """
    extracted_data = {
        "line_items": [
            {
                "item": "BWP4",
                "description": "4 X 10 BLACK SCH40",
                "qty": 35,
                "cost": 105.60,
                "amount": 3696.00,
            },
            build_fee_line_item(),
        ]
    }
    pdf_text = "BWP4 4 X 10 BLACK SCH40 35 105.60 3696.00 Gas Surcharge 35"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(extracted_data, pdf_normalize_set)

    assert is_valid is True
    assert len(details["missing_fields"]) == 0
    assert details["fields_checked"] == 7
    assert details["fields_passed"] == 7


def test_fee_item_with_none_values_classified_correctly():
    """
    GIVEN a fee line item where item/qty/cost are None (not empty string)
    WHEN validation runs
    THEN it is still classified as fee (None counts as empty)
    """
    extracted_data = {
        "line_items": [
            {
                "item": "BWP4",
                "description": "4 X 10 BLACK SCH40",
                "qty": 35,
                "cost": 105.60,
                "amount": 3696.00,
            },
            {
                "item": None,
                "description": "Delivery Fee",
                "qty": None,
                "cost": None,
                "amount": 25.00,
            },
        ]
    }
    pdf_text = "BWP4 4 X 10 BLACK SCH40 35 105.60 3696.00 Delivery Fee 25"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(extracted_data, pdf_normalize_set)

    assert is_valid is True
    assert details["fields_checked"] == 7


def test_fee_item_description_still_validated_against_pdf():
    """
    GIVEN a fee line item with a hallucinated description not in the PDF
    WHEN validation runs
    THEN the description field fails PDF verification (anti-hallucination still works)
    """
    extracted_data = {
        "line_items": [
            {
                "item": "BWP4",
                "description": "4 X 10 BLACK SCH40",
                "qty": 35,
                "cost": 105.60,
                "amount": 3696.00,
            },
            {
                "item": "",
                "description": "HALLUCINATED CHARGE",
                "qty": "",
                "cost": "",
                "amount": 35.00,
            },
        ]
    }
    pdf_text = "BWP4 4 X 10 BLACK SCH40 35 105.60 3696.00 Gas Surcharge 35"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(extracted_data, pdf_normalize_set)

    assert is_valid is False
    assert any("description (item 1) - not found in PDF" in f for f in details["missing_fields"])


def test_fee_description_partial_overlap_rejected():
    """
    GIVEN a fee line item with description "Fuel Surcharge"
    AND the PDF only contains "Gas Surcharge" (shared "surcharge" token)
    WHEN validation runs
    THEN the fee description fails because ALL tokens must match for fee rows
    (not just any single shared token)
    """
    extracted_data = {
        "line_items": [
            {
                "item": "BWP4",
                "description": "4 X 10 BLACK SCH40",
                "qty": 35,
                "cost": 105.60,
                "amount": 3696.00,
            },
            {
                "item": "",
                "description": "Fuel Surcharge",
                "qty": "",
                "cost": "",
                "amount": 35.00,
            },
        ]
    }
    pdf_text = "BWP4 4 X 10 BLACK SCH40 35 105.60 3696.00 Gas Surcharge 35"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(extracted_data, pdf_normalize_set)

    assert is_valid is False
    assert any("description (item 1) - not found in PDF" in f for f in details["missing_fields"])


@pytest.mark.parametrize(
    "extracted_date,pdf_date,expected_valid,_description",
    [
        pytest.param(
            "05/19/2022",
            "5/19/22",
            True,
            "zero-padded month + full year matches short PDF date",
            id="bruce_supply_date_format",
        ),
        pytest.param(
            "5/19/2022",
            "5/19/22",
            True,
            "full year matches 2-digit year in PDF",
            id="full_year_only",
        ),
        pytest.param(
            "05/19/22",
            "5/19/22",
            True,
            "zero-padded month matches non-padded in PDF",
            id="zero_padded_month_only",
        ),
        pytest.param(
            "5/19/22",
            "5/19/22",
            True,
            "exact match passes",
            id="exact_date_match",
        ),
        pytest.param(
            "12/25/2022",
            "5/19/22",
            False,
            "completely different date fails",
            id="wrong_date_fails",
        ),
    ],
)
def test_header_date_variant_matching(extracted_date, pdf_date, expected_valid, _description):
    """
    BUG: Header validation fails for date when model zero-pads month and/or
    expands 2-digit year to 4-digit. Bruce Supply PDFs use "5/19/22" but
    the model extracts "05/19/2022".

    GIVEN extracted header with a date value
    AND a PDF containing the date in a different format
    WHEN validate_header_data runs
    THEN the date field matches via variant normalization
    """
    extracted_data = {"date": extracted_date}
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_date))

    is_valid, details = validate_header_data(extracted_data, pdf_normalize_set)

    assert is_valid == expected_valid
    if expected_valid:
        assert "date - not found in PDF" not in details["missing_fields"]
    else:
        assert "date - not found in PDF" in details["missing_fields"]


# ---------------------------------------------------------------------------
# Freight "0.00" when PDF has no value (First found in Bruce Supply)
# ---------------------------------------------------------------------------


def test_bug_freight_zero_when_pdf_has_no_value():
    """
    BUG: freight validation fails when the PDF shows a "FREIGHT" column header
    but no dollar amount. The model infers "0.00" which normalizes to token "0",
    but "0" doesn't appear in the PDF token set.

    This affects 39/49 recent Bruce Supply extractions.

    GIVEN PDF shows "FREIGHT" as a column label with no dollar amount
    AND model extracts freight as "0.00"
    WHEN header validation runs
    THEN freight fails the hallucination check (token "0" not in PDF)
    """
    extracted_data = {
        "date": "2/03/22",
        "ref_no": "8771114",
        "freight": "0.00",
        "tax": "179.57",
        "total": "2,202.94",
    }
    # Realistic Bruce Supply PDF text: FREIGHT amount shows up as '.00'
    pdf_text = """
    PAGE NO.
    INVOICE NO.
    1
    8771114
    2/03/22
    TAX 8.875
    FREIGHT
    OTH CHG
    TOTAL DUE
    2,023.37
    179.57
    .00
    2,202.94
    """
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_header_data(extracted_data, pdf_normalize_set)

    assert is_valid is True
    assert "freight - not found in PDF" not in details["missing_fields"]


# ---------------------------------------------------------------------------
# Bruce Supply end-to-end scenario (header + line items combined)
# ---------------------------------------------------------------------------


def test_bruce_supply_invoice_header_passes_with_date_variants():
    """
    GIVEN a realistic Bruce Supply invoice header
    AND the PDF uses short date format and has no explicit freight value
    WHEN validate_header_data runs
    THEN date passes via variant matching (only freight may fail)
    """
    extracted_data = {
        "date": "03/14/2022",
        "ref_no": "8812345",
        "po_no": "1099",
        "tax": "45.50",
        "total": "550.00",
        "sub_total": "504.50",
    }
    pdf_text = "3/14/22 8812345 1099 45.50 550 504.5"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_header_data(extracted_data, pdf_normalize_set)

    assert is_valid is True
    assert "date - not found in PDF" not in details["missing_fields"]
    assert details["fields_checked"] == 6
    assert details["fields_passed"] == 6


def test_bruce_supply_mixed_product_and_fee_line_items():
    """
    GIVEN a Bruce Supply invoice with product lines and a Gas Surcharge fee
    WHEN validate_line_items_data runs
    THEN product items check all 5 fields, fee item checks only description + amount
    AND the Gas Surcharge does not drag down the validation score
    """
    extracted_data = {
        "line_items": [
            {
                "item": "CTD3410L",
                "description": "LG 3/4 X 10 L TUBING DOM LG",
                "qty": "3",
                "cost": "92.600",
                "amount": "95.06",
            },
            {
                "item": "CTD110L",
                "description": "LG 1 X 10 L TUBING DOM LG",
                "qty": "5",
                "cost": "132.200",
                "amount": "226.19",
            },
            {
                "item": "",
                "description": "Gas Surcharge",
                "qty": "",
                "cost": "",
                "amount": "5.00",
            },
        ]
    }
    pdf_text = """
    CTD3410L LG 3/4 X 10 L TUBING DOM LG 3 92.600 95.06
    CTD110L LG 1 X 10 L TUBING DOM LG 5 132.200 226.19
    Gas Surcharge 5
    """
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is True
    assert len(details["missing_fields"]) == 0
    # 2 product items * 5 fields + 1 fee item * 2 fields = 12
    assert details["fields_checked"] == 12
    assert details["fields_passed"] == 12

def test_bruce_supply_mixed_product_and_fee_line_items_alternative():
    """
    GIVEN a Bruce Supply invoice with product lines and a Gas Surcharge fee
    WHEN validate_line_items_data runs
    THEN product items check all 5 fields, fee item checks only description + amount
    AND the Gas Surcharge does not drag down the validation score

    Note: The difference between this test and `test_bruce_supply_mixed_product_and_fee_line_items`
    is that this one has the 'item' and 'description' as 'Gas Surcharge'
    """
    extracted_data = {
        "line_items": [
            {
                "item": "CTD3410L",
                "description": "LG 3/4 X 10 L TUBING DOM LG",
                "qty": "3",
                "cost": "92.600",
                "amount": "95.06",
            },
            {
                "item": "CTD110L",
                "description": "LG 1 X 10 L TUBING DOM LG",
                "qty": "5",
                "cost": "132.200",
                "amount": "226.19",
            },
            {
                "item": "Gas Surcharge",
                "description": "Gas Surcharge",
                "qty": "",
                "cost": "",
                "amount": "5.00",
            },
        ]
    }
    pdf_text = """
    CTD3410L LG 3/4 X 10 L TUBING DOM LG 3 92.600 95.06
    CTD110L LG 1 X 10 L TUBING DOM LG 5 132.200 226.19
    Gas Surcharge 5
    """
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is True
    assert len(details["missing_fields"]) == 0
    # 2 product items * 5 fields + 1 fee item * 2 fields = 12
    assert details["fields_checked"] == 12
    assert details["fields_passed"] == 12


# ---------------------------------------------------------------------------
# po_no slash-separated compound values (First found in AF Supply)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pdf_text",
    [
        pytest.param("02/08/2022 123456 3992482 8001126807 500.00"),
        pytest.param("02/08/2022 123456 3992482 /8001126807 500.00"),
        pytest.param("02/08/2022 123456 3992482/ 8001126807 500.00"),
    ],
)
def test_header_po_no_slash_separated_matches_pdf(pdf_text):
    """AF Supply PO numbers combine job + SAP order (e.g. '3992482/8001126807').

    The PDF renders these on separate lines so the tokenizer sees two
    independent tokens. The model joins them with '/'. Validation must
    split on '/' and verify each sub-part exists in the PDF token set.

    Real example: MPIPLUMBINVOICES.pdf (@afsupply.com, 2022-02)
    had 5 invoices blocked at validation_score=94.567 (threshold 95)
    solely because of this po_no mismatch.
    """
    extracted_data = {
        "date": "02/08/2022",
        "ref_no": "123456",
        "po_no": "3992482/8001126807",
        "total": "500.00",
    }
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_header_data(extracted_data, pdf_normalize_set)

    assert is_valid is True
    assert "po_no - not found in PDF" not in details["missing_fields"]


def test_header_po_no_slash_separated_partial_miss():
    """po_no slash fallback must require ALL sub-parts to exist in PDF.

    If only one side of the slash exists, the other may be hallucinated.
    Validation should reject.
    """
    extracted_data = {
        "date": "02/08/2022",
        "ref_no": "123456",
        "po_no": "3992482/9999999999",
        "total": "500.00",
    }
    # PDF has 3992482 but NOT 9999999999
    pdf_text = "02/08/2022 123456 3992482 8001126807 500.00"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_header_data(extracted_data, pdf_normalize_set)

    assert is_valid is False
    assert "po_no - not found in PDF" in details["missing_fields"]


# ---------------------------------------------------------------------------
# Plumbing Exchange: item field exempt from validation
# ---------------------------------------------------------------------------


def test_plumbing_exchange_item_not_required():
    """
    GIVEN a Plumbing Exchange invoice where item values are descriptions (not product codes)
    AND item values cannot be found in the PDF token set
    WHEN validation runs
    THEN validation passes because item is not a required field for PE
    AND fields_checked reflects 4 fields per product item (no item field)
    """
    extracted_data = {
        "vendor": "Plumbing Exchange",
        "line_items": [
            {
                "item": "1-1/2 NH 1/8 BEND",
                "description": "1-1/2 NH 1/8 BEND",
                "qty": "20",
                "cost": "4.08",
                "amount": "81.60",
            },
            {
                "item": "2 NH 1/8 BEND",
                "description": "2 NH 1/8 BEND",
                "qty": "50",
                "cost": "2.05",
                "amount": "102.50",
            },
        ],
    }
    pdf_text = """
    1-1/2 NH 1/8 BEND 20 4.08 81.60
    2 NH 1/8 BEND 50 2.05 102.50
    """
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is True
    assert len(details["missing_fields"]) == 0
    # 2 product items * 4 fields (description, qty, cost, amount) = 8
    assert details["fields_checked"] == 8
    assert details["fields_passed"] == 8


def test_plumbing_exchange_still_validates_other_fields():
    """
    GIVEN a Plumbing Exchange invoice with a hallucinated description
    WHEN validation runs
    THEN description still fails PDF check (only item is exempt)
    """
    extracted_data = {
        "vendor": "Plumbing Exchange",
        "line_items": [
            {
                "item": "FAKE ITEM",
                "description": "HALLUCINATED DESCRIPTION",
                "qty": "20",
                "cost": "4.08",
                "amount": "81.60",
            },
        ],
    }
    pdf_text = "1-1/2 NH 1/8 BEND 20 4.08 81.60"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is False
    assert any("description (item 0) - not found in PDF" in f for f in details["missing_fields"])
    # item should NOT appear in missing_fields (not checked for PE)
    assert not any("item (item" in f for f in details["missing_fields"])


def test_non_pe_vendor_still_requires_item():
    """
    GIVEN a non-PE invoice where item fails PDF check
    WHEN validation runs
    THEN item field still fails (PE exemption does not apply)
    """
    extracted_data = {
        "vendor": "Bruce Supply",
        "line_items": [
            {
                "item": "WRONG_CODE",
                "description": "4 X 10 BLACK SCH40",
                "qty": 35,
                "cost": 105.60,
                "amount": 3696.00,
            },
        ],
    }
    pdf_text = "BWP4 4 X 10 BLACK SCH40 35 105.60 3696.00"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is False
    assert any("item (item 0) - not found in PDF" in f for f in details["missing_fields"])


def test_plumbing_exchange_has_product_items_without_item_code():
    """
    GIVEN a Plumbing Exchange invoice where item field is empty
    WHEN validation runs
    THEN has_product_items check passes (PE doesn't need item codes)
    AND the empty item field is not flagged as missing
    """
    extracted_data = {
        "vendor": "Plumbing Exchange",
        "line_items": [
            {
                "item": "",
                "description": "2 NH 1/8 BEND",
                "qty": "50",
                "cost": "2.05",
                "amount": "102.50",
            },
        ],
    }
    pdf_text = "2 NH 1/8 BEND 50 2.05 102.50"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is True
    assert "product_line_items" not in details["missing_fields"]


# ---------------------------------------------------------------------------
# Plumbing Exchange: negative values on credit/return invoices
# ---------------------------------------------------------------------------


def test_pe_credit_invoice_negative_qty_matches_pdf():
    """
    PE credit/return invoices have negative quantities and amounts (e.g., qty="-16",
    amount="-916.80") but the PDF shows positive numbers ("16", "916.80").

    GIVEN a PE credit invoice with negative qty and amount
    AND the PDF contains the positive equivalents
    WHEN validation runs
    THEN qty and amount pass (absolute value matches PDF token)
    """
    extracted_data = {
        "line_items": [
            {
                "item": "",
                "description": "1-1/2 NH 1/8 BEND",
                "qty": "-16",
                "cost": "4.08",
                "amount": "-65.28",
            },
        ],
    }
    pdf_text = "1-1/2 NH 1/8 BEND 16- 4.08 65.28-"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is True
    assert len(details["missing_fields"]) == 0
    # 4 fields per PE config: description, qty, cost, amount
    assert details["fields_checked"] == 4
    assert details["fields_passed"] == 4


@pytest.mark.parametrize(
    "extracted_data,pdf_text",
    [
        pytest.param({
            "date": "04/15/2021",
            "ref_no": "66775",
            "po_no": "Return",
            "sub_total": "-997.95",
            "tax": "-88.57",
            "total": "-1086.52",
            },
            """
            04/15/2021 66775 Return
            997.95 88.57 1086.52
            """
        ),
        pytest.param({
            "tax": "-1.24",
            "bill": "MPI Plumbing, Corp 670 Myrtle Ave Brooklyn, NY 11205 718 280-9049",
            "date": "03/23/2021",
            "buyer": "",
            "po_no": "",
            "total": "-15.19",
            "ref_no": "66222",
            "vendor": "Plumbing Exchange",
            "freight": "",
            "doc_type": "INVOICE",
            "sub_total": "-13.95",
            },
            """
            66222

            Mar 23 2021

            MPI Plumbing, Corp  36-20 Steinway Street

            670 Myrtle Ave  36-20 Steinway Street

            Brooklyn, NY 11205  Astoria, NY

            718 280-9049

            13.95-
            1.24-
            15.19-

            0 13.95-

            0.00 %  0.00

            1.24-

            15.19-
            """
        ),

    ]
)
def test_pe_credit_invoice_negative_header_values(extracted_data, pdf_text):
    """
    PE credit invoices have negative sub_total, tax, and total values but the PDF
    shows positive numbers.

    GIVEN header with negative financial values
    AND the PDF contains positive equivalents
    WHEN header validation runs
    THEN all fields pass via absolute value matching
    """
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_header_data(extracted_data, pdf_normalize_set)

    assert is_valid is True
    assert len(details["missing_fields"]) == 0


def test_negative_value_still_fails_when_not_in_pdf():
    """
    Negative value fallback must not blindly pass -- the absolute value must
    actually exist in the PDF token set.
    """
    extracted_data = {
        "vendor": "Plumbing Exchange",
        "line_items": [
            {
                "item": "",
                "description": "1-1/2 NH 1/8 BEND",
                "qty": "-99",
                "cost": "4.08",
                "amount": "-999.99",
            },
        ],
    }
    pdf_text = "1-1/2 NH 1/8 BEND 16 4.08 65.28"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is False
    assert any("qty (item 0) - not found in PDF" in f for f in details["missing_fields"])
    assert any("amount (item 0) - not found in PDF" in f for f in details["missing_fields"])


def test_pe_date_passes():
    """
    GIVEN a PE invoice where the date is in format: MMM d yyyy
    WHEN header validation runs
    THEN date passes because the extracted data is part of a date variant
    """
    extracted_data = {
        "date": "04/15/2021",
        "ref_no": "66775",
        "sub_total": "997.95",
        "tax": "88.57",
        "total": "1086.52",
    }
    # PDF text has the date in a different format than what was extracted
    pdf_text = """
        66775
        Apr 15 2021
        997.95
        88.57
        1086.52
    """
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_header_data(extracted_data, pdf_normalize_set)

    assert is_valid is True
    assert "date - not found in PDF" not in details["missing_fields"]
    assert details["fields_checked"] == len(extracted_data.keys())
    assert details["fields_passed"] == len(extracted_data.keys())


def test_pe_product_line_items_detected_without_item_code():
    """
    PE invoices have no item codes. A product row has qty + cost + amount,
    even when item is empty.

    GIVEN a PE invoice with empty item but populated qty/cost/amount
    WHEN the product_line_items check runs
    THEN it detects product items (PE doesn't need item codes)
    """
    extracted_data = {
        "vendor": "Plumbing Exchange",
        "line_items": [
            {
                "item": "",
                "description": "4 NH P TRAP W/1/2\" TAP",
                "qty": "1",
                "cost": "44.64",
                "amount": "44.64",
            },
        ],
    }
    pdf_text = '4 NH P TRAP W/1/2" TAP 1 44.64'
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is True
    assert "product_line_items" not in details["missing_fields"]


@pytest.mark.xfail(reason="Bug: sub_total fails validation when not explicitly printed in PDF - fix pending")
def test_bug_sub_total_fails_when_not_printed_in_pdf():
    """
    BUG: sub_total validation fails when the value is calculated but not printed in PDF.

    GIVEN PDF shows line item amounts and Balance Due
    AND PDF does NOT show an explicit sub_total line
    AND model calculates sub_total from line items
    WHEN header validation runs
    THEN validation fails because calculated sub_total is not found in PDF text

    This bug affects 95% of BMW Plumbing validation_failed records.
    The sub_total field is calculated by the model but the invoice PDF
    only shows individual amounts and the final "Balance Due" - no sub_total.
    """
    extracted_data = {
        "date": "8/7/2020",
        "ref_no": "198872",
        "sub_total": "382.43",  # Model calculated this from line items
        "tax": "33.94",
        "line_items": [
            {"item": "CT3412", "description": "3/4 X 1/2 CCC TEE", "qty": 3, "cost": 0.91, "amount": 2.73},
            {"item": "006-ST4", "description": "3/4 IPS BRZ CIRCULATOR", "qty": 2, "cost": 185.68, "amount": 371.36},
            {"item": "CM1234", "description": "1/2 X 3/4 CM ADAPTER", "qty": 6, "cost": 1.39, "amount": 8.34},
        ],
    }

    # PDF shows amounts per line but NOT the calculated sub_total
    # Only shows "Balance Due" which is sub_total + tax
    pdf_text = """
    Invoice | Date | 8/7/2020 | Invoice # | 198872 |
    CT3412 3/4 X 1/2 CCC TEE 3 0.91 2.73T |
    006-ST4 3/4 IPS BRZ CIRCULATOR 2 185.68 371.36T |
    CM1234 1/2 X 3/4 CM ADAPTER 6 1.39 8.34T |
    Sales Tax (8.875%) | 33.94 |
    Balance Due | $416.37 |
    """
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_header_data(extracted_data, pdf_normalize_set)

    # After fix: sub_total should either:
    # 1. Be skipped in validation (if it's a calculated field), OR
    # 2. Be validated via computation (sum of amounts)
    assert is_valid is True
    assert "sub_total - not found in PDF" not in details["missing_fields"]


def test_pe_credit_trailing_minus_with_trailing_zero():
    """
    GIVEN a PDF with credit amounts ending in zero (e.g., -916.80)
    WHEN the the data validation runs
    THEN the validation must match trailing-minus PDF notation (916.80-) despite normalization
    (-916.80 -> -916.8 -> 916.8 != 916.80-)
    """
    extracted_data = {
        "vendor": "Plumbing Exchange",
        "line_items": [
            {
                "description": "EZS-50L TEE",
                "qty": "-16",
                "cost": "57.30",
                "amount": "-916.80",
            },
        ],
    }
    pdf_text = "EZS-50L TEE 16- 57.30 916.80-"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is True
    assert len(details["missing_fields"]) == 0


def test_item_ocr_confusion_I_vs_1():
    """
    GIVEN a PDF containing item code "FI78" (letter I)
    WHEN the model extracts "F178" (digit 1) due to OCR confusion
    THEN validation correctly flags the item as missing (fuzzy corrector handles the fix)
    """
    extracted_data = {
        "line_items": [
            {
                "item": "F178",
                "description": "7/8 ID SELF SEAL INS",
                "qty": "17",
                "cost": "2.534",
                "amount": "43.08",
            },
        ],
    }
    pdf_text = "FI78 7/8 ID SELF SEAL INS 17 2.534 43.08"
    pdf_normalize_set = set(normalize_text_to_tokens(pdf_text))

    is_valid, details = validate_line_items_data(
        extracted_data, pdf_normalize_set, raw_pdf_text=pdf_text
    )

    assert is_valid is False
    assert any("item (item 0)" in f for f in details["missing_fields"])
