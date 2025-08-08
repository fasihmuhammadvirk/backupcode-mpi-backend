import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from typing import Callable, Any, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Import business logic tasks lazily in functions to avoid heavy imports at module load
from mpi_backend.utils.quickbooks_priority import set_scheduler_instance

logger = logging.getLogger(__name__)


# Configuration
UTC_TZ = pytz.utc
MAPPINGS_ENABLED = os.getenv("ENABLE_MAPPINGS", "true").lower() == "true"
MAPPINGS_EXCLUSION_ENABLED = os.getenv("ENABLE_MAPPINGS_EXCLUSION", "true").lower() == "true"


# Thread pools – separate pools so IO-heavy jobs do not interfere with mapping tasks
task_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mapping_task")
email_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="email_task")


# Simple retry wrapper for background tasks
def _run_with_retries(
    func: Callable[..., Any],
    *args: Any,
    retries: int = 2,
    initial_delay_seconds: float = 5.0,
    backoff_factor: float = 2.0,
    **kwargs: Any,
) -> Optional[Any]:
    delay = initial_delay_seconds
    attempt = 0
    while True:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            logger.error(
                "Background task failed (attempt %s/%s): %s",
                attempt,
                retries + 1,
                exc,
            )
            if attempt > retries:
                logger.error("Background task permanently failed after retries")
                return None
            with suppress(Exception):
                time.sleep(delay)
            delay *= backoff_factor


# Non-blocking wrappers – submit to appropriate thread pools
def async_email_download_wrapper():
    from mpi_backend.utils.invoice_downaloder import email_download_background_task

    def _execute():
        logger.info("Starting async email download task")
        _run_with_retries(email_download_background_task)
        logger.info("Email download task completed")

    email_executor.submit(_execute)


def async_statement_download_wrapper():
    from mpi_backend.utils.statement_downloader import (
        statement_download_background_task,
    )

    def _execute():
        logger.info("Starting async statement download task")
        _run_with_retries(statement_download_background_task)
        logger.info("Statement download task completed")

    email_executor.submit(_execute)


def async_failed_invoice_recovery_wrapper():
    from mpi_backend.utils.failed_invoice_recovery import (
        failed_invoice_recovery_background_task,
    )

    def _execute():
        logger.info("Starting async failed invoice recovery task")
        _run_with_retries(failed_invoice_recovery_background_task)
        logger.info("Failed invoice recovery task completed")

    email_executor.submit(_execute)


def async_missing_invoice_download_wrapper():
    from mpi_backend.utils.missing_invoice_downaloder import (
        missing_email_download_background_task,
    )

    def _execute():
        logger.info("Starting async missing invoice download task")
        _run_with_retries(missing_email_download_background_task)
        logger.info("Missing invoice download task completed")

    email_executor.submit(_execute)


def scheduled_uidi_no_match_update():
    """Daily UIDI/NO Match update, runs on mapping thread pool."""
    def _execute():
        try:
            logger.info("Starting scheduled UIDI/NO Match update")
            from mpi_backend.database import SessionLocal
            from mpi_backend.database.controllers.GoogleSheetSyncController import (
                GoogleSheetSyncController,
            )

            with SessionLocal() as temp_db:
                GoogleSheetSyncController.execute_sync_task(temp_db, "update_no_match_uidi")
            logger.info("Scheduled UIDI/NO Match update completed")
        except Exception as exc:  # noqa: BLE001
            logger.error("UIDI/NO Match update failed: %s", exc)

    task_executor.submit(_execute)


def scheduled_all_mappings_update():
    """Weekly All Mappings update, runs on mapping thread pool."""
    def _execute():
        try:
            logger.info("Starting scheduled All Mappings update")
            from mpi_backend.database import SessionLocal
            from mpi_backend.database.controllers.GoogleSheetSyncController import (
                GoogleSheetSyncController,
            )

            with SessionLocal() as temp_db:
                GoogleSheetSyncController.execute_sync_task(temp_db, "update_all")
            logger.info("Scheduled All Mappings update completed")
        except Exception as exc:  # noqa: BLE001
            logger.error("All Mappings update failed: %s", exc)

    task_executor.submit(_execute)


def memory_cleanup_task():
    import gc

    try:
        collected = gc.collect()
        logger.info("Memory cleanup completed - collected %s objects", collected)
    except Exception as exc:  # noqa: BLE001
        logger.error("Memory cleanup failed: %s", exc)


def init_scheduler() -> BackgroundScheduler:
    """Create and configure the APScheduler with all jobs and exact timing preserved."""
    scheduler = BackgroundScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 300,
        },
        timezone=UTC_TZ,
    )

    # Register scheduler globally for QuickBooks priority control
    set_scheduler_instance(scheduler)

    # Interval jobs (IDs and timings preserved exactly)
    scheduler.add_job(
        async_email_download_wrapper,
        "interval",
        minutes=5,
        max_instances=1,
        id="email_download",
        name="Email Download Task (Every 5 Minutes, Async)",
        misfire_grace_time=600,
        replace_existing=True,
    )

    scheduler.add_job(
        async_statement_download_wrapper,
        "interval",
        hours=12,
        max_instances=1,
        id="statement_download",
        name="Statement Download Task (Every 12 Hours, Async)",
        misfire_grace_time=1800,
        replace_existing=True,
    )

    scheduler.add_job(
        async_failed_invoice_recovery_wrapper,
        "interval",
        hours=1,
        max_instances=1,
        id="failed_invoice_recovery",
        name="Failed Invoice Recovery Task (Every 1 Hour, Async)",
        misfire_grace_time=1800,
        replace_existing=True,
    )

    scheduler.add_job(
        async_missing_invoice_download_wrapper,
        "interval",
        hours=5,
        max_instances=1,
        id="missing_invoice_download",
        name="Missing Invoice Download Task (Every 5 Hours, Async)",
        misfire_grace_time=1800,
        replace_existing=True,
    )

    # Cron jobs (times preserved)
    scheduler.add_job(
        scheduled_uidi_no_match_update,
        CronTrigger(hour=13, minute=0, timezone=UTC_TZ),
        id="daily_uidi_no_match_update",
        max_instances=1,
        name="Daily UIDI/NO Match Update (6 PM PKT)",
        misfire_grace_time=3600,
        replace_existing=True,
    )

    scheduler.add_job(
        scheduled_all_mappings_update,
        CronTrigger(hour=3, minute=0, timezone=UTC_TZ, day_of_week=5),
        id="all_mappings_update_saturday_8am",
        max_instances=1,
        name="All Mappings Update (Every Saturday at 8 AM PKT)",
        misfire_grace_time=3600,
        replace_existing=True,
    )

    # Memory cleanup – keep app lean
    scheduler.add_job(
        memory_cleanup_task,
        "interval",
        minutes=30,
        max_instances=1,
        id="memory_cleanup",
        name="Memory Cleanup Task",
        replace_existing=True,
    )

    return scheduler

