from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from typing import Dict, Any, List

from mpi_backend.database import get_db
from mpi_backend.database.models.User import User
from mpi_backend.database.controllers.UserOverrideController import UserOverrideController
from mpi_backend.utils.auth.dependencies import require_bookkeeping_or_admin

router = APIRouter(prefix="/overrides", tags=["User Overrides"])


class BulkUpsertItem(BaseModel):
    record_id: str
    overrides: Dict[str, Any]
    old_values: Dict[str, Any]

    @field_validator("overrides")
    @classmethod
    def no_null_values(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            raise ValueError("overrides must not be empty")
        null_keys = [k for k, val in v.items() if val is None]
        if null_keys:
            raise ValueError(f"Override values cannot be null: {null_keys}")
        return v


# /bulk must be registered before /{record_id} to avoid the path parameter
# swallowing the literal "bulk" segment.
@router.post("/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_upsert_overrides_endpoint(
    items: List[BulkUpsertItem],
    current_user: User = Depends(require_bookkeeping_or_admin),
    db: Session = Depends(get_db),
):
    """
    Upsert overrides for multiple records in a single request.

    Accepts a list of {record_id, overrides} objects and writes them
    all in one transaction.
    """
    controller = UserOverrideController(db)
    controller.bulk_upsert(
        [{"record_id": item.record_id, "overrides": item.overrides, "old_values": item.old_values} for item in items],
        current_user.id,
    )


@router.post("/rows/restore", status_code=status.HTTP_200_OK)
async def restore_rows_endpoint(
    record_ids: str = Query(
        ...,
        description="Comma-separated list of record IDs (invoice_items_id) to restore.",
        example="123,456,789",
    ),
    current_user: User = Depends(require_bookkeeping_or_admin),
    db: Session = Depends(get_db),
):
    """
    Restore one or more previously soft-deleted mart rows.

    Rows are made visible again in data-review views and aggregations.
    Any field-level overrides that existed before deletion are also restored.

    Query param:
        record_ids: Comma-separated invoice_items_id values, e.g. ``123,456``
    """
    controller = UserOverrideController(db)
    restored = controller.restore_rows(record_ids, current_user.id)
    return {
        "success": True,
        "message": f"{restored} row(s) restored."
    }


@router.delete("/rows", status_code=status.HTTP_200_OK)
async def soft_delete_rows_endpoint(
    record_ids: str = Query(
        ...,
        description="Comma-separated list of record IDs (invoice_items_id) to soft-delete.",
        example="123,456,789",
    ),
    current_user: User = Depends(require_bookkeeping_or_admin),
    db: Session = Depends(get_db),
):
    """
    Soft-delete one or more mart rows.

    Deleted rows are immediately hidden from all data-review views and
    excluded from aggregate calculations.  The operation is reversible —
    use POST /overrides/rows/restore to bring them back.

    Field-level overrides on a deleted row are preserved so they are
    restored automatically when the row is un-deleted.

    Query param:
        record_ids: Comma-separated invoice_items_id values, e.g. ``123,456``
    """
    controller = UserOverrideController(db)
    affected = controller.soft_delete_rows(record_ids, current_user.id)
    return {
        "success": True,
        "message": f"{affected} row(s) soft-deleted."
    }


class UpsertOverrideRequest(BaseModel):
    overrides: Dict[str, Any]
    old_values: Dict[str, Any]

    @field_validator("overrides")
    @classmethod
    def no_null_values(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            raise ValueError("overrides must not be empty")
        null_keys = [k for k, val in v.items() if val is None]
        if null_keys:
            raise ValueError(f"Override values cannot be null: {null_keys}")
        return v


@router.post("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_override_endpoint(
    record_id: str,
    body: UpsertOverrideRequest,
    current_user: User = Depends(require_bookkeeping_or_admin),
    db: Session = Depends(get_db),
):
    """
    Upsert user override fields for a mart record.

    Merges the supplied overrides JSONB into any existing override row for
    record_id. Creates the row if it does not exist.
    """
    controller = UserOverrideController(db)
    controller.upsert_override(record_id, body.overrides, current_user.id, body.old_values)


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revert_record_endpoint(
    record_id: str,
    current_user: User = Depends(require_bookkeeping_or_admin),
    db: Session = Depends(get_db),
):
    """
    Soft-delete all overrides for a record (reverts all fields to mart values).
    """
    controller = UserOverrideController(db)
    found = controller.revert_record(record_id, current_user.id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Override record not found")


@router.delete("/{record_id}/fields/{field_name}", status_code=status.HTTP_204_NO_CONTENT)
async def revert_field_endpoint(
    record_id: str,
    field_name: str,
    current_user: User = Depends(require_bookkeeping_or_admin),
    db: Session = Depends(get_db),
):
    """
    Remove a single overridden field for a record (reverts that field to its mart value).
    """
    controller = UserOverrideController(db)
    found = controller.revert_field(record_id, field_name, current_user.id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Override record not found")
