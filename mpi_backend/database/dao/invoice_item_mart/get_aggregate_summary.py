"""
Aggregate invoice line items by sheet + MPI item code for Data Review export.

SQL structure mirrors get_by_ids (same mart join, void filter, overrides, deleted rows).
Filtered exports reuse build_base_filtered_query (same scope as apply_filters / export-all).
"""

import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from mpi_backend.database.schemas.Filters import FilterRequest

from .utils import check_mart_table_exists, OVERRIDEABLE_COALESCE_EXPRESSIONS, build_base_filtered_query, _merge_excluded_fragment

logger = logging.getLogger(__name__)

# Intentional subset of OVERRIDEABLE_COALESCE_EXPRESSIONS.
# Only columns that are meaningful to aggregate are included.
# Excluded: date, vendor, cost, unit_cost, mpi_category -- these are per-line
# values that do not aggregate meaningfully across invoice items.
_AGGREGATE_EFFECTIVE_KEYS = (
    "sheet_name",
    "mpi_item",
    "mpi_description",
    "qty",
    "amount",
)

# Single mpi_bucket for all unmapped mpi_item on a sheet.
AGGREGATE_UNMAPPED_BUCKET_LABEL = "No Match"


def _sql_mpi_bucket_case(mpi_item_expr: str) -> str:
    """
    Map effective mpi_item into the aggregate bucket key.

    Aligns with Data Review "unmapped" semantics: empty mpi_item, No Match (any casing),
    "No Match / …" variants, and temporary UIDI codes all roll into one bucket per sheet.

    NOTE: mpi_item_expr is interpolated directly into SQL.
    Must be a trusted column reference (e.g. 'mpi_item', 'fi.mpi_item').
    Never pass user-controlled input here.
    """
    lab = AGGREGATE_UNMAPPED_BUCKET_LABEL.replace("'", "''")
    e = mpi_item_expr
    return f"""CASE
                        WHEN {e} IS NULL
                             OR TRIM({e}) = ''
                             OR LOWER(TRIM({e})) = 'no match'
                             OR LOWER(TRIM({e})) LIKE 'no match /%'
                             OR TRIM({e}) ILIKE 'uidi%'
                        THEN '{lab}'
                        ELSE TRIM({e})
                    END"""


def _effective_select_sql() -> str:
    """SELECT list for the effective CTE (invoice_items_id + shared override expressions)."""
    parts = ["invoice_items_id"] + [
        OVERRIDEABLE_COALESCE_EXPRESSIONS[k] for k in _AGGREGATE_EFFECTIVE_KEYS
    ]
    return ",\n                    ".join(parts)


def _aggregate_select_from_bucketed() -> str:
    """Final SELECT + GROUP BY; mpi_bucket is already the display MPI code or No Match for unmapped."""
    lab = AGGREGATE_UNMAPPED_BUCKET_LABEL.replace("'", "''")
    return f"""
            SELECT
                sheet_name AS group_name,
                mpi_bucket AS mpi_item_label,
                CASE
                    WHEN mpi_bucket = '{lab}'
                    THEN '{lab}'
                    ELSE MIN(mpi_description)
                END AS mpi_description,
                SUM(qty) AS subtotal_qty,
                SUM(amount) AS total_amount,
                ROUND(SUM(amount) / NULLIF(SUM(qty), 0), 2) AS ppp
            FROM bucketed
            GROUP BY sheet_name, mpi_bucket
            ORDER BY sheet_name NULLS LAST, mpi_bucket
    """


