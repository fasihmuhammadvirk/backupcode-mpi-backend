"""
Get distinct mapping types from analytics.mart__invoice_items_map.
"""

import logging
import time
from sqlalchemy import text
from sqlalchemy.orm import Session
from mpi_backend.database.dao.dao_models import DaoMappingTypesResult

# Known mapping types that should always be present in graph stats (with 0 if missing)
EXPECTED_MAPPING_TYPES = {"permanent", "possible_match", "no_match", "temporary"}

logger = logging.getLogger(__name__)


def get_mapping_types(db: Session) -> DaoMappingTypesResult:
    """
    Query analytics.mart__invoice_items_map for distinct mapping_type values.

    Args:
        db: SQLAlchemy database session

    Returns:
        DaoMappingTypesResult with list of distinct mapping types and source identifier
    """
    logger.info("Querying distinct mapping types from mart__invoice_items_map")
    start_time = time.time()

    # TODO: This needs to be the same source as the datareview. We're splitting it between
    # _map and no "_map" for testing and validation for now
    query = """
        SELECT DISTINCT mapping_type
        FROM analytics.mart__invoice_items_map
        ORDER BY mapping_type
    """

    try:
        result = db.execute(text(query))
        rows = result.fetchall()

        # Get types from DB and merge with expected types to ensure all are present
        db_types = {row[0] for row in rows if row[0]}
        all_types = sorted(EXPECTED_MAPPING_TYPES | db_types)

        execution_time = time.time() - start_time
        logger.info(f"execution time: {execution_time:.3f}s, returned {len(all_types)} types (db: {len(db_types)}, expected: {len(EXPECTED_MAPPING_TYPES)})")

        return DaoMappingTypesResult(mapping_types=all_types, source="mart__invoice_items_map")

    except Exception as _:
        logger.exception("Error executing query for mapping types")
        raise
