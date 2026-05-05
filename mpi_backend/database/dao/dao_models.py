"""
Data models for DAO layer.

These dataclasses represent the structure of data returned by DAO functions.
"""

from dataclasses import dataclass, asdict
from typing import List, Any, Dict, Optional


@dataclass
class DaoPaginatedResult:
    """
    DAO-layer paginated result for unique column values.

    This dataclass represents the structure returned by DAO functions
    that perform paginated queries on the mart table.

    Attributes:
        data: List of unique values for the current page
        page: Current page number (1-indexed)
        limit: Number of results per page
        total_records: Total number of matching records across all pages
        total_pages: Total number of pages available
        source: Identifier of the data source (e.g., 'mart_invoice_items_optimized')
    """
    data: List[Any]
    page: int
    limit: int
    total_records: int
    total_pages: int
    source: str

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the dataclass to a dictionary for API responses.

        Returns:
            Dictionary representation with all fields
        """
        return asdict(self)


@dataclass
class DaoAggregateResult:
    """
    DAO-layer result for address + sheet_name aggregations.

    This dataclass represents the structure returned by analysis_page_dao functions
    that query the mart__address_sheet_aggregates table.

    Attributes:
        data: Optional dict of address-specific data (nested structure with categories)
        category_averages: Dict mapping sheet_name to global average per address (float)
        category_totals: Dict mapping sheet_name to grand total across all addresses (float)
        grand_total: Total amount across all addresses and all sheet_names (float)
        source: Identifier of the data source (e.g., 'mart_address_sheet_aggregates')
    """
    data: Optional[Dict[str, Any]]
    category_averages: Dict[str, float]
    category_totals: Dict[str, float]
    grand_total: float
    source: str

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the dataclass to a dictionary for API responses.

        Returns:
            Dictionary representation with all fields
        """
        return asdict(self)


@dataclass
class DaoInvoiceAggregatesResult:
    """
    DAO-layer result for invoice items aggregates (totals, averages, counts).

    This dataclass represents the structure returned by DAO functions
    that perform aggregation queries on the mart__invoice_items table.

    Attributes:
        total_qty: Sum of all quantities
        total_amount: Sum of all amounts (already Float in mart table)
        average_cost: Average cost per item
        source: Identifier of the data source (e.g., 'mart_invoice_items_aggregates')
    """
    total_qty: Optional[float]
    total_amount: Optional[float]
    average_cost: Optional[float]
    source: str

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the dataclass to a dictionary for API responses.

        Returns:
            Dictionary representation with all fields
        """
        return asdict(self)


@dataclass
class DaoFilteredItemsResult:
    """
    DAO-layer result for filtered and paginated invoice items.

    This dataclass represents the structure returned by DAO functions
    that perform filtered queries on the mart__invoice_items table.

    Attributes:
        items: List of invoice item dictionaries
        total: Total number of matching records
        page: Current page number
        size: Items per page
        source: Identifier of the data source (e.g., 'mart_invoice_items_filtered')
    """
    items: List[Dict[str, Any]]
    total: int
    page: int
    size: Optional[int] # optional since we could request all data by specifying size=None
    source: str

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the dataclass to a dictionary for API responses.

        Returns:
            Dictionary representation with all fields
        """
        return asdict(self)


@dataclass
class DaoUnmappedItemsResult:
    """
    DAO-layer result for unmapped items from analytics.mart__invoice_items_map.

    This dataclass represents the structure returned by DAO functions
    that query unmapped items with pagination.

    Attributes:
        items: List of unmapped item dictionaries
        total_count: Total number of matching records
        page: Current page number
        size: Items per page
        pages: Total number of pages
        source: Identifier of the data source (e.g., 'mart__invoice_items_map')
        aggregates: Optional dict with pre-calculated totals (total_cost, total_amount, total_qty)
    """
    items: List[Dict[str, Any]]
    total_count: int
    page: int
    size: int
    pages: int
    source: str
    aggregates: Optional[Dict[str, float]] = None  # {total_cost, total_amount, total_qty, total_times_bought}
    group_counts: Optional[Dict[str, int]] = None  # {group_key: count}

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the dataclass to a dictionary for API responses.

        Returns:
            Dictionary representation with all fields
        """
        return asdict(self)


@dataclass
class DaoMappingTypesResult:
    """
    DAO-layer result for distinct mapping types from analytics.mart__invoice_items_map.

    This dataclass represents the structure returned by DAO functions
    that query distinct mapping_type values.

    Attributes:
        mapping_types: List of distinct mapping type strings
        source: Identifier of the data source (e.g., 'mart__invoice_items_map')
    """
    mapping_types: List[str]
    source: str

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the dataclass to a dictionary for API responses.

        Returns:
            Dictionary representation with all fields
        """
        return asdict(self)
