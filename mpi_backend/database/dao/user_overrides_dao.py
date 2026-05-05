"""
DAO write path for user_overrides table.

Provides upsert, field revert, record revert, and row soft-delete operations.
All functions accept db: Session as first param (ADR-0001).
"""

import json
import logging
import time
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text


logger = logging.getLogger(__name__)


def upsert_override(db: Session, record_id: str, overrides: dict, overridden_by: UUID, old_values: dict) -> None:
    """
    Upsert override fields for a record.

    On conflict, merges new overrides into the existing JSONB (|| operator preserves
    existing fields not present in the new payload). Null values are stored as-is.
    """
    start = time.time()
    db.execute(text("SET LOCAL app.override_old_values = :val"), {"val": json.dumps(old_values)})
    db.execute(
        text("""
            INSERT INTO public.user_overrides (record_id, overrides, overridden_by)
            VALUES (:record_id, CAST(:overrides AS jsonb), :overridden_by)
            ON CONFLICT (record_id) DO UPDATE
                SET overrides     = user_overrides.overrides || EXCLUDED.overrides,
                    overridden_by = EXCLUDED.overridden_by,
                    overridden_at = NOW(),
                    deleted_at    = NULL
        """),
        {
            "record_id": record_id,
            "overrides": json.dumps(overrides),
            "overridden_by": str(overridden_by),
        }
    )
    db.commit()
    logger.info(f"upsert_override record_id={record_id} elapsed={time.time()-start:.3f}s")


def revert_field(db: Session, record_id: str, field_name: str, overridden_by: UUID) -> bool:
    """
    Remove a single field from the overrides JSONB for a record.

    If removing the field leaves the overrides as '{}', soft-deletes the row.
    """
    start = time.time()
    result = db.execute(
        text("""
            UPDATE public.user_overrides
            SET overrides     = overrides - :field_name,
                overridden_by = :overridden_by,
                overridden_at = NOW(),
                deleted_at    = CASE
                                    WHEN (overrides - :field_name) = '{}'::jsonb THEN NOW()
                                    ELSE NULL
                                END
            WHERE record_id = :record_id
              AND deleted_at IS NULL
              AND overrides ? :field_name
        """),
        {
            "record_id": record_id,
            "field_name": field_name,
            "overridden_by": str(overridden_by),
        }
    )
    db.commit()
    found = result.rowcount > 0
    logger.info(f"revert_field record_id={record_id} field={field_name} found={found} elapsed={time.time()-start:.3f}s")
    return found


def bulk_upsert_overrides(db: Session, items: list[dict], overridden_by: UUID) -> None:
    """
    Upsert overrides for multiple records in a single transaction.

    Each item must have:
        record_id: str
        overrides: dict  — null values are stored as-is
        old_values: dict
    """
    start = time.time()
    for item in items:
        db.execute(text("SET LOCAL app.override_old_values = :val"), {"val": json.dumps(item["old_values"])})
        db.execute(
            text("""
                INSERT INTO public.user_overrides (record_id, overrides, overridden_by)
                VALUES (:record_id, CAST(:overrides AS jsonb), :overridden_by)
                ON CONFLICT (record_id) DO UPDATE
                    SET overrides     = user_overrides.overrides || EXCLUDED.overrides,
                        overridden_by = EXCLUDED.overridden_by,
                        overridden_at = NOW(),
                        deleted_at    = NULL
            """),
            {
                "record_id": item["record_id"],
                "overrides": json.dumps(item["overrides"]),
                "overridden_by": str(overridden_by),
            }
        )
    db.commit()
    logger.info(f"bulk_upsert_overrides count={len(items)} elapsed={time.time()-start:.3f}s")


