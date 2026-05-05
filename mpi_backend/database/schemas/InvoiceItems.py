from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, TypeVar, Generic, Any
from datetime import date, datetime
from uuid import UUID


class InvoiceItemBase(BaseModel):
    """Base invoice item schema with public fields

    Public fields refers to any field that doesn't need a specific role to be accessed. For example, the
    "account" column can only be accessed by "bookkeeper" and "admins"
    """
    id: Optional[str] = "0"
    filename: Optional[str]
    sheet_name: Optional[str]
    mpi_item: Optional[str]
    mpi_description: Optional[str]
    item: Optional[str]
    description: Optional[str]
    qty: Optional[float]
    cost: Optional[str]  # Changed from float to str for formatted display
    amount: Optional[str]
    date: Optional[str]
    ref_no: Optional[str]
    po_number: Optional[str]
    customer_job: Optional[str]
    bill: Optional[str]
    vendor: Optional[str]
    class_: Optional[str]  # 'class' is reserved in Python
    export_status: Optional[str]
    memo: Optional[str]
    buyer: Optional[str]
    date_added: Optional[str]
    invoice_id: Optional[UUID]
    is_active: Optional[bool] = True  # Default True for mart table (only active records)
    percentage_increase: Optional[float] = None  # Price increase percentage for color filtering
    best_price: Optional[str] = None  # Best market price for comparison
    previous_cost: Optional[str] = None  # Previous cost for comparison
    price_difference: Optional[str] = None  # Absolute price difference
    line_order: Optional[int] = None  # Line ordering for display (Tax records appear last)
    is_overridden: Optional[bool] = None
    is_voided: Optional[bool] = None
    is_price_rerated: Optional[bool] = None
    original_current_qty: Optional[float] = None
    original_cost: Optional[str] = None

    class Config:
        from_attributes = True

    @validator('id', pre=True)
    def convert_id_to_string(cls, value):
        """Serialize invoice_items_id as a string to prevent JS float precision loss.
        These are large bigints (> Number.MAX_SAFE_INTEGER) that JS rounds when parsed as number.
        """
        if value is None:
            return "0"
        return str(value)

    @validator('cost', 'amount', 'best_price', 'previous_cost', 'price_difference', 'original_cost', pre=True)
    def convert_numeric_to_string(cls, value):
        """Convert cost/amount from numeric types to string for display formatting."""
        if value is None:
            return None
        # Handle Decimal (from PostgreSQL), float, and int
        if isinstance(value, (int, float)) or hasattr(value, '__float__'):
            return str(value)
        return value

    @validator('date', pre=True)
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

    @validator('date_added', pre=True)
    def format_date_added(cls, value):
        # date_added is a timestamptz in Postgres and represents the exact instant
        # of extraction. We must preserve the timezone so clients can render it in
        # the user's local timezone. Returning a strftime'd "MM/DD/YYYY" string
        # collapses the instant to a UTC calendar day and drops the offset, which
        # causes the Data Review grid to show a day later than the Status History
        # modal for any user in a negative-offset timezone.
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return value


class InvoiceItemFull(InvoiceItemBase):
    """Full invoice item schema

    This includes the account field which can only be accessed by "admin" and "bookkeeping" roles
    """
    account: Optional[str]  # Account field for account mapping

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


class InvoiceItemStandard(InvoiceItemBase):
    """Invoice item schema without account field - for standard role"""
    pass  # Inherits all fields from Base except account


# TODO: Revise which code paths expect InvoiceItems and remove
# Backwards compatibility - existing code expecting InvoiceItems will get Full version
InvoiceItems = InvoiceItemFull


# Generic type for paginated responses
T = TypeVar('T')

class PaginatedInvoiceItemsResponse(BaseModel, Generic[T]):
    """Paginated response that works with any InvoiceItem variant"""
    items: List[T]
    total: int
    page: int
    size: int
    pages: int

