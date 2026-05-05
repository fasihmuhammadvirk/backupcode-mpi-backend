"""
Shared DocumentType enum used by both the keyword classifier and Gemini schema.

This is the single source of truth for document type values and descriptions.
The descriptions serve double-duty: human-readable labels for the keyword
classifier and field descriptions injected into the Gemini JSON schema.
"""

from enum import Enum


class DocumentType(str, Enum):
    INVOICE = "INVOICE"
    CREDIT = "CREDIT"
    CREDIT_MEMO = "CREDIT_MEMO"
    STATEMENT = "STATEMENT"
    BID = "BID"
    # BID_PROPOSAL = "BID_PROPOSAL"
    PACKING_SLIP = "PACKING_SLIP"
    SALE_ORDER = "SALE_ORDER"
    UNKNOWN = "UNKNOWN"

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self]

    @property
    def is_invoice_like(self) -> bool:
        """Types that should NOT be soft-deleted."""
        return self in (
            DocumentType.INVOICE,
            DocumentType.CREDIT,
            DocumentType.CREDIT_MEMO,
            DocumentType.BID,
            # DocumentType.BID_PROPOSAL,
        )

    @property
    def canonical(self) -> "DocumentType":
        """Collapse aliases (CREDIT_MEMO --> CREDIT)."""
        return DocumentType.CREDIT if self == DocumentType.CREDIT_MEMO else self

    @classmethod
    def gemini_enum(cls) -> list[str]:
        """Values list for Gemini schema DOC_TYPE_ENUM."""
        return [dt.value for dt in cls]

    @classmethod
    def gemini_description(cls) -> str:
        """Combined description string for Gemini doc_type field."""
        parts = [f"{dt.value} = {dt.description}" for dt in cls]
        return (
            "Document type for THIS specific document. "
            + " | ".join(parts)
        )


_DESCRIPTIONS = {
    DocumentType.INVOICE: "Standard invoice with line items, totals, and an invoice number",
    DocumentType.CREDIT: "Credit memo, return credit, or refund document",
    DocumentType.CREDIT_MEMO: "Credit memo, return credit, or refund document",
    DocumentType.STATEMENT: "Account statement summarizing multiple invoices, showing balances, aging, or payment history -- NOT a single invoice",
    DocumentType.BID: "Bid, proposal, quote, or estimate -- a price offer BEFORE any order is placed. Look for words like 'bid', 'proposal', 'quote', 'estimate'. The customer has NOT committed to purchase.",
    # DocumentType.BID_PROPOSAL: "Bid proposal or quote with a bid number",
    DocumentType.PACKING_SLIP: "Shipping or delivery document without prices",
    DocumentType.SALE_ORDER: "Sales order or order confirmation -- the customer HAS placed an order. Look for words like 'sales order', 'order confirmation', 'SO#'. NOT a bid or quote.",
    DocumentType.UNKNOWN: "Cannot determine document type",
}
