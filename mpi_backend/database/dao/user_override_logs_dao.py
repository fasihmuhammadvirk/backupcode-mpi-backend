"""
DAO read path for user_override_logs table (append-only audit log).

Provides paginated, filterable access to override audit history.
All functions accept db: Session as first param (ADR-0001).
"""

import logging
import math
import time
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text


logger = logging.getLogger(__name__)


def get_override_logs(
    db: Session,
    record_id: Optional[str] = None,
    overridden_by: Optional[str] = None,
    action_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    size: int = 50,
    company_id: Optional[int] = None,
) -> dict:
    """
    Return paginated override audit log entries.

    Filters (all optional):
      record_id      -- exact match
      overridden_by  -- UUID string, exact match
      action_type    -- 'upsert' | 'field_revert' | 'record_revert' | 'row_delete' | 'row_restore'
      date_from      -- ISO date string, inclusive lower bound on saved_at
      date_to        -- ISO date string, inclusive upper bound on saved_at
      company_id     -- when set, restricts results to logs from users in that company

    Returns:
      {items, total, page, size, total_pages}
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if size < 1:
        raise ValueError("size must be >= 1")

    start = time.time()

    where_parts = []
    params: dict = {}

    if record_id:
        where_parts.append("ol.record_id = :record_id")
        params["record_id"] = record_id

    if overridden_by:
        where_parts.append("ol.overridden_by = :overridden_by")
        params["overridden_by"] = overridden_by

    if action_type:
        where_parts.append("ol.action_type = :action_type")
        params["action_type"] = action_type

    if date_from:
        where_parts.append("ol.saved_at >= CAST(:date_from AS date)")
        params["date_from"] = date_from

    if date_to:
        where_parts.append("ol.saved_at < (CAST(:date_to AS date) + INTERVAL '1 day')")
        params["date_to"] = date_to

    if company_id is not None:
        where_parts.append(
            "ol.overridden_by IN (SELECT id FROM public.users WHERE company_id = :company_id)"
        )
        params["company_id"] = company_id

    where_clause = " AND ".join(where_parts) if where_parts else "1=1"

    count_sql = f"SELECT COUNT(*) FROM public.user_override_logs ol WHERE {where_clause}"
    total = db.execute(text(count_sql), params).scalar() or 0

    offset = (page - 1) * size
    data_sql = f"""
        SELECT ol.id, ol.record_id, ol.old_values, ol.new_values, ol.action_type,
               ol.overridden_by::text, ol.saved_at
        FROM public.user_override_logs ol
        WHERE {where_clause}
        ORDER BY ol.saved_at DESC
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = size
    params["offset"] = offset

    result = db.execute(text(data_sql), params)
    rows = result.fetchall()
    columns = result.keys()
    items = [dict(zip(columns, row)) for row in rows]

    logger.info(
        f"get_override_logs page={page} size={size} total={total} "
        f"elapsed={time.time()-start:.3f}s"
    )

    return {
        "items": items,
        "total": int(total),
        "page": page,
        "size": size,
        "total_pages": math.ceil(total / size) if size else 1,
    }