# Backwards compatibility - default to Full version
PaginatedInvoiceItemsResponseFull = PaginatedInvoiceItemsResponse[InvoiceItemFull]
PaginatedInvoiceItemsResponseStandard = PaginatedInvoiceItemsResponse[InvoiceItemStandard]


class UpdateInvoiceItemRequest(BaseModel):
    id: int
    filename: str
    sheet_name: str
    mpi_item: str
    mpi_description: str
    item: str
    description: str
    qty: float
    cost: str
    amount: str
    date: str
    ref_no: str
    po_number: str
    customer_job: str
    bill: str
    vendor: str
    class_: str
    account: Optional[str] = ""  # Only account is optional with default empty string
    memo: str
    buyer: str
    date_added: str
    invoice_id: str
    is_active: Optional[bool] = True  # Only is_active is optional with default True
    
    @validator('account', pre=True)
    def handle_account_null(cls, value):
        """Convert null/None account values to empty string"""
        if value is None or value == "null" or value == "None":
            return ""
        return value
    
    @validator('is_active', pre=True)
    def handle_is_active_null(cls, value):
        """Convert null/None is_active values to True"""
        if value is None or value == "null" or value == "None":
            return True
        return value


class ToggleVisibilityRequest(BaseModel):
    ids: List[int]
    make_visible: bool = False


class UpdateInvoiceItemColumnsRequest(BaseModel):
    """
    Request to update columns of a single invoice item.
    Updates only the specified invoice item row.
    """
    # Single invoice item update
    id: int = Field(
        ...,
        description="The invoice item ID to update"
    )
    
    updates: Dict[str, Any] = Field(
        ...,
        description="Dictionary of column names and values to update"
    )

    class Config:
        schema_extra = {
            "examples": {
                "update_single_column": {
                    "summary": "Update single column for an invoice item",
                    "value": {
                        "id": 123,
                        "updates": {
                            "export_status": "Exported"
                        }
                    }
                },
                "update_multiple_columns": {
                    "summary": "Update multiple columns for an invoice item",
                    "value": {
                        "id": 123,
                        "updates": {
                            "memo": "Updated memo",
                            "export_status": "Exported",
                            "customer_job": "Project Alpha"
                        }
                    }
                }
            }
        }


