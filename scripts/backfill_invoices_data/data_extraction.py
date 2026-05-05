"""
Invoice data extraction using AI models.

This module provides functions to extract structured invoice data from files
(PDFs, images) using OpenAI and Google Gemini AI models. It includes functions
for single extraction attempts and batch extraction with validation and retry logic.
"""
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pdf_utils import normalize_pdf_text, extract_text_from_pdf
from data_validation import validate_header_data, validate_line_items_data, validate_financial_totals
from fuzzy_correction import fuzzy_correct
from ascii_normalization import normalize_extracted_data
from google import genai
from google.genai import types
from invoice_extraction_schema import InvoiceExtractionSchema, LineItemExtractionSchema
from enums import GEMINI_MODEL, OPENAI_GPT_4_1_MINI, TABULA, SupplierName, get_extraction_function
from prompt_schemas import build_gemini_invoice_schema, build_gemini_multi_invoice_schema, get_prompt_metadata, pydantic_to_gemini_schema
from db_utils import excel_to_dict
import logging
logger = logging.getLogger(__name__)

project_root = Path(__file__).parent.parent
load_dotenv(project_root / '.env')

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

EXCEL_OUTPUT_PATH = "output/excel"
os.makedirs(EXCEL_OUTPUT_PATH, exist_ok=True)

# Maximum number of retry attempts for extraction and validation
MAX_RETRIES = 2

