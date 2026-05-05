"""
DBT Operations API Routes

Provides endpoints for managing and monitoring dbt materialized view refreshes.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel

from mpi_backend.database.models.User import User
from mpi_backend.database.models.DbtRun import DbtRunStatus
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.utils.dbt_scheduler import get_dbt_runner
from mpi_backend.config import ENVIRONMENT
from mpi_backend.utils.elementary_report_service import send_report_to_s3
from mpi_backend.background.scheduler import get_scheduler_instance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync/dbt", tags=["Sync Mapping", "dbt"])

HEALTH_MESSAGES = {
    "not_started": "DBT system is healthy (no refreshes yet)",
    DbtRunStatus.SUCCESS.value: "DBT system is healthy (last refresh successful)",
    DbtRunStatus.RUNNING.value: "DBT refresh currently in progress",
}
HEALTHY_STATUSES = {"not_started", DbtRunStatus.SUCCESS.value}


# TODO: Move these classes to a better location
class RefreshResponse(BaseModel):
    """
    Response model for the DBT refresh operation.

    When a refresh is successfully started in the background, this model
    provides immediate feedback. The full results of the dbt run can be
    monitored via the `/status` endpoint.

    Attributes:
        status: Indicates the outcome of the request. Possible values are
                "started" if the refresh began, or "already_running" if a
                refresh was already in progress.
        message: A human-readable message describing the outcome.
        execution_time: The time in seconds for the operation to complete.
                        Note: This is not returned when starting a background task.
        timestamp: The ISO 8601 timestamp for when the operation was requested.
        error: A description of any error that occurred.
        output: The stdout from the dbt process.
                Note: This is not returned when starting a background task.
    """
    status: str
    message: Optional[str] = None


class StatusResponse(BaseModel):
    """
    Response model for the DBT status endpoint.

    Provides a comprehensive overview of the DBT runner's current state,
    including its operational status and scheduling details.

    Attributes:
        runner_status: A dictionary containing the detailed status from the
                       DBTRunner, including whether a refresh is running,
                       the last refresh time, status, and any errors.
        next_scheduled_run: The ISO 8601 timestamp for the next scheduled
                            dbt refresh job.
        scheduler_job_id: The unique identifier for the scheduled dbt job,
                          which is typically "dbt_refresh".
    """
    runner_status: dict
    next_scheduled_run: Optional[str] = None
    scheduler_job_id: str = "dbt_refresh"


class HealthResponse(BaseModel):
    """
    Response model for the health check endpoint.

    Offers a simple, high-level overview of the DBT system's health,
    suitable for automated monitoring and liveness probes.

    Attributes:
        healthy: A boolean indicating if the system is considered healthy.
                 This is true if the last refresh was successful or if no
                 refreshes have occurred yet.
        last_status: The status of the last dbt refresh (e.g., "success",
                     "failed", "timeout", "not_started").
        last_refresh_time: The ISO 8601 timestamp of the last refresh.
        message: A human-readable message summarizing the health status.
    """
    healthy: bool
    last_status: str
    last_refresh_time: Optional[str] = None
    message: str


@router.get("/status", response_model=StatusResponse)
async def get_dbt_status(current_user: User = Depends(get_current_user)):
    """
    Get current DBT runner status and next scheduled run time.

    Returns:
        StatusResponse with runner status and scheduling information
    """
    try:
        runner = get_dbt_runner()
        runner_status = runner.get_status()

        # Try to get next scheduled run from scheduler
        next_scheduled_run = None
        scheduler = get_scheduler_instance()
        if scheduler:
            try:
                job = scheduler.get_job("dbt_refresh")
                if job and job.next_run_time:
                    next_scheduled_run = job.next_run_time.isoformat()
            except Exception as e:
                logger.debug(f"Could not get next scheduled run: {e}")

        return StatusResponse(
            runner_status=runner_status,
            next_scheduled_run=next_scheduled_run,
            scheduler_job_id="dbt_refresh"
        )
    except Exception as e:
        logger.error(f"Error getting DBT status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to get DBT status"
        )


async def _trigger_dbt_refresh(
    background_tasks: BackgroundTasks, current_user: User, full_refresh: bool
) -> RefreshResponse:
    label = "Full" if full_refresh else "Regular"
    try:
        runner = get_dbt_runner()

        if runner.is_refresh_in_progress():
            return RefreshResponse(
                status="already_running",
                message="A refresh is already in progress."
            )

        background_tasks.add_task(
            runner.try_refresh_materialized_views,
            user_id=current_user.id,
            full_refresh=full_refresh
        )

        return RefreshResponse(
            status="started",
            message=f"{label} DBT refresh process has been started in the background."
        )
    except Exception as e:
        logger.error(f"Error triggering {label} DBT refresh: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger {label.lower()} DBT refresh"
        )


@router.post("/refresh", response_model=RefreshResponse)
async def trigger_refresh(background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user)):
    """Manually trigger a regular DBT refresh."""
    return await _trigger_dbt_refresh(background_tasks, current_user, full_refresh=False)


@router.post("/full-refresh", response_model=RefreshResponse)
async def trigger_full_refresh(background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user)):
    """Manually trigger a full DBT refresh."""
    return await _trigger_dbt_refresh(background_tasks, current_user, full_refresh=True)


@router.get("/health", response_model=HealthResponse)
async def check_health(current_user: User = Depends(get_current_user)):
    """
    Simple health check for DBT operations.

    Returns:
        HealthResponse indicating if DBT system is healthy
    """
    try:
        runner = get_dbt_runner()
        status = runner.get_status()

        last_status = status.get("last_refresh_status", "unknown")
        healthy = last_status in HEALTHY_STATUSES
        message = HEALTH_MESSAGES.get(last_status, f"DBT system unhealthy (last status: {last_status})")

        return HealthResponse(
            healthy=healthy,
            last_status=last_status,
            last_refresh_time=status.get("last_refresh_time"),
            message=message
        )
    except Exception as e:
        logger.error(f"Error checking DBT health: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to check DBT health"
        )


class ElementaryReportResponse(BaseModel):
    status: str
    message: Optional[str] = None


def _run_elementary_report_background():
    """Background task wrapper for Elementary report generation."""
    try:
        s3_key = send_report_to_s3()
        if s3_key:
            logger.info(f"Elementary report sent to S3: {s3_key}")
        else:
            logger.warning("Elementary report generation returned no S3 key")
    except Exception:
        logger.exception("Elementary report background task failed")


@router.post("/elementary-report", response_model=ElementaryReportResponse)
async def trigger_elementary_report(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Manually trigger Elementary report generation and S3 upload."""
    try:
        if ENVIRONMENT != "production":
            return ElementaryReportResponse(
                status="skipped",
                message=f"Elementary reports only publish in production (current: {ENVIRONMENT}).",
            )

        runner = get_dbt_runner()
        if runner.is_refresh_in_progress():
            return ElementaryReportResponse(
                status="skipped",
                message="A dbt refresh is in progress. Try again after it completes.",
            )

        background_tasks.add_task(_run_elementary_report_background)

        return ElementaryReportResponse(
            status="started",
            message="Elementary report generation has been started in the background.",
        )
    except Exception as e:
        logger.error(f"Error triggering Elementary report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to trigger Elementary report generation",
        )
