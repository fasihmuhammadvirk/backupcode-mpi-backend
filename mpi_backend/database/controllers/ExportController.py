import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from mpi_backend.database.dao import invoice_item_mart
from mpi_backend.database.schemas.Filters import FilterRequest
from mpi_backend.utils.export_utils import (
    export_items_generic,
    AGGREGATE_EXPORT_EXCEL_COLUMNS,
)

logger = logging.getLogger(__name__)


class ExportController:

    def run_aggregate_export_for_ids(self, db: Session, ids: List[str]) -> str:
        """
        Aggregate export by explicit row selection.

        Raises:
            ValueError: No data found (empty IDs or all rows filtered out).
            RuntimeError: Mart/infrastructure failure.
        """
        if not ids:
            raise ValueError("No data found for export")
        raw = invoice_item_mart.get_aggregate_summary(db, ids)
        if raw is None:
            raise RuntimeError("Mart data is unavailable; aggregate export cannot run.")
        if not raw:
            raise ValueError("No data found for export")
        raw.sort(key=lambda r: (r.get("group_name") or "", r.get("mpi_item_label") or ""))
        return export_items_generic(raw, columns=AGGREGATE_EXPORT_EXCEL_COLUMNS)

    def run_aggregate_export_for_filtered(
        self,
        db: Session,
        request: FilterRequest,
        excluded_rows_ids: Optional[List[str]] = None,
    ) -> str:
        """
        Aggregate export for full filtered scope.
        Includes pre-flight count check.

        Raises:
            ValueError: No data found (empty filter result or all rows filtered out).
            RuntimeError: Mart/infrastructure failure.
        """
        filter_req = request
        total_matching = invoice_item_mart.count_filtered_rows_for_aggregate(db, filter_req, excluded_rows_ids)

        if total_matching is None:
            raise RuntimeError("Could not resolve filtered rows for aggregate export.")
        if total_matching == 0:
            raise ValueError("No items found matching the filters")
        raw = invoice_item_mart.get_aggregate_summary_filtered(db, request, excluded_rows_ids)
        if raw is None:
            raise RuntimeError("Mart data is unavailable; aggregate export cannot run.")
        if not raw:
            raise ValueError("No data found for export")
        raw.sort(key=lambda r: (r.get("group_name") or "", r.get("mpi_item_label") or ""))
        return export_items_generic(raw, columns=AGGREGATE_EXPORT_EXCEL_COLUMNS)
