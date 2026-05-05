"""
Schemas for Monthly Statement operations and exports.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date


class MonthlyStatementExportAllRequest(BaseModel):
    """Schema for export-all monthly statement request with filters."""
    from_date: date = Field(..., description="Start date for the date range (YYYY-MM-DD)")
    to_date: date = Field(..., description="End date for the date range (YYYY-MM-DD)")
    supplier_names: Optional[List[str]] = Field(None, description="List of supplier names. Use ['All'] for all suppliers, or provide specific supplier names")
    status: Optional[str] = Field(None, description="Invoice status filter: 'Processed', 'Failed', 'Unlisted', 'Missing System', 'Missing Statement', or 'All'")
    excluded_invoice_ids: Optional[List[str]] = Field(
        None, 
        description="List of IDs to exclude from export. Supports three types: 1) UUIDs from Invoice table, 2) Integer invoice_ids from plumbing_invoices, 3) Integer item IDs from invoice_items. The system intelligently detects and handles all types."
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "from_date": "2025-01-01",
                "to_date": "2025-01-31",
                "supplier_names": ["BMW Plumbing Supplies"],
                "status": "Processed",
                "excluded_invoice_ids": ["123", "456"]
            }
        }


class MonthlyStatementExportSelectedRequest(BaseModel):
    """Schema for export selected monthly statement invoices by IDs."""
    invoice_ids: List[str] = Field(
        ..., 
        description="List of IDs to export. Supports three types: 1) UUIDs from Invoice table (parent invoice), 2) Integer invoice_ids from plumbing_invoices, 3) Integer item IDs from invoice_items. The system intelligently detects and handles all types."
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "invoice_ids": ["bf5daa2e-6d21-49f1-a855-81203f6095fa", "123", "456"]
            }
        }

