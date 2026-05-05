"""
Public API for invoice_item_mart DAO operations.

Provides stateless functions for querying the dbt-managed mart table
with pre-computed normalized columns for ultra-fast searches.
"""

from .apply_filters import apply_filters
from .get_unique_values import get_paginated_unique_values
from .get_aggregates import get_aggregates
from .get_by_ids import get_by_ids
from .get_aggregate_summary import (
    get_aggregate_summary,
    get_aggregate_summary_filtered,
)
from .utils import count_filtered_rows_for_aggregate

__all__ = [
    'apply_filters',
    'get_paginated_unique_values',
    'get_aggregates',
    'get_by_ids',
    'get_aggregate_summary',
    'get_aggregate_summary_filtered',
    'count_filtered_rows_for_aggregate',
]
