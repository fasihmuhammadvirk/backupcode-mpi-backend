"""
Data Access Object for supplier report queries.

Queries the dbt-managed mart table for aggregated invoice data.
"""

import logging
import re
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from mpi_backend.database.schemas.Filters import SupplierReportRequest
from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query

logger = logging.getLogger(__name__)


def _normalize_for_search(value: str) -> str:
    """
    Normalize a string for matching against the indexed *_normalized columns.

    Mirrors the dbt normalization: REGEXP_REPLACE(LOWER(...), '[-_\\s\\(\\)]+', ' ', 'g')
    """
    return re.sub(r'[-_\s()]+', ' ', value.lower())


def get_supplier_report_aggregated(
    db: Session,
    request: SupplierReportRequest
) -> List[Dict[str, Any]]:
    """
    Query and aggregate invoice items by ref_no using SQL-level aggregation.

    Uses `build_base_filtered_query` to apply all filters (date, fields, etc.)
    then groups by ref_no, customer_job, and vendor.

    Args:
        db: SQLAlchemy database session
        request: FilterRequest (or SupplierReportRequest) with applied filters

    Returns:
        List of dicts with keys: date, ref_no, customer_job, vendor, amount
    """
    # Normalized expressions are required: the WHERE clause below filters on
    # customer_job_normalized and vendor_search_normalized from filtered_items.
    base_cte, params = build_base_filtered_query(
        request,
        include_normalized_expressions=True
    )

    customer_jobs_normalized = [_normalize_for_search(job) for job in request.customer_jobs]
    supplier_names_normalized = [_normalize_for_search(s) for s in request.supplier_names] if request.supplier_names else None

    where_clause = "WHERE customer_job_normalized = ANY(:customer_jobs_normalized)"
    params['customer_jobs_normalized'] = customer_jobs_normalized

    if supplier_names_normalized:
        where_clause += " AND vendor_search_normalized = ANY(:supplier_names_normalized)"
        params['supplier_names_normalized'] = supplier_names_normalized

    query = text(f"""
        {base_cte},
        items_with_key AS (
            SELECT
                date,
                COALESCE(NULLIF(TRIM(ref_no), ''), 'Unknown-' || invoice_items_id::text) as ref_no_key,
                customer_job,
                vendor,
                COALESCE(amount, 0) as amount
            FROM filtered_items
            {where_clause}
        )
        SELECT
            MIN(date) as date,
            ref_no_key as ref_no,
            customer_job,
            vendor,
            SUM(amount) as amount
        FROM items_with_key
        GROUP BY ref_no_key, customer_job, vendor
        ORDER BY customer_job, vendor, ref_no_key
    """)

    result = db.execute(query, params)
    rows = result.fetchall()

    items = [
        {
            "date": row.date,
            "ref_no": row.ref_no,
            "customer_job": row.customer_job,
            "vendor": row.vendor,
            "amount": float(row.amount) if row.amount else 0.0
        }
        for row in rows
    ]

    logger.debug(f"Retrieved {len(items)} aggregated items from mart table")
    return items

