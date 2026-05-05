"""
Pydantic schemas for invoice data extraction.

This module defines the structure for invoice extraction results using Pydantic
models. These schemas are used by AI models (particularly Gemini) to ensure
structured JSON output with proper field types and validation.
"""
from pydantic import BaseModel, Field
from typing import List


class MiscCharge(BaseModel):
    """Schema for a miscellaneous footer charge on an invoice."""
    label: str = Field(description="The label of the charge as printed on the invoice (e.g. 'RESTOCK FEE', 'HANDLING CHARGE').")
    amount: float = Field(description="The dollar amount of the charge.")


class LineItem(BaseModel):
    """
    Schema for a single product or service entry on an invoice.
    
    Each line item represents one row in an invoice table, containing all
    relevant information about the product/service, quantities, pricing,
    and associated metadata.
    
    Attributes:
        item: Item name or product code identifier.
        description: Full description or name of the product/service.
        qty: Quantity of the item (integer).
        cost: Unit price before tax (float).
        amount: Total amount for this line item, typically qty * cost (float).
    """
    item: str = Field(description="The item or name of the product/service.")
    description: str = Field(
        description="The description or name of the product/service.")
    qty: int = Field(description="The quantity of the item.")
    outOfStock: int = Field(description="The quantity of the item that are not shipped.", default=0)
    cost: float = Field(description="The unit price before tax.")
    amount: float = Field(
        description="The total amount for this line item (quantity * unit_price).")
    
class InvoiceExtractionSchema(BaseModel):
    """
    Schema for the complete invoice extraction result.
    
    This schema represents the full output from an AI model's invoice extraction,
    containing all line items and a confidence score indicating the model's
    certainty about the extraction quality.
    
    Attributes:
        line_items: List of LineItem objects, each representing one product or
            service entry from the invoice. The list should contain all line items
            found in the invoice table.
        confidence_score: Float value between 0.0 and 1.0 (typically) representing
            the model's confidence in the accuracy of the extraction. Higher values
            indicate greater confidence.
    
    Attributes:
        line_items: List of LineItem objects, each representing one product or
            service entry from the invoice. The list should contain all line items
            found in the invoice table.
        date: Invoice date in MM/DD/YYYY format.
        ref_no: Invoice reference number.
        po_no: Purchase order number.
        customer_job: Ship-to address or customer job identifier.
        bill: Bill information.
        vendor: Name of the company that issued the invoice.
        buyer: Buyer information.
        sub_total: Sub-total amount of the invoice before tax.
        tax: Tax amount of the invoice.
        confidence_score: Float value between 0.0 and 1.0 (typically) representing
            the model's confidence in the accuracy of the extraction. Higher values
            indicate greater confidence.
    
    Note:
        This schema is used with Gemini's structured output feature to ensure
        consistent JSON format. The confidence_score helps prioritize which
        extractions may need human review.
    """
    line_items: List[LineItem] = Field(
        description="A list of all individual line items/products from the invoice table.")
    date: str = Field(
        description="The date the invoice was issued (MM/DD/YYYY format).")
    ref_no: str = Field(description="The reference number of the invoice.")
    po_no: str = Field(description="The purchase order number of the invoice.")
    customer_job: str = Field(description="The ship-to address of the invoice.")
    bill: str = Field(description="The bill of the invoice.")
    vendor: str = Field(
        description="The name of the company that issued the invoice.")
    buyer: str = Field(description="Person name from the 'Buyer' field in the invoice metadata table. Not the company from 'Sold To'/'Bill To'. Empty if not present.")
    sub_total: str = Field(description="The sub-total amount of the invoice.")
    confidence_score: float = Field(description="The confidence score of the extraction.")
    tax: str = Field(description="The tax amount of the invoice.")
    freight: str = Field(description="The freight amount of the invoice.")
    misc_charges: List[MiscCharge] = Field(
        default_factory=list,
        description="List of miscellaneous footer charges (e.g. RESTOCK FEE, HANDLING CHARGE). Empty list if none."
    )
    total: str = Field(description="The invoice total -- the final amount at the bottom of the invoice.")


class LineItemExtractionSchema(BaseModel):
    """
    Schema for extracting only line items from an invoice.
    
    This schema is used during retry attempts when only line items need to be
    re-extracted, and the header data (date, ref_no, etc.) has already been
    successfully extracted in a previous attempt.
    
    Attributes:
        line_items: List of LineItem objects, each representing one product or
            service entry from the invoice table.
    """
    line_items: List[LineItem] = Field(
        description="A list of all individual line items/products from the invoice table.")

    