# Gemini extraction prompts - exported for experiment tracking
GEMINI_SYSTEM_PROMPT = """You are a precise invoice data extractor. Extract ONLY information explicitly visible in the document.

## CRITICAL RULES - ANTI-HALLUCINATION
1. **NEVER invent or guess data** - If a field is not clearly visible, return an empty string ""
2. **NEVER assume values** - Do not calculate or infer values that aren't printed
3. **NEVER fill based on patterns** - Each invoice is unique; don't use patterns from other invoices
4. **When uncertain, leave empty** - An empty field is better than a wrong value

## FIELD EXTRACTION GUIDE

### Header Fields (Look at TOP of document):
- **vendor**: Company name/logo at the TOP of the document (the seller, NOT the buyer)
- **date**: Invoice date (look for "Date:", "Invoice Date:", or date near invoice number)
- **ref_no**: Invoice number (look for "Invoice #:", "Invoice No:", "Ref #:")
- **po_no**: Purchase order number. It is typically alphanumeric and may include special characters or can be blank but NOT the same as 'Ship Via'. (look for labels like "P.O.:", "PO #:", "Customer P/O", "Customer PO #").
- **buyer**: The person who placed the order (look for label "Buyer" in the metadata table row that contains Customer #, Order Date, Sales Order #, Ship Via, Salesman). This is a person's name, NOT the company from "Sold To" or "Bill To" or po_no. Leave empty if no "Buyer" field exists. The buyer name might also include a phone number.
- **customer_job**: Ship-to address (look for "Ship To:", delivery address)
- **bill**: Billing address if different from ship-to

### Financial Fields (Look at BOTTOM of document):
- **sub_total**: Amount before tax (look for "Subtotal:", "Sub Total:")
- **tax**: Tax amount (look for "Tax:", "Sales Tax:", "GST:", "VAT:")
- **freight**: Shipping/freight charges (look for "Freight:", "Shipping:", "Delivery:")
- **total**: The final invoice total (look for "Total:", "Invoice Total:", "Amount Due:", "Balance Due:")
- **misc_charges**: Any additional charges in the footer area that are NOT sub_total, tax, or freight.
  Common examples: "RESTOCK FEE", "RESTOCKING FEE", "HANDLING CHARGE", "HANDLING FEE", "MISCELLANEOUS", "MISC CHARGE", "FUEL SURCHARGE", "ENVIRONMENTAL FEE".
  Extract each as {label, amount}. Return empty list [] if no miscellaneous charges exist.

### Line Items (Look in the TABLE/GRID section):

**CRITICAL: COLUMN BOUNDARY DETECTION**
Before extracting line items, FIRST identify ALL column headers in the table.
Tables often have many columns like: Line#, Qty Ordered, Qty Shipped, Qty B/O, Product#, Description, UOM, Price, Extension, etc.

**RULE: Each column's data must stay separate.**
- If you see "25 650-375-00540" and the table has separate QTY and PRODUCT columns, these are TWO values: "25" and "650-375-00540"
- Never merge data from adjacent columns into one field
- When in doubt, look at the column header directly above the value

**CRITICAL: MULTI-LINE CELL VALUES**
Table cells often contain multiple lines of text stacked vertically. Handle these correctly:
- **Wrapped text**: If a value like "B-FPPCP0012" is split across lines as "B-" and "FPPCP0012", JOIN them into one value: "B-FPPCP0012"
- **Stacked values**: If a cell has TWO distinct values stacked (e.g., "PPEXAFL12" on top, "29976" below), preserve BOTH with a newline separator: "PPEXAFL12\\n29976"
- **Row boundaries**: A new TABLE ROW starts when you see the next line number (#) or when all columns have new values - NOT at every line break

**Field mapping (find the semantically matching column):**
- **item**: Product code/SKU/Product Name column (alphanumeric codes like "GRP2D", "650-375-00540") Verify for OCR Common Alphanumeric Confusions with the provided "RAW PDF TEXT" in the User Prompt
- **description**: Product description/name column (text describing the item)
- **qty**: Quantity shipped OR quantity ordered (prefer shipped if both exist, take value with - symbol if negative)
- **outOfStock**: Back-ordered quantity OR (Qty Ordered - Qty Shipped), default 0
- **cost**: Unit price/Net price column (price per single item)
- **amount**: Extension/Total/Line Amount column (line total)

## DATA FORMATTING
- Dates: Convert to MM/DD/YYYY format
- Numbers: Remove $ and commas (e.g., "$1,234.56" → 1234.56)
- Empty fields: Use empty string "" not null

## CONFIDENCE SCORING
Set confidence_score based on document quality:
- 0.9-1.0: Clear, legible, all fields visible
- 0.7-0.9: Mostly clear, some fields hard to read
- 0.5-0.7: Poor quality, many unclear fields
- Below 0.5: Very poor quality, high uncertainty

## CRITICAL: GROUND TRUTH VALIDATION
You will be provided with RAW TEXT extracted from the PDF. Use this to validate your extraction:
1. **Every value you extract MUST appear in the raw text** (with allowed normalization for numbers/dates)
2. Before outputting a value, verify you can find it (or its normalized form) in the raw text
3. If you cannot find a value in the raw text, leave the field EMPTY - do not guess
4. Numbers may differ in formatting ($1,234.56 vs 1234.56) - this is acceptable
5. The raw text helps you understand column boundaries and multi-line values

## MULTI-INVOICE DETECTION
This PDF may contain ONE or MORE separate invoices. You MUST identify and extract ALL of them.

Signs of multiple invoices in one PDF:
- Multiple invoice headers (different "Invoice #" or "Ref #" values)
- Repeated company logos or invoice headers after one invoice's totals
- Different dates, PO numbers, or reference numbers on different pages
- A new "Invoice" heading appearing after the previous invoice's footer totals

For EACH invoice found:
- Extract complete header fields (ref_no, date, vendor, po_no, buyer, etc.)
- Extract its own line_items array
- Extract its own financial totals (sub_total, tax, freight, total)

Return ALL invoices in the "invoices" array, even if there is only one.

Return ONLY the JSON object matching the schema.

## PER-DOCUMENT TYPE CLASSIFICATION
For EACH entry in the "invoices" array, you MUST accurately classify its doc_type.
CRITICAL: A single PDF may contain DIFFERENT document types across pages.
Page 1 might be a STATEMENT while pages 2+ are INVOICES. Classify each independently.
Do NOT let the first page's document type influence your classification of subsequent pages.

## DISAMBIGUATION RULES FOR COMMONLY CONFUSED TYPES
- Documents titled "BID PROPOSAL", "QUOTE", "ESTIMATE", or "PROPOSAL" are BID, not SALE_ORDER.
- SALE_ORDER requires an explicit sales order number or order confirmation. A bid/quote is NOT a sales order.
- STATEMENT summarizes multiple invoices or account activity. A single invoice is INVOICE, not STATEMENT."""

