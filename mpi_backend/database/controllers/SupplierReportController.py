"""
Controller for supplier report generation.

Handles business logic for exporting aggregated invoice items by ref_no.
Aggregation is performed at the SQL level via DAO for optimal performance.
"""

import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException, BackgroundTasks

from mpi_backend.database.schemas.Filters import SupplierReportRequest
from mpi_backend.database.dao.supplier_report_dao import get_supplier_report_aggregated
from mpi_backend.utils.export_utils import export_items_generic

logger = logging.getLogger(__name__)


class SupplierReportController:
    """Controller for supplier report business logic."""

    def __init__(self, db: Session):
        self.db = db

    def generate_report(
        self,
        background_tasks: BackgroundTasks,
        request: SupplierReportRequest
    ):
        """
        Generate supplier report with SQL-level aggregation.

        The DAO performs GROUP BY aggregation in PostgreSQL, which is 10-100x faster
        than fetching all rows and aggregating in Python. This scales well for
        large datasets (10k+ invoice items per job/supplier).

        Args:
            background_tasks: FastAPI BackgroundTasks for async export
            request: Validated SupplierReportRequest with customer_jobs, supplier_names, all_suppliers

        Returns:
            - If < 1000 records: Presigned S3 URL string (sync)
            - If >= 1000 records: Dict with export_id, status, status_endpoint (async)

        Raises:
            HTTPException: 404 if no items found, 500 if processing fails
        """
        # Query aggregated invoice items via DAO (SQL-level GROUP BY)
        items = get_supplier_report_aggregated(
            self.db,
            request
        )

        if not items:
            jobs_str = ", ".join(f"'{j}'" for j in request.customer_jobs)
            if request.all_suppliers or not request.supplier_names:
                supplier_str = "all suppliers"
            else:
                supplier_str = ", ".join(f"'{s}'" for s in request.supplier_names)
            raise HTTPException(
                status_code=404,
                detail=f"No invoice items found for Job(s): {jobs_str} and Supplier(s): {supplier_str}"
            )

        # Build descriptive log message
        jobs_str = ", ".join(request.customer_jobs)
        if request.all_suppliers or not request.supplier_names:
            supplier_str = "all suppliers"
        else:
            supplier_str = ", ".join(request.supplier_names)

        logger.info(
            f"Supplier report: {len(items)} unique invoices for "
            f"jobs=[{jobs_str}] / suppliers=[{supplier_str}]"
        )

        # Export using generic utility (handles sync/async based on size)
        return export_items_generic(
            items=items,
            columns=['Date', 'Ref NO', 'Customer Job', 'Vendor', 'Amount'],
            background_tasks=background_tasks
        )

