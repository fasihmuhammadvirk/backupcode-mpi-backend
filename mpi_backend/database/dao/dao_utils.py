"""
Shared utility functions for DAO layer.
"""

import logging
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def check_table_exists(db: Session, schema: str, table_name: str) -> bool:
    """
    Check if a table exists in the specified schema.

    Args:
        db: SQLAlchemy database session
        schema: Database schema name
        table_name: Table name to check

    Returns:
        True if table exists, False otherwise
    """
    try:
        check_query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = :schema
                AND table_name = :table_name
            )
        """)
        return db.execute(check_query, {"schema": schema, "table_name": table_name}).scalar()
    except Exception as e:
        logger.warning(f"Error checking table existence ({schema}.{table_name}): {e}")
        return False