GEMINI_USER_PROMPT_TEMPLATE = """**STEP 0: INVOICE COUNT DETECTION**
Before extracting details, scan the ENTIRE document to count separate invoices:
- Look for repeated invoice numbers (e.g., multiple "Invoice #:" occurrences with different values)
- Look for repeated company headers or logos after footer totals
- Count distinct invoices, then extract each one separately into the "invoices" array

Analyze this invoice document and extract all data following the schema.

**STEP 1: SUPPLIER IDENTIFICATION**
First, identify the supplier/vendor from the header. Based on the supplier, apply specific extraction strategies:

- **BMW Plumbing Supplies**: Look for multi-column layouts, product codes often in format XXX-XXX-XXXXX
- **Y & S Plumbing Supplies**: Watch for quantity columns, items may have both ordered and shipped quantities
- **World Wide Plumbing**: Check for backorder columns, line items may span multiple table sections
- **Flow Mark/Supreme/Pyramid Plumbing**: Standard layouts but check for merged header cells

**STEP 2: TABLE ANALYSIS**
2a. Locate the line items table (usually mid-document)
2b. Identify ALL column headers by reading across the header row
2c. Note column boundaries - text alignment can indicate column separation
2d. Check for any spanning headers or merged cells

**STEP 3: ROW-BY-ROW EXTRACTION**
For each table row:
3a. Start with the line number or sequence number (leftmost column usually)
3b. Extract values for each column, keeping them separate
3c. Map each value to the correct schema field based on semantic meaning, not position
3d. Handle wrapped text within cells (join broken words, preserve separate values)

**STEP 4: VALIDATION & CORRECTION**
4a. Verify each line item has required fields (qty, product_code, description)
4b. Check that financial calculations make sense (qty × unit_price ≈ line_total)
4c. Cross-reference extracted values with the raw PDF text below

**STEP 5: HEADER & TOTALS**
5a. Extract header fields from top of document
5b. Extract financial totals from bottom
5c. Ensure buyer/ship-to information is captured correctly

---
RAW PDF TEXT for validation:
```
{raw_pdf_text}
```"""


def extract_data(
    model_name: str,
    file_path: str,
    schema: type[InvoiceExtractionSchema | LineItemExtractionSchema],
    vendor: str = None
) -> dict | None:
    """
    Extract invoice data from a file using the specified AI model.

    This function coordinates the extraction process by routing to the appropriate
    model-specific extraction function (OpenAI, Gemini, or Tabula). It does not include
    validation or retry logic - those are handled by extract_and_validate_data().

    Args:
        model_name: Name of the AI model to use. Must be one of:
            - GEMINI_MODEL: Google Gemini 3.0 pro preview model
            - OPENAI_GPT_4_1_MINI: OpenAI GPT-4.1-mini model
            - TABULA: Tabula-based PDF extraction (requires vendor parameter)
        file_path: Path to the invoice file (image or document) to be processed.
        schema: Pydantic schema defining the expected output structure. Must be
            either InvoiceExtractionSchema (for full invoice extraction) or
            LineItemExtractionSchema (for line items only).
        vendor: Vendor name extracted by Gemini. Required for TABULA model to
            determine which supplier-specific extraction function to use.

    Returns:
        dict | None: Dictionary containing the extracted invoice data. Structure
            depends on the schema used, but typically includes:
            - line_items: List of line item dictionaries
            - confidence_score: Confidence score (float) of the extraction
            - Additional fields based on schema (date, ref_no, tax, sub_total, etc.)
            Returns None if extraction failed, invalid model name provided, API key
            is missing, or vendor is missing/unrecognized (TABULA only).

    Note:
        This function performs a single extraction attempt. For retry logic and
        validation, use extract_and_validate_data() instead.
    """
    if model_name == OPENAI_GPT_4_1_MINI:
        extracted_data = extract_data_using_openai(file_path, json.dumps(schema.model_json_schema(), indent=4))

    elif model_name == GEMINI_MODEL:
        extracted_data = extract_data_using_gemini(file_path, schema=schema)

    elif model_name == TABULA:
        if not vendor:
            logger.error("TABULA requires vendor parameter from Gemini extraction")
            return None
        output_path = os.path.join(EXCEL_OUTPUT_PATH, f"{file_path.split('/')[-1].split('.')[0]}.xlsx")
        name = SupplierName.from_vendor_name(vendor)
        if name is None:
            logger.error(f"Unrecognized vendor for TABULA: {vendor}")
            return None
        func = get_extraction_function(name)
        if func is None:
            logger.error(f"No extraction function found for vendor: {vendor}")
            return None
        func(file_path, output_path)
        dict_data = excel_to_dict(output_path, vendor)
        extracted_data = {
            "line_items": dict_data,
            "confidence_score": 1.0
        }

    else:
        logger.error(f"Invalid model name: {model_name}")
        return None

    return extracted_data



