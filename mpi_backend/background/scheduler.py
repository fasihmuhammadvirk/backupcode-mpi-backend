"""
Simple, Unrestricted APScheduler Configuration for MPI Backend
No restrictions, no memory management, no performance monitoring.
"""

import gc
import logging
import pytz
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor as APSchedulerThreadPool

from mpi_backend.background.tasks.email_download import download_emails
from mpi_backend.utils.quickbooks_priority_controller import (
    set_scheduler_instance,
    get_scheduler_instance as get_global_scheduler_instance
)
from mpi_backend.utils.dbt_scheduler import get_dbt_runner, DBTConfig, RefreshStatus

logger = logging.getLogger(__name__)

# Simple, unrestricted configuration
JOB_COALESCE_TIME = 1800  # 30 minutes grace period

def init_scheduler() -> BackgroundScheduler:
    """
    Create a simple, unrestricted APScheduler with no restrictions.
    """
    
    # Simple executor configuration - no restrictions
    executors = {
        'default': APSchedulerThreadPool(10),   # Lightweight for scheduler internals
        'background': APSchedulerThreadPool(100),  # Dedicated pool for background tasks
    }
    
    # Simple job defaults - no restrictions
    job_defaults = {
        "coalesce": True,                    # Combine missed executions
        "max_instances": 10,                 # Allow multiple instances
        "misfire_grace_time": JOB_COALESCE_TIME,  # Grace period for missed jobs
        "timeout": None,                     # No timeout restrictions
        "max_instances_per_job": 10,         # Allow multiple instances per job
    }
    
    # Create simple scheduler
    scheduler = BackgroundScheduler(
        executors=executors,
        job_defaults=job_defaults,
        timezone=pytz.utc,
        jobstores={'default': {'type': 'memory'}},
    )

    # Register scheduler globally
    set_scheduler_instance(scheduler)

    # =============================================================================
    # BACKGROUND JOBS - No restrictions
    # =============================================================================
    
    # Email downloads - every 5 minutes
    scheduler.add_job(
        download_emails,
        "interval",
        minutes=5,
        executor='background',
        id="email_download",
        name="Email Download Task (Every 5 Minutes)",
        replace_existing=True,
        max_instances=1,
    )

    # =============================================================================
    # CRON JOBS - No restrictions
    # =============================================================================
    
    # Memory cleanup - every 6 hours
    scheduler.add_job(
        scheduled_memory_cleanup,
        "interval",
        hours=6,
        executor='background',
        id="memory_cleanup",
        name="Memory Cleanup (Every 6 Hours)",
        replace_existing=True,
    )

    # =============================================================================
    # DBT REFRESH JOB - Conditionally enabled
    # =============================================================================

    dbt_config = DBTConfig.from_env()

    # Check if dbt is enabled and return early if it is
    if not dbt_config.enabled:
        logger.info("DBT refresh job disabled via DBT_SCHEDULER_ENABLED=false")
        return scheduler

    # Calculate next run time with initial delay
    next_run_time = datetime.now(pytz.utc) + timedelta(seconds=dbt_config.initial_delay_seconds)

    scheduler.add_job(
        dbt_refresh_wrapper,
        "interval",
        minutes=dbt_config.refresh_interval_minutes,
        executor='background',
        id="dbt_refresh",
        name=f"DBT Materialized Views Refresh (Every {dbt_config.refresh_interval_minutes} Minutes)",
        replace_existing=True,
        max_instances=1,  # Prevent concurrent refreshes
        next_run_time=next_run_time
    )
    logger.info(f"DBT refresh job scheduled: every {dbt_config.refresh_interval_minutes} minutes")

    return scheduler

def start_scheduler():
    """Start the scheduler with no restrictions."""
    try:
        scheduler = init_scheduler()
        scheduler.start()
        logger.info("Scheduler started successfully - no restrictions applied")

        # Log all registered jobs with their next run times
        jobs = scheduler.get_jobs()
        logger.info(f"Total registered jobs: {len(jobs)}")
        
        for job in jobs:
            next_run = job.next_run_time
            logger.info(
                f"Registered job: {job.id} ({job.name}). "
                f"Next run: {next_run}"
            )

        # Specifically check and log key scheduled jobs
        # Check DBT refresh job
        dbt_job = scheduler.get_job("dbt_refresh")
        if dbt_job:
            next_run = dbt_job.next_run_time
            logger.info("✓ Registered dbt_refresh job successfully. " f"Next run: {next_run}")
        else:
            logger.info("DBT refresh job not registered (disabled or error)")

        return scheduler
    except Exception as e:
        logger.error("Failed to start scheduler: %s", e, exc_info=True)
        return None

def stop_scheduler():
    """Stop the scheduler."""
    try:
        scheduler = get_scheduler_instance()
        if scheduler:
            scheduler.shutdown()
            logger.info("Scheduler stopped successfully")
    except Exception as e:
        logger.error("Error stopping scheduler: %s", e)

def get_scheduler_instance():
    """Get the global scheduler instance."""
    try:
        return get_global_scheduler_instance()
    except ImportError:
        logger.warning("Could not import get_scheduler_instance")
        return None

def scheduled_memory_cleanup():
    """Simple memory cleanup - no restrictions."""
    try:
        logger.info("Starting memory cleanup task")
        collected = gc.collect()
        logger.info("Memory cleanup completed - collected %s objects", collected)
    except Exception as e:
        logger.error("Memory cleanup failed: %s", e)

def dbt_refresh_wrapper():
    """Simple wrapper for DBT refresh - no restrictions."""
    try:
        logger.info("Starting DBT refresh task")
        runner = get_dbt_runner()
        result = runner.try_refresh_materialized_views()

        if result.status == RefreshStatus.SUCCESS:
            logger.info("DBT refresh task completed successfully")
        elif result.status == RefreshStatus.ALREADY_RUNNING:
            logger.info("DBT refresh task skipped - already running")
        else:
            logger.warning("DBT refresh task completed with status: %s", result.status)
    except Exception:
        logger.exception("DBT refresh task failed")

