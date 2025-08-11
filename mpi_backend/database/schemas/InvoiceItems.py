from pydantic import BaseModel, Field, validator
import re
from typing import List, Optional, Dict
from datetime import date
from uuid import UUID


class InvoiceItems(BaseModel):
    id: Optional[int]
    filename: Optional[str]
    sheet_name: Optional[str]
    mpi_item: Optional[str]
    mpi_description: Optional[str]
    item: Optional[str]
    description: Optional[str]
    qty: Optional[int]
    cost: Optional[float]
    amount: Optional[str]
    date: Optional[str]
    ref_no: Optional[str]
    po_number: Optional[str]
    customer_job: Optional[str]
    bill: Optional[str]
    vendor: Optional[str]
    class_: Optional[str]  # 'class' is reserved in Python
    account: Optional[str]  # New account field for account mapping
    export_status: Optional[str]
    memo: Optional[str]
    buyer: Optional[str]
    date_added: Optional[str]
    invoice_id: Optional[UUID]
    is_active: Optional[bool]
    
    class Config:
        # Support both Pydantic v1 and v2 environments
        orm_mode = True  # v1
        from_attributes = True  # v2

    @validator('date', 'date_added', pre=True)
    def format_date(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                parsed_date = date.fromisoformat(value)
                return parsed_date.strftime("%m/%d/%Y")
            except ValueError:
                return value  # already is US format, or is invalid
        if isinstance(value, date):
            return value.strftime("%m/%d/%Y")
        return value

    @validator('buyer', pre=True)
    def normalize_buyer(cls, value):
        """
        Normalize buyer strings to collapse internal spacing within alpha and numeric segments
        while preserving segment order. Examples:
          - "PR ST GE 12 34 98" -> "PRSTGE 123498"
          - "an dr e w 3 4 7 52 6 -9 5 90" -> "andrew 3475269590"
          - "Arlem(929) 442-955" -> "Arlem 929442955"
          - "YOELY 3472102715 POD" -> "YOELY 3472102715 POD"
        """
        if value is None:
            return value
        s = str(value).strip()
        if not s:
            return s

        # Replace non-alphanumeric characters with spaces, keep letters, digits, spaces
        cleaned = re.sub(r"[^A-Za-z0-9\s]", " ", s)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        segments = []
        current = []
        current_type = None  # 'alpha' | 'digit' | 'other'

        def flush():
            nonlocal current, current_type
            if not current:
                return
            if current_type == 'alpha':
                segments.append(''.join(current))
            elif current_type == 'digit':
                segments.append(''.join(current))
            else:
                segments.append(' '.join(current))
            current = []
            current_type = None

        for tok in cleaned.split(' '):
            if not tok:
                continue
            tok_type = 'alpha' if tok.isalpha() else ('digit' if tok.isdigit() else 'other')
            if current_type is None:
                current_type = tok_type
                current.append(re.sub(r"\s+", "", tok))
                continue
            if tok_type == current_type and tok_type in ('alpha', 'digit'):
                current.append(re.sub(r"\s+", "", tok))
            else:
                flush()
                current_type = tok_type
                current.append(re.sub(r"\s+", "", tok))

        flush()
        return ' '.join(filter(None, segments))

    @validator('account', pre=True)
    def normalize_account(cls, value):
        """
        Normalize QuickBooks account strings to letter codes for responses.
        - 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased' -> 'M'
        - 'UnInvoiced JIP:Cost Of Materials:Job Equipment' -> 'E'
        Preserve 'A', 'M', 'E'. Leave others as-is.
        """
        if value is None:
            return value
        s = str(value).strip()
        if not s:
            return s
        if s in ('A', 'M', 'E'):
            return s
        low = s.lower()
        if 'job materials purchased' in low:
            return 'M'
        if 'job equipment' in low:
            return 'E'
        return s


class PaginatedInvoiceItemsResponse(BaseModel):
    items: List[InvoiceItems]
    total: int
    page: int
    size: int
    pages: int


class UpdateInvoiceItemRequest(BaseModel):
    id: int
    filename: str = None
    sheet_name: str = None
    mpi_item: str = None
    mpi_description: str = None
    item: str = None
    description: str = None
    qty: int = None
    cost: float = None
    amount: str = None
    date: str = None
    ref_no: str = None
    po_number: str = None
    customer_job: str = None
    bill: str = None
    vendor: str = None
    class_: str = None
    account: str = None  # New account field for account mapping
    memo: str = None
    buyer: str = None
    date_added: str = None
    invoice_id: str = None
    is_active: bool = None


class ToggleVisibilityRequest(BaseModel):
    ids: List[int]
    make_visible: bool = False


# New schemas for unmapped items endpoint
class UnmappedItemResponse(BaseModel):
    """Response model for individual unmapped item"""
    original_item_id: str
    original_description: Optional[str]
    cost: Optional[float]
    amount: Optional[float]  # Calculated as cost * quantity
    quantity: Optional[int]
    sheet_name: Optional[str]
    supplier: Optional[str]

    class Config:
        from_attributes = True


class UnmappedItemsFilterRequest(BaseModel):
    """Request model for filtering unmapped items"""
    item_type: str = Field(
        ..., description="Type of items: 'temporary', 'unmapped', or 'no_temporary'"
    )
    date_from: Optional[date] = Field(
        None, description="Start date filter (YYYY-MM-DD)"
    )
    date_to: Optional[date] = Field(
        None, description="End date filter (YYYY-MM-DD)"
    )
    supplier_names: Optional[List[str]] = Field(
        None, description="List of supplier names to filter by"
    )
    search: Optional[str] = Field(
        None, description="Search term for item code or description"
    )
    order_by: Optional[List[Dict[str, str]]] = Field(
        None, 
        description="Optional ordering criteria"
    )


class PaginatedUnmappedItemsResponse(BaseModel):
    """Paginated response for unmapped items"""
    items: List[UnmappedItemResponse]
    total_count: int
    page: int
    size: int
    pages: int

    class Config:
        from_attributes = True