def extract_data_using_openai(file_path: str, schema: str) -> dict | None:
    """
    Extract invoice data from a file using OpenAI's GPT-4.1-mini model.

    This function uploads the file to OpenAI, sends it to the model with a
    structured schema prompt (as JSON string), and parses the JSON response to
    extract invoice line items and metadata.

    Args:
        file_path: Path to the invoice file (image or document) to be processed.
            The file will be opened in binary read mode and uploaded to OpenAI.
        schema: JSON schema string defining the expected output structure. This
            is generated from a Pydantic model's model_json_schema() method and
            passed as a formatted JSON string to guide the model's output format.

    Returns:
        dict | None: Dictionary containing the extracted invoice data. The structure
            matches the provided schema, typically including:
            - line_items: List of dictionaries, each containing item, description,
              qty, cost, amount, and other line item fields
            - Header fields: date, ref_no, po_no, customer_job, bill, vendor, buyer
            - Financial fields: sub_total, tax, freight
            - confidence_score: Confidence score (float) of the extraction
            Returns None if OPENAI_API_KEY is not set or if extraction fails.

    Raises:
        Exception: If OPENAI_API_KEY is not set, logs error and returns None.
        Exception: If file upload, API call, or JSON parsing fails, exception
            is raised to be handled by the retry logic in extract_and_validate_data().

    Note:
        Uses OpenAI's Responses API with model "gpt-4.1-mini". The response
        is expected to be JSON, and code block markers (```json) are stripped
        during parsing.
    """
    if not OPENAI_API_KEY:
        logger.exception("OPENAI_API_KEY is not set")
        return None

    with open(file_path, "rb") as file_obj:
        file = openai_client.files.create(
            file=file_obj,
            purpose="user_data"
        )
    response = openai_client.responses.create(
                model=OPENAI_GPT_4_1_MINI,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": f"Extract invoice data as structured JSON. The output schema would be like {schema}"},
                            {
                                "type": "input_file",
                                "file_id": file.id
                            }
                        ]
                    }
                ],
            )

    data = json.loads(response.output_text.strip('```json\n').strip('```'))
    return data


