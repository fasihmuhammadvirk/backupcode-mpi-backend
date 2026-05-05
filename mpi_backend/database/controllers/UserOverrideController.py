"""Controller for user override operations."""

import logging
from typing import List, Dict, Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from mpi_backend.database.dao import user_overrides_dao

logger = logging.getLogger(__name__)

_MAX_BULK_IDS = 500


class UserOverrideController:
    """
    Handle user override business operations.

    This controller coordinates request-level intent with DAO persistence.
    """

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _parse_record_ids(record_ids_param: str) -> List[str]:
        """
        Parse a comma-separated record_ids query parameter into a validated list.

        Raises HTTPException 422 if the list is empty or exceeds the bulk limit.
        """
        ids = [rid.strip() for rid in record_ids_param.split(",") if rid.strip()]
        if not ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="record_ids must contain at least one ID.",
            )
        if len(ids) > _MAX_BULK_IDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"record_ids is limited to {_MAX_BULK_IDS} IDs per request.",
            )
        return ids

    def soft_delete_rows(self, record_ids: str, user_id: UUID) -> int:
        """
        Soft-delete one or more mart rows.
        """
        ids = self._parse_record_ids(record_ids)
        try:
            return user_overrides_dao.soft_delete_rows(self.db, ids, user_id)
        except Exception as e:
            logger.exception(f"Error soft-deleting rows: {e}")
            raise

    def restore_rows(self, record_ids: str, user_id: UUID) -> int:
        """
        Restore one or more previously soft-deleted mart rows.
        """
        ids = self._parse_record_ids(record_ids)
        try:
            return user_overrides_dao.restore_rows(self.db, ids, user_id)
        except Exception as e:
            logger.exception(f"Error restoring rows: {e}")
            raise

    def bulk_upsert(self, items: List[Dict[str, Any]], user_id: UUID) -> None:
        """
        Upsert overrides for multiple records in a single request.
        """
        if not items:
            return
        if len(items) > _MAX_BULK_IDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Bulk upsert limited to {_MAX_BULK_IDS} items per request"
            )
        try:
            user_overrides_dao.bulk_upsert_overrides(self.db, items, user_id)
        except Exception as e:
            logger.exception(f"Error in bulk upsert overrides: {e}")
            raise

    def upsert_override(self, record_id: str, overrides: Dict[str, Any], user_id: UUID, old_values: Dict[str, Any]) -> None:
        """
        Upsert user override fields for a mart record.
        """
        try:
            user_overrides_dao.upsert_override(self.db, record_id, overrides, user_id, old_values)
        except Exception as e:
            logger.exception(f"Error upserting override for record {record_id}: {e}")
            raise

    def revert_record(self, record_id: str, user_id: UUID) -> bool:
        """
        Soft-delete all overrides for a record.
        """
        try:
            return user_overrides_dao.revert_record(self.db, record_id, user_id)
        except Exception as e:
            logger.exception(f"Error reverting record {record_id}: {e}")
            raise

    def revert_field(self, record_id: str, field_name: str, user_id: UUID) -> bool:
        """
        Remove a single overridden field for a record.
        """
        try:
            return user_overrides_dao.revert_field(self.db, record_id, field_name, user_id)
        except Exception as e:
            logger.exception(f"Error reverting field {field_name} for record {record_id}: {e}")
            raise
