"""
Prompt schemas for AI model extraction.

This module provides reusable schema components and builder functions
for constructing JSON schemas used in AI model prompts.
"""
import hashlib
import json
import warnings

from enums import SupplierName


# Version tracking
PROMPT_VERSION = "v17.0"
KNOWN_HASH = "2971e12de99d"  # Will be updated when schema changes are detected


# Document type enum values
DOC_TYPE_ENUM = ["INVOICE", "PACKING_SLIP", "CREDIT_MEMO", "SALE_ORDER", "UNKNOWN", "CREDIT", "STATEMENT", "BID"]


# Reusable field definitions
LINE_ITEM_FIELDS = {
    "item": {
        "type": "string",
        "description": "The item number or code of the product/service."
    },
    "description": {
        "type": "string",
        "description": "(Verify description often starts from line with Product/item code) The description or name of the product/service."
    },
    "qty": {
        "type": "string",
        "description": "The quantity of the item.(Take value with negative sign if value is negative)"
    },
    "outOfStock": {
        "type": "string",
        "description": "The quantity of the item that are not shipped, always positive value (quantity_ordered - quantity_shipped)."
    },
    "cost": {
        "type": "string",
        "description": "The unit price before tax."
    },
    "amount": {
        "type": "string",
        "description": "The total amount for this line item (quantity * unit_price)."
    }
}

LINE_ITEM_REQUIRED = ["item", "description", "qty", "outOfStock", "cost", "amount"]


def build_line_items_schema() -> dict:
    """Build the line_items array schema."""
    return {
        "type": "array",
        "description": "A list of all individual line items/products from the invoice table.",
        "items": {
            "type": "object",
            "properties": LINE_ITEM_FIELDS,
            "required": LINE_ITEM_REQUIRED,
            "propertyOrdering": LINE_ITEM_REQUIRED
        }
    }


def build_gemini_invoice_schema() -> dict:
    """
    Build the complete invoice extraction schema for Gemini.

    Returns a JSON schema dict with dynamic vendor enum from SupplierName.
    """
    properties = {
        "line_items": build_line_items_schema(),
        "date": {
            "type": "string",
            "description": "The date the invoice was issued (MM/DD/YYYY format)."
        },
        "ref_no": {
            "type": "string",
            "description": "The reference number of the invoice.(If a ref_no contains a hyphen (e.g., X-000), evaluate the characters preceding the hyphen as part of an alphabetic prefix and characters following it as numeric.)"
        },
        "po_no": {
            "type": "string",
            "description": "(P/O)The purchase order string of the invoice. The value may contain special characters (e.g., 'Y.Y.T', '843952-PO') NOT ANY VALUE LIKE THIS: '^Tr\s+[A-Z0-9]+/\d{3}$'. Value can be blank but NOT same as 'Ship Via'. Also known as 'Customer P/O #', 'P.O. No.', 'Customer PO #'."
        },
        "customer_job": {
            "type": "string",
            "description": "The ship-to address of the invoice.(Add one character space between two lines)"
        },
        "bill": {
            "type": "string",
            "description": "The bill of the invoice."
        },
        "vendor": {
            "type": "string",
            "description": "The name of the company that issued the invoice. Choose appropriate enum. If the vendor name is ambiguous, look for the entity at the top of the document, return 'Unknown Vendor' if you can't match to any of the enums.",
            "enum": SupplierName.values()
        },
        "doc_type": {
            "type": "string",
            "description": "Choose appropriate Type of the Document from enum,if not recognized then set UNKNOWN",
            "enum": DOC_TYPE_ENUM
        },
        "buyer": {
            "type": "string",
            "description": "The person who placed the order, found in the invoice metadata table under a column labeled 'Buyer'. This is a person's name (e.g. 'Yoely Podrigal'), NOT the company from 'Sold To' or 'Bill To'. Leave empty if no Buyer field exists."
        },
        "sub_total": {
            "type": "string",
            "description": "The sub-total amount of the invoice."
        },
        "confidence_score": {
            "type": "string",
            "description": "The confidence score of the extraction."
        },
        "tax": {
            "type": "string",
            "description": "The tax amount of the invoice."
        },
        "freight": {
            "type": "string",
            "description": "The freight amount of the invoice."
        },
        "misc_charges": {
            "type": "array",
            "description": "List of miscellaneous footer charges (e.g. RESTOCK FEE, HANDLING CHARGE). Empty list if none.",
            "items": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "The label of the charge as printed on the invoice (e.g. 'RESTOCK FEE', 'HANDLING CHARGE')."
                    },
                    "amount": {
                        "type": "string",
                        "description": "The dollar amount of the charge."
                    }
                },
                "required": ["label", "amount"],
                "propertyOrdering": ["label", "amount"]
            }
        },
        "total": {
            "type": "string",
            "description": "The invoice total -- the final amount at the bottom of the invoice."
        }
    }

    required_fields = [
        "line_items", "date", "ref_no", "po_no", "customer_job", "bill",
        "vendor", "doc_type", "buyer", "sub_total", "confidence_score", "tax", "freight",
        "misc_charges", "total"
    ]

    return {
        "type": "object",
        "properties": properties,
        "required": required_fields,
        "propertyOrdering": required_fields
    }