def extract_data_using_gemini(file_path: str, schema: type[InvoiceExtractionSchema | LineItemExtractionSchema]) -> dict | None:
    """
    Extract invoice data from a file using Google's Gemini 3.0 pro preview model.

    This function uploads a file to Gemini, uses the AI model with a structured
    JSON schema (Pydantic-based) to extract invoice information including line
    items and metadata, and returns the parsed JSON response.

    Args:
        file_path: Path to the invoice file (image or document) to be processed.
            The file will be uploaded to Gemini's file API.
        schema: Pydantic schema (InvoiceExtractionSchema or LineItemExtractionSchema)
            defining the expected output structure. Used to configure structured
            output via Gemini's response_schema parameter.

    Returns:
        dict | None: Dictionary containing the extracted invoice data parsed from JSON.
            The structure matches the provided schema:
            - For InvoiceExtractionSchema: Includes line_items, date, ref_no, po_no,
              customer_job, bill, vendor, buyer, sub_total, tax, freight, and
              confidence_score
            - For LineItemExtractionSchema: Includes only line_items
            Returns None if GEMINI_API_KEY is not set. Raises exception if JSON
            parsing fails (to be handled by retry logic).

    Raises:
        Exception: If GEMINI_API_KEY is not set, logs error and returns None.
        Exception: If file upload, API call, or JSON parsing fails, exception
            is raised to be handled by the retry logic in extract_and_validate_data().

    Note:
        Uses Gemini 3.0 pro preview model with structured output via Pydantic schema.
        The response is guaranteed to be JSON format due to response_mime_type
        and response_schema configuration. Validation and retry logic are handled
        by the extract_and_validate_data() wrapper function.
    """
    if not GEMINI_API_KEY:
        logger.exception("GEMINI_API_KEY is not set")
        return None

    uploaded_file = gemini_client.files.upload(file=file_path)
    logger.info(f"File uploaded successfully to Gemini: {uploaded_file.name}")

    # Extract raw text from PDF for ground truth validation
    raw_pdf_text = extract_text_from_pdf(file_path)
    if not raw_pdf_text:
        logger.warning(f"Could not extract raw text from PDF: {file_path}. Proceeding without ground truth validation.")
        raw_pdf_text = "(Raw text extraction failed - image-based PDF)"

    # Format user prompt with raw text for validation
    user_prompt = GEMINI_USER_PROMPT_TEMPLATE.format(raw_pdf_text=raw_pdf_text)

    # Convert Pydantic schema to JSON schema format for Gemini
    # json_schema = pydantic_to_gemini_schema(schema)

    schema = build_gemini_multi_invoice_schema()

    config = types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=schema,
                system_instruction=GEMINI_SYSTEM_PROMPT,
            )

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[user_prompt, uploaded_file],
        config=config
    )
    logger.info(f"Gemini returned: {response}")

    extracted_data = json.loads(response.text)

    # Sometimes the model doesn't return a dictionary but we want to make sure that we save its data to debug
    # later and figure out what went wrong
    if isinstance(extracted_data, dict):
        return {
            **extracted_data,
            "prompt_hash": get_prompt_metadata().get("prompt_hash", None)
        }
    else:
        return {
            "response": extracted_data,
            "prompt_hash": get_prompt_metadata().get("prompt_hash", None)
        }
  
  
def validate_and_enrich(data: dict, pdf_normalize_set, raw_pdf_text: str = None) -> dict:
    """Validate extracted data against PDF content, apply fuzzy correction, and enrich with metadata.

    Runs header and line items validation, applies fuzzy correction for
    invalid fields, and adds validation metadata (_header_valid,
    _line_items_valid, _validation_passed, _header_details,
    _line_items_details) to the data dict.

    Args:
        data: Extracted invoice data dict.
        pdf_normalize_set: Normalized PDF text set for validation.
        raw_pdf_text: Raw PDF text string for fuzzy correction.
            If None, fuzzy correction is skipped.

    Returns:
        The enriched data dict (mutated in place) with validation metadata added.
    """
    header_valid, header_details = validate_header_data(data, pdf_normalize_set)
    line_items_valid, line_items_details = validate_line_items_data(data, pdf_normalize_set, raw_pdf_text)

    if (not line_items_valid or not header_valid) and raw_pdf_text:
        corrected_data, correction_details = fuzzy_correct(
            data, line_items_details, header_details,
            raw_pdf_text, ratio_threshold=0.2
        )
        if correction_details['corrections_made'] > 0:
            logger.info(f"Applied {correction_details['corrections_made']} fuzzy corrections")
            data = corrected_data
            if not line_items_valid:
                line_items_valid, line_items_details = validate_line_items_data(data, pdf_normalize_set, raw_pdf_text)
            if not header_valid:
                header_valid, header_details = validate_header_data(data, pdf_normalize_set)
            data['_correction_details'] = correction_details

    financial_valid, financial_details = validate_financial_totals(data)

    data['_header_valid'] = header_valid
    data['_line_items_valid'] = line_items_valid
    data['_financial_valid'] = financial_valid
    data['_financial_details'] = financial_details
    all_passed = header_valid and line_items_valid and financial_valid
    data['_validation_passed'] = all_passed
    if not all_passed:
        failed = [name for name, valid in [
            ('header', header_valid),
            ('line_items', line_items_valid),
            ('financial', financial_valid),
        ] if not valid]
        data['_validation_failed_checks'] = failed
    data['_header_details'] = header_details
    data['_line_items_details'] = line_items_details

    return data


