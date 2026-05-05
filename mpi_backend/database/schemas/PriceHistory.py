from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, Union
from datetime import date


class PriceHistoryRequest(BaseModel):
    # Lookup: at least one of item_number or mpi_item is required
    item_number: Optional[str] = None
    mpi_item: Optional[str] = None

    # vendor: pass "all" to skip vendor filtering
    vendor: str

    # Optional date range — from_date only is valid (open-ended to "now")
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    filter_zero_cost: bool = True
    # When True, from_date/to_date are applied to date_added (the day the system
    # first observed the item) instead of the invoice date. Used by the Mappings
    # page whose "Date History" filter is a date_added filter; other callers
    # (Price Changes, Data Review, Dashboard) keep the default invoice-date
    # semantics.
    filter_by_date_added: bool = False

    @model_validator(mode='after')
    def require_at_least_one_item_field(self) -> 'PriceHistoryRequest':
        item_number_valid = self.item_number and self.item_number.strip()
        mpi_item_valid = self.mpi_item and self.mpi_item.strip()

        if not item_number_valid and not mpi_item_valid:
            raise ValueError("At least one of 'item_number' or 'mpi_item' is required and cannot be empty.")
        return self


class PriceHistoryResponse(BaseModel):
    id: int  # invoice item id
    ref_no: str
    date: str  # we are formatting to US dates and get formatted strings back
    item_code: str
    item_description: str
    cost: float
    original_cost: float
    qty: int
    original_quantity: int
    amount: float
    invoice_id: str
    # Flag to indicate if price increased compared to previous entry
    is_price_increase: Optional[bool] = None
    memo: Optional[str] = None
    vendor: Optional[str] = None
    filename: Optional[str] = None
    is_price_rerated: bool = False
    
    @field_validator('cost','amount', 'original_cost', mode='before')
    @classmethod
    def clean_cost(cls, v: Union[str, float, int]) -> float:
        """Remove commas from cost string and convert to float"""
        if isinstance(v, str):
            # Remove commas and convert to float
            v = v.replace(',', '').strip()
        try:
            return float(v)
        except (ValueError, TypeError):
            raise ValueError(f"Cannot convert cost value '{v}' to float")
