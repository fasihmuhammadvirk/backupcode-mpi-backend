import logging
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Any, Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Import business logic tasks lazily in functions to avoid heavy imports
from mpi_backend.utils.quickbooks_priority import set_scheduler_instance

logger = logging.getLogger(__name__)

# SIMPLE DUPLICATION PREVENTION: 1 worker per task
# APScheduler's max_instances=1 ensures only one instance of each task runs
# This prevents duplicate execution across multiple workers without complex locking


# Configuration
UTC_TZ = pytz.utc
MAPPINGS_ENABLED = os.getenv("ENABLE_MAPPINGS", "true").lower() == "true"
EXCLUSION_ENABLED = os.getenv("ENABLE_MAPPINGS_EXCLUSION", "true").lower()




# Optimized thread pools with better resource isolation
# Separate pools for different types of operations to prevent interference
mapping_executor = ThreadPoolExecutor(
    max_workers=3,
    thread_name_prefix="mapping_task"
)
email_executor = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="email_task"
)
download_executor = ThreadPoolExecutor(
    max_workers=6,
    thread_name_prefix="download_task"
)
processing_executor = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="processing_task"
)


# Enhanced async retry wrapper for background tasks
async def _run_with_retries_async(
    func: Callable[..., Any],
    *args: Any,
    retries: int = 2,
    initial_delay_seconds: float = 5.0,
    backoff_factor: float = 2.0,
    **kwargs: Any,
) -> Optional[Any]:
    """Async retry wrapper that doesn't block the event loop"""
    delay = initial_delay_seconds
    attempt = 0
    while True:
        try:
            # Run the function in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                processing_executor, func, *args, **kwargs
            )
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            logger.error(
                "Background task failed (attempt %s/%s): %s",
                attempt,
                retries + 1,
                exc,
            )
            if attempt > retries:
                logger.error("Background task permanently failed")
                return None
            # Use asyncio.sleep to avoid blocking
            await asyncio.sleep(delay)
            delay *= backoff_factor





# Simple async wrappers - APScheduler handles duplication prevention
async def async_email_download_wrapper():
    """Email download task - uses email_executor"""
    from mpi_backend.utils.invoice_downaloder import (
        email_download_background_task,
    )
    
    try:
        logger.info("Starting email download task")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(email_executor, email_download_background_task)
        logger.info("Email download task completed")
    except Exception as e:
        logger.error(f"Email download failed: {e}")


async def async_statement_download_wrapper():
    """Statement download task - uses download_executor"""
    from mpi_backend.utils.statement_downloader import (
        statement_download_background_task,
    )
    
    try:
        logger.info("Starting statement download task")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            download_executor, statement_download_background_task
        )
        logger.info("Statement download task completed")
    except Exception as e:
        logger.error(f"Statement download failed: {e}")


async def async_failed_invoice_recovery_wrapper():
    """Failed invoice recovery task - uses processing_executor"""
    from mpi_backend.utils.failed_invoice_recovery import (
        failed_invoice_recovery_background_task,
    )
    
    try:
        logger.info("Starting failed invoice recovery task")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            processing_executor, failed_invoice_recovery_background_task
        )
        logger.info("Failed invoice recovery task completed")
    except Exception as e:
        logger.error(f"Failed invoice recovery failed: {e}")


async def async_missing_invoice_download_wrapper():
    """Missing invoice download task - uses download_executor"""
    from mpi_backend.utils.missing_invoice_downaloder import (
        missing_email_download_background_task,
    )
    
    try:
        logger.info("Starting missing invoice download task")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            download_executor, missing_email_download_background_task
        )
        logger.info("Missing invoice download task completed")
    except Exception as e:
        logger.error(f"Missing invoice download failed: {e}")


async def scheduled_uidi_no_match_update():
    """Daily UIDI/NO Match update - uses mapping_executor"""
    from mpi_backend.database.controllers.GoogleSheetSyncController import (
        GoogleSheetSyncController,
    )
    
    try:
        logger.info("Starting scheduled UIDI/NO Match update")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            mapping_executor,
            GoogleSheetSyncController._execute_sync_task_worker,
            None,
            "update_no_match_uidi"
        )
        logger.info("UIDI/NO Match update completed")
    except Exception as e:
        logger.error(f"UIDI/NO Match update failed: {e}")


async def scheduled_all_mappings_update():
    """Weekly All Mappings update - uses mapping_executor"""
    from mpi_backend.database.controllers.GoogleSheetSyncController import (
        GoogleSheetSyncController,
    )
    
    try:
        logger.info("Starting scheduled All Mappings update")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            mapping_executor,
            GoogleSheetSyncController._execute_sync_task_worker,
            None,
            "update_all"
        )
        logger.info("All Mappings update completed")
    except Exception as e:
        logger.error(f"All Mappings update failed: {e}")


async def memory_cleanup_task():
    """Memory cleanup task - runs in processing executor"""
    import gc
    
    try:
        logger.info("Starting memory cleanup")
        loop = asyncio.get_event_loop()
        collected = await loop.run_in_executor(processing_executor, gc.collect)
        logger.info(f"Memory cleanup completed - collected {collected} objects")
    except Exception as exc:  # noqa: BLE001
        logger.error("Memory cleanup failed: %s", exc)


def init_scheduler() -> AsyncIOScheduler:
    """Create and configure AsyncIOScheduler for non-blocking execution."""
    scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,  # Combine missed executions
            "max_instances": 1,  # Only 1 instance per task
            "misfire_grace_time": 300,  # 5 minutes grace period
        },
        timezone=UTC_TZ,
    )

    # Register scheduler globally for QuickBooks priority control
    set_scheduler_instance(scheduler)

    # Interval jobs - 1 worker per task prevents duplication
    scheduler.add_job(
        async_email_download_wrapper,
        "interval",
        minutes=5,
        max_instances=1,  # Only 1 instance can run at a time
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