def build_gemini_multi_invoice_schema() -> dict:
    """Wrap existing invoice schema in an invoices array for multi-invoice PDF support."""
    single_invoice_schema = build_gemini_invoice_schema()
    return {
        "type": "object",
        "properties": {
            "invoices": {
                "type": "array",
                "description": (
                    "Array of ALL invoices found in this PDF document. "
                    "Most PDFs contain exactly 1 invoice, but some contain 2 or more. "
                    "Each element is a complete invoice with its own header fields, "
                    "line items, and financial totals."
                ),
                "items": single_invoice_schema
            }
        },
        "required": ["invoices"],
        "propertyOrdering": ["invoices"]
    }


def _compute_schema_hash(schema: dict) -> str:
    """Generate deterministic hash of schema content."""
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True).encode()
    ).hexdigest()[:12]


def get_prompt_metadata() -> dict:
    """
    Get version info to store with extractions.
    Warns if schema changed but version wasn't bumped.

    TODO: If we need to add more models, we should support them here. For now, we only need Gemini
    """
    schema = build_gemini_invoice_schema()
    current_hash = _compute_schema_hash(schema)

    if KNOWN_HASH is not None and current_hash != KNOWN_HASH:
        warnings.warn(
            f"\n[PROMPT VERSION MISMATCH]\n"
            f"Schema content changed but version not updated.\n"
            f"Current hash:  {current_hash}\n"
            f"Known hash:    {KNOWN_HASH}\n"
            "Actions: \n"
            "1) Update PROMPT_VERSION\n"
            f"2) Set KNOWN_HASH = '{current_hash}'\n"
            "3) Update PROMPT_CHANGELOG.md with the change",
            UserWarning,
            stacklevel=2
        )

    return {
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": current_hash
    }


def _remove_defaults_recursively(schema: dict) -> None:
    """
    Recursively remove default values from a JSON schema.

    This helper function walks through all levels of a JSON schema and removes
    any 'default' keys found in property definitions. This is necessary because
    Gemini's response_schema doesn't support default values.

    Args:
        schema: JSON schema dictionary to process (modified in-place)
    """
    if not isinstance(schema, dict):
        return

    # Remove default from current level
    if 'default' in schema:
        del schema['default']

    # Process properties
    if 'properties' in schema:
        for prop_schema in schema['properties'].values():
            _remove_defaults_recursively(prop_schema)

    # Process array items
    if 'items' in schema:
        _remove_defaults_recursively(schema['items'])

    # Process definitions ($defs)
    if '$defs' in schema:
        for def_schema in schema['$defs'].values():
            _remove_defaults_recursively(def_schema)

    # Process anyOf, allOf, oneOf
    for key in ['anyOf', 'allOf', 'oneOf']:
        if key in schema:
            for sub_schema in schema[key]:
                _remove_defaults_recursively(sub_schema)


def pydantic_to_gemini_schema(pydantic_schema: type) -> dict:
    """
    Convert Pydantic schema to Gemini-compatible JSON schema.

    This function takes a Pydantic model class and converts it to a JSON schema
    dictionary that can be used with Gemini's response_schema parameter. It also
    adds any Gemini-specific enhancements like enum values for vendor and doc_type.

    IMPORTANT: Removes default values from all properties because Gemini's
    response_schema doesn't support default values.

    Args:
        pydantic_schema: Pydantic model class (e.g., InvoiceExtractionSchema)

    Returns:
        dict: JSON schema dictionary compatible with Gemini's response_schema
    """
    # Convert Pydantic schema to JSON schema format
    json_schema = pydantic_schema.model_json_schema()

    # Remove all default values recursively (Gemini doesn't support them)
    _remove_defaults_recursively(json_schema)

    # Add Gemini-specific enhancements
    if 'properties' in json_schema:
        properties = json_schema['properties']

        # Add vendor enum if it exists
        if 'vendor' in properties:
            properties['vendor']['enum'] = SupplierName.values()

        # Add doc_type enum if it exists
        if 'doc_type' in properties:
            properties['doc_type']['enum'] = DOC_TYPE_ENUM

    return json_schema