def revert_record(db: Session, record_id: str, overridden_by: UUID) -> bool:
    """
    Soft-delete the entire override row for a record (restores all fields to mart values).
    """
    start = time.time()
    result = db.execute(
        text("""
            UPDATE public.user_overrides
            SET deleted_at    = NOW(),
                overridden_by = :overridden_by,
                overridden_at = NOW()
            WHERE record_id = :record_id
              AND deleted_at IS NULL
        """),
        {
            "record_id": record_id,
            "overridden_by": str(overridden_by),
        }
    )
    db.commit()
    found = result.rowcount > 0
    logger.info(f"revert_record record_id={record_id} found={found} elapsed={time.time()-start:.3f}s")
    return found


def soft_delete_rows(db: Session, record_ids: list[str], deleted_by: UUID) -> int:
    """
    Soft-delete one or more mart rows so they are hidden from all views and aggregate calculations.

    Each record_id maps to an invoice_items_id (cast to text) in the mart table.
    The operation is an upsert:
    - If no override row exists yet, one is created with an empty overrides JSONB
      and is_row_deleted = TRUE.
    - If an override row already exists (field overrides in place), the existing
      overrides JSONB is preserved so field edits survive the deletion.  Only
      is_row_deleted and deleted_at are changed.

    The row is kept *active* (deleted_at = NULL) so the query layer can read
    is_row_deleted = TRUE from the LEFT JOIN and filter it out.

    Args:
        db: SQLAlchemy database session.
        record_ids: List of record IDs (invoice_items_id cast to text) to soft-delete.
        deleted_by: UUID of the user performing the deletion.

    Returns:
        Number of rows affected (upserted).
    """
    if not record_ids:
        return 0

    start = time.time()
    affected = 0
    for record_id in record_ids:
        result = db.execute(
            text("""
                INSERT INTO public.user_overrides
                    (record_id, overrides, overridden_by, overridden_at, deleted_at, is_row_deleted)
                VALUES
                    (:record_id, '{}'::jsonb, :deleted_by, NOW(), NULL, TRUE)
                ON CONFLICT (record_id) DO UPDATE
                    SET is_row_deleted = TRUE,
                        overridden_by  = EXCLUDED.overridden_by,
                        overridden_at  = NOW(),
                        deleted_at     = NULL
            """),
            {
                "record_id": record_id,
                "deleted_by": str(deleted_by),
            }
        )
        affected += result.rowcount

    db.commit()
    logger.info(
        f"soft_delete_rows count={len(record_ids)} affected={affected} "
        f"elapsed={time.time()-start:.3f}s"
    )
    return affected


def restore_rows(db: Session, record_ids: list[str], restored_by: UUID) -> int:
    """
    Restore one or more previously soft-deleted mart rows.

    Sets is_row_deleted = FALSE on existing override rows.
    If a row has no field-level overrides (overrides = '{}') after restore,
    it is also soft-deleted (deleted_at = NOW()) to clean up the override table
    — the row effectively goes back to having no overrides at all.

    Rows that still have field overrides after restore remain active
    (deleted_at = NULL) so those overrides continue to apply.

    Args:
        db: SQLAlchemy database session.
        record_ids: List of record IDs to restore.
        restored_by: UUID of the user performing the restore.

    Returns:
        Number of rows actually restored (rows that were is_row_deleted = TRUE).
    """
    if not record_ids:
        return 0

    start = time.time()
    result = db.execute(
        text("""
            UPDATE public.user_overrides
            SET is_row_deleted = FALSE,
                overridden_by  = :restored_by,
                overridden_at  = NOW(),
                -- Clean up empty override rows now that the deletion flag is gone.
                -- Rows with actual field overrides stay active (deleted_at = NULL).
                deleted_at     = CASE
                                     WHEN overrides = '{}'::jsonb THEN NOW()
                                     ELSE NULL
                                 END
            WHERE record_id = ANY(:record_ids)
              AND is_row_deleted = TRUE
        """),
        {
            "record_ids": record_ids,
            "restored_by": str(restored_by),
        }
    )
    db.commit()
    affected = result.rowcount
    logger.info(
        f"restore_rows count={len(record_ids)} restored={affected} "
        f"elapsed={time.time()-start:.3f}s"
    )
    return affected