# New schemas for unmapped items endpoint
class UnmappedItemResponse(BaseModel):
    """Response model for individual unmapped item"""
    original_item_id: str
    mapping_type: Optional[str]
    original_description: Optional[str]
    cost: Optional[str]  # Changed from float to str for formatted display
    amount: Optional[str]  # Changed from float to str for formatted display
    quantity: Optional[int]
    sheet_name: Optional[str]
    supplier: Optional[str]
    date: Optional[str]
    is_isolated: Optional[bool] = False
    is_price_rerated: Optional[bool] = False
    original_quantity: Optional[int]
    times_bought: Optional[int] = 0

    class Config:
        from_attributes = True

    @validator('cost', 'amount', pre=True)
    def convert_numeric_to_string(cls, value):
        """Convert numeric values to string for display formatting."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return str(value)
        return value


class UnmappedItemsFilterRequest(BaseModel):
    """Request model for filtering unmapped items"""
    item_type: str = Field(
        ...,
        description="Type of items: 'temporary', 'no_match', 'permanent', or 'all'"
    )
    date_from: Optional[str] = Field(
        None, description="Start date filter (YYYY-MM-DD)"
    )
    date_to: Optional[str] = Field(
        None, description="End date filter (YYYY-MM-DD)"
    )
    date_history: Optional[str] =  Field(
        None,
        description=(
            "Date added filter (YYYY-MM-DD). Matches COALESCE(date_added, date), "
            "i.e. the date the system first observed the item, falling back to "
            "the invoice date for legacy rows with no date_added."
        ),
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
    group_by: Optional[str] = Field(
        None,
        description="Optional column to group by for aggregate counts (supplier, status, invoice-date, sheet name)"
    )

    @validator('group_by', pre=True)
    def normalize_group_by(cls, value):
        """Normalize and validate group_by; enforce allowed keys early."""
        if value is None or str(value).strip() == "":
            return None
        v = str(value).strip().lower()
        # Alias normalization first (UI sends human labels sometimes)
        alias_map = {
            "invoice-date": "date",
            "sheet name": "sheet",
            "mapping_type": "status",
        }
        v = alias_map.get(v, v)
        # Import deferred to avoid circular imports
        from mpi_backend.database.dao.invoice_items_map.constants import GROUP_BY_MAP, ALLOWED_GROUP_BY
        if v == "none":
            return None
        if v in GROUP_BY_MAP:
            return v
        # Reject unknown values early
        raise ValueError(f"Invalid group_by value: '{v}'. Must be one of: {sorted(list(ALLOWED_GROUP_BY))}")

    @validator('item_type', pre=True)
    def normalize_item_type(cls, value):
        """Normalize item_type to lowercase for consistent comparison."""
        if value is None:
            return value
        return str(value).lower()


class UnmappedItemsAggregates(BaseModel):
    """Pre-calculated aggregates for unmapped items across ALL filtered records"""
    total_cost: float = Field(0.0, description="Sum of all costs across all filtered records")
    total_amount: float = Field(0.0, description="Sum of all amounts across all filtered records")
    total_qty: float = Field(0.0, description="Sum of all quantities across all filtered records")
    total_times_bought: int = Field(0, description="Total number of times items were bought across all filtered records")


class PaginatedUnmappedItemsResponse(BaseModel):
    """Paginated response for unmapped items"""
    items: List[UnmappedItemResponse]
    total_count: int
    page: int
    size: int
    pages: int
    aggregates: Optional[UnmappedItemsAggregates] = Field(
        None, description="Pre-calculated totals across ALL filtered records (not just this page)"
    )
    group_counts: Optional[Dict[str, int]] = Field(
        None, description="Total record counts per group when group_by is requested"
    )

    class Config:
        from_attributes = True

# Schemas for address and sheet name aggregation endpoint
class SheetCategoryAggregate(BaseModel):
    """Aggregated data for a single sheet_name category within an address"""
    sheet_name: str = Field(..., description="Sheet name category")
    total_amount: str = Field(..., description="Total amount for this category at this address")
    category_average: str = Field(..., description="Average amount for this category across all addresses")
    difference_from_average: str = Field(..., description="Difference from category average (no + for positive)")
    percentage_difference: Optional[float] = Field(None, description="Percentage difference from average")

    class Config:
        from_attributes = True


class AddressAggregate(BaseModel):
    """Aggregated data for a single address with breakdown by sheet_name categories"""
    address: str = Field(..., description="Customer job address")
    categories: Dict[str, SheetCategoryAggregate] = Field(..., description="Breakdown by sheet_name category")
    address_total: str = Field(..., description="Total amount for this address across all categories")

    class Config:
        from_attributes = True


class AggregatesByAddressResponse(BaseModel):
    """Response for aggregates by address and sheet name endpoint"""
    data: Dict[str, AddressAggregate] = Field(..., description="Aggregated data keyed by address")
    category_averages: Dict[str, str] = Field(..., description="Global averages per sheet_name category")
    grand_total: str = Field(..., description="Sum of all amounts across all addresses and categories")

    class Config:
        from_attributes = True


class AvailableDatesResponse(BaseModel):
    """Response for the /unmapped-items/available-dates endpoint.

    Returns unique invoice dates present in the dataset for the given filters,
    sorted newest → oldest. Used to populate the 'Date History' dropdown.
    """
    dates: List[str] = Field(
        ...,
        description="Unique invoice dates (dd/mm/YYYY), sorted newest → oldest"
    )
    total: int = Field(
        ...,
        description="Total number of distinct dates returned"
    )

    class Config:
        from_attributes = True
