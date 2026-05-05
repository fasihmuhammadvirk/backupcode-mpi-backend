from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Literal, Optional
from uuid import UUID

from mpi_backend.database import get_db
from mpi_backend.database.models.User import User
from mpi_backend.database.dao.user_override_logs_dao import get_override_logs
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.utils.auth.roles import UserRole

router = APIRouter(prefix="/override-logs", tags=["Override Logs"])


@router.get("")
async def list_override_logs(
    record_id: Optional[str] = None,
    overridden_by: Optional[UUID] = None,
    action_type: Optional[Literal["upsert", "field_revert", "record_revert", "row_delete", "row_restore"]] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List override audit log entries with optional filters.

    Filters: record_id, overridden_by (UUID), action_type, date_from, date_to (ISO dates).
    Non-admin users only see logs for their own company.
    """
    company_id = None if current_user.role == UserRole.ADMIN.value else current_user.company_id
    return get_override_logs(
        db,
        record_id=record_id,
        overridden_by=str(overridden_by) if overridden_by else None,
        action_type=action_type,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        page=page,
        size=size,
        company_id=company_id,
    )
