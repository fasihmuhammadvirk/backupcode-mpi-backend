"""
DAO for querying item mapping history from analytics.mart__item_mapping_timeline.

Returns ordered history events for a single (supplier_item_ids, supplier_id),
including rows where supplier_id IS NULL for the same item code.
"""

import logging
import time
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from mpi_backend.database.schemas.MappingTimeline import MappingHistoryEvent

logger = logging.getLogger(__name__)


def get_item_history(
    db: Session,
    supplier_item_ids: str,
    supplier_id: Optional[int],
) -> List[MappingHistoryEvent]:
    """
    Fetch the ordered mapping history for a single (supplier_item_ids, supplier_id)
    from the pre-computed analytics.mart__item_mapping_timeline mart.

    Rows where supplier_id IS NULL for the same item code are always included
    alongside supplier-specific rows (temporary mappings often have no supplier context).

    History events are reconstructed from the mart's phase date columns and returned
    in chronological order (oldest first) matching the Status History modal:
        no_match -> temporary -> permanent

    Args:
        db:                SQLAlchemy session
        supplier_item_ids: The supplier's item code (e.g. 'SP*00011341-W')
        supplier_id:       Supplier ID. NULL-supplier rows for same item always included.

    Returns:
        Ordered list of MappingHistoryEvent instances.
    """
    logger.info(
        f"Fetching mapping history for item='{supplier_item_ids}', "
        f"supplier_id={supplier_id}"
    )
    start_time = time.time()

    query = text("""
        SELECT
            mapping_type,
            recorded_at,
            supplier_id,
            is_delete_record,
            sheet_title,
            supplier
        FROM analytics.mart__item_mapping_timeline
        WHERE supplier_item_ids = :item_id
          AND (
              :supplier_id IS NULL
              OR supplier_id = :supplier_id
              OR supplier_id IS NULL
          )
        ORDER BY recorded_at ASC
    """)

    try:
        result = db.execute(query, {
            "item_id": supplier_item_ids,
            "supplier_id": supplier_id,
        })

        events = [MappingHistoryEvent.from_dict(row._mapping) for row in result.fetchall()]

        execution_time = time.time() - start_time
        logger.info(
            f"History for '{supplier_item_ids}': {len(events)} events "
            f"in {execution_time:.3f}s"
        )

        return events

    except Exception:
        logger.exception(
            f"Error fetching mapping history for item='{supplier_item_ids}'"
        )
        raise
