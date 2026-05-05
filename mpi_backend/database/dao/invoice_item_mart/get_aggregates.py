"""
Get aggregated statistics from mart__invoice_items table.
"""

import logging
import time
import math
from sqlalchemy import text
from sqlalchemy.orm import Session
from mpi_backend.database.dao.dao_models import DaoInvoiceAggregatesResult
from mpi_backend.database.schemas.Filters import FilterRequest
from .utils import check_mart_table_exists, build_base_filtered_query


logger = logging.getLogger(__name__)


def get_aggregates(
    db: Session,
    request: FilterRequest
) -> DaoInvoiceAggregatesResult:
    """
    Query analytics.mart__invoice_items for aggregated statistics.

    Uses pre-computed numeric columns (amount is already Float) to eliminate
    expensive string validation and casting operations. Provides fast SUM/AVG
    calculations on filtered datasets.

    Args:
        db: SQLAlchemy database session
        request: FilterRequest Pydantic object with filters, comparison_filters, color_filters

    Returns:
        DaoInvoiceAggregatesResult if successful, None to fall back to invoice_items

    Raises:
        None - returns None on any error to allow fallback
    """
    logger.info(f"Getting aggregates for request: {request}")

    try:
        # Check if mart table exists
        if not check_mart_table_exists(db):
            raise NotImplementedError("mart__invoice_items not found")

        start_time = time.time()

        # Totals must always exclude voided invoices, even when the UI list
        # shows them via include_voided=True.
        agg_request = request.model_copy(update={"include_voided": False})

        try:
            base_cte, query_params = build_base_filtered_query(agg_request)
        except (ValueError, TypeError, NotImplementedError) as e:
            # Invalid filter - fall back to ORM
            logger.warning(f"Invalid filter for mart aggregates, falling back: {e}")
            raise

        # Build aggregate query using the filtered_items CTE
        # Note: amount is already Float in mart table (no validation/casting needed)
        sql_query = f"""
            {base_cte}
            SELECT
                SUM(qty) as total_qty,
                SUM(amount) as total_amount,
                AVG(cost) as average_cost
            FROM filtered_items
        """

        # Execute query
        logger.info("Executing mart aggregate query")
        result = db.execute(text(sql_query), query_params)
        row = result.fetchone()

        if not row:
            logger.warning(f"No aggregates returned from mart table. Request: {request}. Query: {sql_query}")
            raise ValueError("Expected some aggregation, got none")

        # Extract results (handle None values)
        total_qty = float(row[0]) if row[0] is not None else 0.0
        total_amount = float(row[1]) if row[1] is not None else 0.0
        average_cost = float(row[2]) if row[2] is not None else 0.0

        # Validate numeric results (handle NaN, Infinity)
        if math.isnan(total_qty) or math.isinf(total_qty):
            total_qty = 0.0
        if math.isnan(total_amount) or math.isinf(total_amount):
            total_amount = 0.0
        if math.isnan(average_cost) or math.isinf(average_cost):
            average_cost = 0.0

        execution_time = time.time() - start_time
        logger.info(f"Execution time: {execution_time:.3f}s, "
            f"qty={total_qty:.2f}, amount={total_amount:.2f}, avg_cost={average_cost:.2f}"
        )

        return DaoInvoiceAggregatesResult(
            total_qty=total_qty,
            total_amount=total_amount,
            average_cost=average_cost,
            source="mart_invoice_items_aggregates"
        )

    except Exception as e:
        logger.exception(f"Error using optimized mart table for aggregates, falling back: {e}")
        raise
