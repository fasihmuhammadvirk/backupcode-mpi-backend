from datetime import date
from enum import Enum
from pydantic import BaseModel, model_validator, field_validator
from pydantic.v1 import validator
from typing import List, Dict, Any, Union, Optional
from uuid import UUID

class ComparisonFilter(BaseModel):
    column: str
    operator: str
    value: Union[str, int, float, date]  # supports date, int, and float

class OrderByFilter(BaseModel):
    column: str
    order: str  # "asc" for ascending or "desc" for descending

    @field_validator('order')
    @classmethod
    def validate_order(cls, v: str) -> str:
        normalized = v.lower().strip()
        if normalized not in ('asc', 'desc'):
            raise ValueError("order must be 'asc' or 'desc'")
        return normalized

class ColorFilter(BaseModel):
    """Color-based price comparison filter"""
    colors: List[str]  # ["green", "orange", "both"] - can be multiple colors
    # Color mapping: Green (>10%), Orange (4-9%), Both (>4%)

class PriceChangeType(str, Enum):
    """Type of price change to filter by"""
    ALL = "all"  # No filtering by price change direction
    INCREASE = "increase"  # Only items with percentage_increase > 0
    DECREASE = "decrease"  # Only items with percentage_increase < 0

    @classmethod
    def all_types(cls):
        """Return all enum member names"""
        return [member.value for member in cls]

class PriceChangeFilter(BaseModel):
    """Filter for price changes (increase/decrease/all)"""
    change_type: PriceChangeType = PriceChangeType.ALL
    min_percent: Optional[float] = None  # Minimum percentage change (absolute value)
    max_percent: Optional[float] = None  # Maximum percentage change (absolute value)

    @validator("change_type", pre=True, always=True)
    def validate_change_type(self, v):
        all_types = PriceChangeType.all_types()
        if v not in all_types:
            raise ValueError(f"Invalid price change type: {v}")
        return v

    @validator("min_percent", "max_percent", pre=True, always=True)
    def validate_min_percent(self, v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError("min_percent must be a numeric value")

    @classmethod
    def from_request(cls, raw: Any) -> "PriceChangeFilter":
        """
        Create and validate a PriceChangeFilter from a raw request object or dict.
        Raises ValueError when invalid so callers can handle/log and drop the filter.
        """
        if raw is None:
            raise ValueError("price_change_filter is None")
        # Accept either a dict-like or an object with attributes
        if isinstance(raw, dict):
            data = raw
        else:
            data = {
                "change_type": getattr(raw, "change_type", None),
                "min_percent": getattr(raw, "min_percent", None),
                "max_percent": getattr(raw, "max_percent", None)
            }
        return cls(**data)

class FilterRequest(BaseModel):
    filters: Dict[str, List[Any]] = {}
    comparison_filters: List[ComparisonFilter] = []
    order_by: Optional[List[OrderByFilter]] = None  # multiple ordering supported
    color_filters: Optional[ColorFilter] = None  # Add color filter support
    price_change_filter: Optional[PriceChangeFilter] = None  # Add price change filter support
    compare_all_supplier: bool = False  # Add best price comparison support
    search: Optional[str] = ""
    substring_search: bool = False
    include_voided: bool = False

class SendtoQBFilterRequest(BaseModel):
    filters: Dict[str, List[Any]] = {}
    comparison_filters: List[ComparisonFilter] = []
    order_by: Optional[List[OrderByFilter]] = None
    color_filters: Optional[ColorFilter] = None  # Add color filter support
    price_change_filter: Optional[PriceChangeFilter] = None  # Add price change filter support
    excluded_invoice_ids: List[UUID] = None
    skip_exported: bool = False

class ExportToExcelFilterRequest(BaseModel):
    filters: Dict[str, List[Any]] = {}
    comparison_filters: List[ComparisonFilter] = []
    order_by: Optional[List[OrderByFilter]] = None
    color_filters: Optional[ColorFilter] = None  # Add color filter support
    price_change_filter: Optional[PriceChangeFilter] = None  # Add price change filter support
    excluded_rows_ids: List[int] = None
    columns: Optional[List[str]] = []
    search: Optional[str] = ""
    substring_search: bool = False


class AggregateExportRequest(BaseModel):
    """
    Data Review aggregate Excel export.

    - all_filtered_rows_selected=True: export every row matching the filter payload (same scope as
      export-all). Always processed in a background job. ``ids`` is ignored.
    - all_filtered_rows_selected=False: requires non-empty ``ids``; hybrid sync vs background by count.
    """

    ids: Optional[List[int]] = None
    all_filtered_rows_selected: bool = False
    filters: Dict[str, List[Any]] = {}
    comparison_filters: List[ComparisonFilter] = []
    order_by: Optional[List[OrderByFilter]] = None
    color_filters: Optional[ColorFilter] = None
    price_change_filter: Optional[PriceChangeFilter] = None
    excluded_rows_ids: Optional[List[int]] = None
    search: Optional[str] = ""
    substring_search: bool = False

    def to_filter_request(self) -> "FilterRequest":
        """Same shape as Data Review / export-all filtering."""
        return FilterRequest(
            filters=self.filters or {},
            comparison_filters=self.comparison_filters or [],
            order_by=self.order_by,
            color_filters=self.color_filters,
            price_change_filter=self.price_change_filter,
            search=self.search or "",
            substring_search=self.substring_search,
        )

class SupplierReportRequest(FilterRequest):
    """
    Request model for supplier report export endpoint.

    Supports multiple job locations and flexible supplier selection.
    Used by POST /filter/supplier-report/export to generate consolidated
    invoice reports grouped by invoice number.
    Inherits from FilterRequest to support field wise filtering.
    """
    customer_jobs: List[str]  # Array of job locations (>= 1 required)
    supplier_names: Optional[List[str]] = None  # Array of suppliers OR null if all_suppliers=True
    all_suppliers: bool = False  # True = export all suppliers, ignore supplier_names

    @model_validator(mode='after')
    def validate_and_normalize_fields(self):
        """Validate inputs and populate filters dict."""
        
        # Ensure filters dict exists
        if self.filters is None:
            self.filters = {}

        # We handle these explicitly in the DAO with normalized search
        self.filters.pop('customer_job', None)
        self.filters.pop('vendor', None)

        # Strip whitespace from all job locations
        self.customer_jobs = [job.strip() for job in self.customer_jobs if job and job.strip()]

        # Validate at least 1 job location
        if not self.customer_jobs:
            raise ValueError("At least one customer_job is required")

        # If not all_suppliers, validate supplier_names
        if not self.all_suppliers:
            if not self.supplier_names:
                raise ValueError("supplier_names is required when all_suppliers is False")
            # Strip whitespace from supplier names
            self.supplier_names = [s.strip() for s in self.supplier_names if s and s.strip()]
            if not self.supplier_names:
                raise ValueError("At least one supplier_name is required when all_suppliers is False")
        else:
            # Clear supplier_names if all_suppliers is True (not needed)
            self.supplier_names = None

        return self