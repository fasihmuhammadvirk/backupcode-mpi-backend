"""Pydantic schemas for invoice void / restore endpoints."""

from datetime import date as date_type
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VoidByKeyRequest(BaseModel):
    """Request body for voiding an invoice by composite key.
    The ``date`` field must be in YYYY-MM-DD format to match the mart date column.
    """
    ref_no: str = Field(..., description="Invoice reference number")
    date: date_type = Field(..., description="Invoice date (YYYY-MM-DD)")
    vendor: str = Field(..., description="Vendor / supplier name")
    reason: Optional[str] = Field(None, description="Optional reason for voiding")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"ref_no": "INV-001", "date": "2025-06-15", "vendor": "Acme Supply", "reason": "Duplicate"}
            ]
        }
    }


class RestoreByKeyRequest(BaseModel):
    """Request body for restoring a voided invoice by composite key.
    The ``date`` field must be in YYYY-MM-DD format to match the mart date column.
    """
    ref_no: str = Field(..., description="Invoice reference number")
    date: date_type = Field(..., description="Invoice date (YYYY-MM-DD)")
    vendor: str = Field(..., description="Vendor / supplier name")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"ref_no": "INV-001", "date": "2025-06-15", "vendor": "Acme Supply"}
            ]
        }
    }


class InvoiceVoidResponse(BaseModel):
    ref_no: str
    date: date_type
    vendor: str
    invoice_voided_at: Optional[datetime] = None
    invoice_voided_by: Optional[str] = None
    void_reason: Optional[str] = None
