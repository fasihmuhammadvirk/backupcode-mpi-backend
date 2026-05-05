from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date

class QuickBooksPreviewItem(BaseModel):
    """Single line item in QuickBooks preview"""
    id: Optional[str] = None
    items : List[dict] = Field(default_factory=list)  # Original item details
    invoice_id: str
    date: str  # Formatted as MM/DD/YYYY
    ref_no: str = Field(alias="ref")
    vendor: str
    account: str
    customer_job: str
    class_field: str = Field(alias="class")  # Classification
    tax: float = 0.0  # Tax amount (8.875% of amount before tax)
    amount: float  # Tax-inclusive amount (total with tax)
    memo: str = ""  # Item Description / Notes

    is_total_row: bool = False  # True for "INVOICE TOTAL" rows
    filename: Optional[str] = None  # PDF source filename
    
    class Config:
        populate_by_name = True


class QuickBooksPreviewRequest(BaseModel):
    """Request for QuickBooks preview endpoint"""
    start_date: date  # Start date from date picker
    end_date: date  # End date from date picker
    invoice_filter: str = "unprocessed"  # "unprocessed" or "all"
    
    class Config:
        json_schema_extra = {
            "example": {
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
                "invoice_filter": "unprocessed"
            }
        }


class QuickBooksExportRequest(BaseModel):
    """Request body for export endpoint"""
    items: List[QuickBooksPreviewItem]
    
    class Config:
        json_schema_extra = {
            "example": {
                "items": [
                    {
                        "id": "123",
                        "invoice_id": "uuid",
                        "date": "01/20/2025",
                        "ref": "INV-001",
                        "vendor": "Vendor Name",
                        "account": "UnInvoiced JIP:Cost Of Materials:Job Materials Purchased",
                        "customer_job": "Project/Phase",
                        "class": "A",
                        "tax": 50.00,
                        "amount": 550.00,
                        "memo": "Description",
                        "is_total_row": False
                    }
                ]
            }
        }


class QuickBooksUnprocessedDateRangeResponse(BaseModel):
    """Response for unprocessed date range endpoint"""
    oldest_date: Optional[date] = None
    latest_date: Optional[date] = None