def extract_and_validate_data(models: list[str], file_path: str) -> dict | None:
    """
    Extract and validate invoice data from a file using multiple extraction models.

    This function attempts to extract invoice data using each specified model,
    validates the extracted data against PDF content, and includes only successfully
    validated extractions in the returned dictionary. If header data validates but
    line items fail, it retries extraction using LineItemExtractionSchema to
    re-extract only the line items.

    Args:
        models: List of model names to use for extraction (e.g., [GEMINI_MODEL, OPENAI_GPT_4_1_MINI, TABULA]).
            Valid model names are GEMINI_MODEL, OPENAI_GPT_4_1_MINI, TABULA (from enums module).
            Note: TABULA requires Gemini to run first to extract the vendor name.
        file_path: Path to the invoice file (image or document) to be processed.
            The file will be used for both extraction and PDF text normalization.

    Returns:
        dict | None: Dictionary mapping model names to their validated extraction results.
            Each value is a dict with structure matching InvoiceExtractionSchema:
            - line_items: List of line item dictionaries
            - confidence_score: Confidence score (float)
            - Additional header fields: date, ref_no, po_no, customer_job, bill, vendor, buyer
            - Additional financial fields: sub_total, tax, freight
            Example:
            {
                "gemini": {"line_items": [...], "confidence_score": 0.95, "date": "...", ...},
                "openai": {"line_items": [...], "confidence_score": 0.92, "date": "...", ...},
                "tabula": {"line_items": [...], "confidence_score": 1.0, ...}
            }
            Returns empty dict {} if no models successfully extract and validate data.
            Returns None if PDF normalization fails after MAX_RETRIES attempts.
            Only successfully validated extractions are included in the returned dictionary.

    Retry Logic:
        PDF normalization is retried up to MAX_RETRIES (2) times if it fails, with
        1 second delay between attempts. If PDF normalization fails after all retries,
        the function returns None.

        For each model, if the initial extraction with InvoiceExtractionSchema succeeds
        but line items fail validation while header data passes, the function retries
        extraction using LineItemExtractionSchema to re-extract only the line items.
        The retried line items are merged with the original header data and re-validated.

    Validation:
        Extracted data is validated using two separate functions:
        - validate_header_data(): Validates that header fields (date, ref_no, po_no, etc.)
          can be found in the normalized PDF text (hallucination check)
        - validate_line_items_data(): Validates that:
          - All required fields are present in each line item (item, description, qty, cost, amount)
          - Field values can be found in the normalized PDF text (hallucination check)
          - At least one product line item exists (excluding "10 Materials")

        Both validations must pass for data to be included in the results. All models,
        including TABULA, go through the same validation process.

    Note:
        This function normalizes the PDF text once per file and uses it for all
        model validations. If PDF normalization fails after retries, the function
        returns None and no extractions are attempted.

        TABULA requires Gemini to run first to extract the vendor name. If Gemini
        fails or doesn't extract a vendor, TABULA will be skipped with an error log.
    """
    extraction_start = time.perf_counter()

    logger.info("Reading PDF normalized")
    pdf_start = time.perf_counter()
    pdf_normalize_set, raw_pdf_text = normalize_pdf_text(file_path)
    logger.info(f"[TIMING] normalize_pdf_text: {time.perf_counter() - pdf_start:.2f}s")

    model_responses = {}
    gemini_vendor = None  # Will be set after Gemini extraction for TABULA

    # Ensure Gemini runs first (TABULA depends on Gemini's vendor extraction)
    ordered_models = sorted(models, key=lambda m: 0 if m == GEMINI_MODEL else 1)
    logger.info(f"Ordered models: {ordered_models}")

    for model in ordered_models:
        model_start = time.perf_counter()

        if model == GEMINI_MODEL:
            data = extract_data_using_gemini(file_path, schema=InvoiceExtractionSchema)
        # TABULA requires vendor from Gemini
        elif model == TABULA:
            if not gemini_vendor:
                logger.error("TABULA requires vendor from Gemini extraction, but Gemini failed or vendor missing")
                continue
            data = extract_data(model, file_path, schema=InvoiceExtractionSchema, vendor=gemini_vendor)
        else:
            data = extract_data(model, file_path, schema=InvoiceExtractionSchema)

        logger.info(f"[TIMING] {model}_extraction: {time.perf_counter() - model_start:.2f}s")

        if data:
            # Multi-invoice path: Gemini now returns {invoices: [{...}, ...]}
            if model == GEMINI_MODEL and isinstance(data, dict) and 'invoices' in data:
                invoices = data.get('invoices', [])
                if not invoices:
                    invoices = [data]

                validated_invoices = []
                for inv_idx, inv in enumerate(invoices):
                    # Normalize non-ASCII lookalikes before validation so the
                    # validator compares clean ASCII values against PDF text.
                    inv, _norm_report = normalize_extracted_data(
                        inv, fields=['item', 'description', 'po_no']
                    )
                    inv['_ascii_normalization_report'] = _norm_report
                    if _norm_report['fields_normalized'] > 0:
                        logger.info(
                            f"ASCII normalization [invoice {inv_idx}]: "
                            f"{_norm_report['fields_normalized']} field(s) normalized, "
                            f"{_norm_report['total_chars_replaced']} char(s) replaced — "
                            f"fields: {list(_norm_report['field_details'].keys())}"
                        )
                    else:
                        logger.info(f"ASCII normalization [invoice {inv_idx}]: no non-ASCII characters found")
                    inv = validate_and_enrich(inv, pdf_normalize_set, raw_pdf_text)
                    validated_invoices.append(inv)

                data['invoices'] = validated_invoices
                data['prompt_hash'] = data.get('prompt_hash')
                model_responses[model] = data
                logger.info(
                    f"Extracted {len(validated_invoices)} invoice(s) for {model} "
                    f"(per-invoice validation: {[inv['_validation_passed'] for inv in validated_invoices]})"
                )

                # Capture vendor from first invoice for TABULA
                if validated_invoices:
                    gemini_vendor = validated_invoices[0].get('vendor')
                continue  # Skip the single-invoice validation path below

            # Single-invoice path (non-Gemini models and edge cases)
            # Check if line items need retry before full validation
            header_valid, _ = validate_header_data(data, pdf_normalize_set)
            line_items_valid, line_items_details = validate_line_items_data(data, pdf_normalize_set, raw_pdf_text)

            # If line items failed but header passed, retry just line items to improve quality
            if not line_items_valid and header_valid:
                logger.info(f"Retrying line items, validation failed: {line_items_details}")
                if model == TABULA:
                    retry = extract_data(model, file_path, schema=LineItemExtractionSchema, vendor=gemini_vendor)
                else:
                    retry = extract_data(model, file_path, schema=LineItemExtractionSchema)
                if retry:
                    data = {**data, "line_items": retry["line_items"]}

            # Normalize non-ASCII lookalikes before validation so the
            # validator compares clean ASCII values against PDF text.
            data, _norm_report = normalize_extracted_data(
                data, fields=['item', 'description', 'po_no']
            )
            data['_ascii_normalization_report'] = _norm_report
            if _norm_report['fields_normalized'] > 0:
                logger.info(
                    f"ASCII normalization [{model}]: "
                    f"{_norm_report['fields_normalized']} field(s) normalized, "
                    f"{_norm_report['total_chars_replaced']} char(s) replaced — "
                    f"fields: {list(_norm_report['field_details'].keys())}"
                )
            else:
                logger.info(f"ASCII normalization [{model}]: no non-ASCII characters found")

            # Validate, fuzzy-correct, and enrich with metadata
            data = validate_and_enrich(data, pdf_normalize_set, raw_pdf_text)
            model_responses[model] = data
            logger.info(f"Extracted data for {model} (validation_passed={data['_validation_passed']})")

            # Capture vendor from Gemini for TABULA
            if model == GEMINI_MODEL:
                gemini_vendor = data.get('vendor')

    logger.info(f"[TIMING] extraction_total: {time.perf_counter() - extraction_start:.2f}s")
    return model_responses