def get_aggregate_summary(db: Session, ids: List[str]) -> Optional[List[Dict[str, Any]]]:
    """
    Return one row per (sheet_name, MPI item bucket): summed qty/amount and PPP.

    Unmapped lines (empty mpi_item, No Match / UIDI-style codes — same idea as Data Review
    unmapped filters) merge into one row per sheet; MPI and MPI Description show "No Match".
    Subtotal QTY is the sum of quantities for those lines (expected non-zero when lines exist).

    Returns:
        List of dicts with keys: group_name, mpi_item_label, mpi_description, subtotal_qty,
        ppp, total_amount; or None if mart is unavailable or the query fails.
    """
    if not ids:
        return []

    if not check_mart_table_exists(db):
        logger.info("mart__invoice_items not found for aggregate export")
        return None

    start_time = time.time()
    try:
        # raw_data matches get_by_ids; effective columns are built from OVERRIDEABLE_COALESCE_EXPRESSIONS.
        # NUMERIC[] (not BIGINT[]) -- mart invoice_items_id is a 64-bit hash and 19-digit values
        # overflow bigint (max 9.22e18). NUMERIC[] handles the full range.
        sql_query = f"""
            WITH raw_data AS (
                SELECT
                    mart.*,
                    mart.invoice_items_id AS id,
                    o.overrides AS _override_json,
                    CASE WHEN o.record_id IS NOT NULL THEN TRUE ELSE FALSE END AS is_overridden,
                    mart.rerated_cost AS current_price,
                    mart.rerated_qty AS current_qty,
                    mart.qty AS original_current_qty
                FROM analytics.mart__invoice_items mart
                INNER JOIN (
                    SELECT DISTINCT UNNEST(CAST(:id_array AS NUMERIC[])) AS id
                ) AS temp_ids
                    ON mart.invoice_items_id = temp_ids.id
                LEFT JOIN public.user_overrides o
                    ON mart.invoice_items_id::text = o.record_id AND o.deleted_at IS NULL
                LEFT JOIN public.invoice_voided iv
                    ON mart.ref_no = iv.ref_no
                   AND mart.date   = iv.date
                   AND mart.vendor = iv.vendor
                WHERE iv.ref_no IS NULL
                  AND COALESCE(o.is_row_deleted, FALSE) = FALSE
            ),
            effective AS (
                SELECT
                    {_effective_select_sql()}
                FROM raw_data
            ),
            bucketed AS (
                SELECT
                    *,
                    {_sql_mpi_bucket_case('mpi_item')} AS mpi_bucket
                FROM effective
            )
            {_aggregate_select_from_bucketed().strip()}
        """

        result = db.execute(text(sql_query), {"id_array": ids})
        rows = result.fetchall()
        keys = result.keys()
        out = [dict(zip(keys, row)) for row in rows] if rows else []

        logger.info(
            "DAO get_aggregate_summary: %.3fs, %s groups from %s ids",
            time.time() - start_time,
            len(out),
            len(ids),
        )
        return out

    except Exception:
        logger.exception("get_aggregate_summary failed")
        return None




def get_aggregate_summary_filtered(
    db: Session,
    request: FilterRequest,
    excluded_rows_ids: Optional[List[str]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Aggregate all lines matching Data Review filters (effective_data / filtered_items pipeline).
    """
    if not check_mart_table_exists(db):
        return None
    start_time = time.time()
    try:
        base_cte, query_params = build_base_filtered_query(request)
    except (ValueError, TypeError, NotImplementedError) as e:
        # Narrow catch: ValueError/TypeError/NotImplementedError are known invalid-filter
        # errors from build_base_filtered_query. Other unexpected exceptions propagate to
        # the caller rather than being silently swallowed.
        logger.warning("get_aggregate_summary_filtered: invalid filter: %s", e)
        return None

    excl_sql, query_params = _merge_excluded_fragment(query_params, excluded_rows_ids)

    # Extend the same WITH clause with bucketed, then aggregate SELECT (export-all / apply_filters scope).
    sql_query = f"""
        {base_cte.strip()},
        bucketed AS (
            SELECT
                fi.invoice_items_id,
                fi.sheet_name,
                fi.mpi_item,
                fi.mpi_description,
                fi.qty,
                fi.amount,
                {_sql_mpi_bucket_case('fi.mpi_item')} AS mpi_bucket
            FROM filtered_items fi
            WHERE 1=1 {excl_sql}
        )
        {_aggregate_select_from_bucketed().strip()}
    """

    try:
        result = db.execute(text(sql_query), query_params)
        rows = result.fetchall()
        keys = result.keys()
        out = [dict(zip(keys, row)) for row in rows] if rows else []

        logger.info(
            "DAO get_aggregate_summary_filtered: %.3fs, %s groups",
            time.time() - start_time,
            len(out),
        )
        return out

    except Exception as e:
        logger.exception("get_aggregate_summary_filtered failed")
        return None
