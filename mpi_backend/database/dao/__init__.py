"""
Data Access Objects (DAO) for database operations.

DAOs provide stateless functions for database access, separating
data access logic from business logic in controllers.
"""
from mpi_backend.database.dao.get_mapping_history import get_item_history
from mpi_backend.database.dao.invoice_item_mart import (
    get_paginated_unique_values,
    get_aggregates,
    apply_filters,
)
from mpi_backend.database.dao.invoice_items_map import (
    get_unmapped_items,
    get_unmapped_items_by_ids,
    get_unmapped_items_graph_stats,
    get_unmapped_items_available_dates,
)
from mpi_backend.database.dao.supplier_report_dao import (
    get_supplier_report_aggregated,
)
from mpi_backend.database.dao.mappings_review_dao import MappingsReviewDAO
from mpi_backend.database.dao.dao_models import (
    DaoPaginatedResult,
    DaoAggregateResult,
    DaoInvoiceAggregatesResult,
    DaoFilteredItemsResult,
    DaoUnmappedItemsResult,
)

__all__ = [
    "get_paginated_unique_values",
    "get_aggregates",
    "apply_filters",
    "get_unmapped_items",
    "get_unmapped_items_by_ids",
    "get_unmapped_items_graph_stats",
    "get_unmapped_items_available_dates",
    "get_supplier_report_aggregated",
    "get_item_history",
    "MappingsReviewDAO",
    "DaoPaginatedResult",
    "DaoAggregateResult",
    "DaoInvoiceAggregatesResult",
    "DaoFilteredItemsResult",
    "DaoUnmappedItemsResult",
]
