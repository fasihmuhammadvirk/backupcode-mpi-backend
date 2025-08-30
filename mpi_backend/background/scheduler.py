"""
UNLIMITED PERFORMANCE APScheduler Configuration for MPI Backend
No restrictions, no memory management, no performance monitoring.
Maximum speed and scalability.
"""

import logging
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.pool import ThreadPoolExecutor as APSchedulerThreadPool

# Import business logic tasks
from mpi_backend.utils.quickbooks_priority import set_scheduler_instance

logger = logging.getLogger(__name__)

# UNLIMITED PERFORMANCE - No restrictions
JOB_COALESCE_TIME = 3600  # 1 hour grace period for maximum flexibility

def init_scheduler() -> BackgroundScheduler:
    """
    Create UNLIMITED PERFORMANCE APScheduler with no restrictions.
    Maximum speed and scalability.
    """
    
    # UNLIMITED PERFORMANCE executor configuration
    executors = {
        'default': APSchedulerThreadPool(500),  # Massive pool size, no restrictions
    }
    
    # UNLIMITED PERFORMANCE job defaults
    job_defaults = {
        "coalesce": True,                    # Combine missed executions
        "max_instances": 1,                  # Only ONE instance allowed to prevent duplication
        "misfire_grace_time": JOB_COALESCE_TIME,  # Grace period for missed jobs
        "timeout": None,                     # No timeout restrictions
        "max_instances_per_job": 1,          # Only ONE instance per job to prevent duplication
    }
    
    # Create UNLIMITED PERFORMANCE scheduler
    scheduler = BackgroundScheduler(
        executors=executors,
        job_defaults=job_defaults,
        timezone=pytz.utc,
        jobstores={'default': {'type': 'memory'}},
    )

    # Register scheduler globally
    set_scheduler_instance(scheduler)

    # =============================================================================
    # BACKGROUND JOBS - UNLIMITED PERFORMANCE
    # =============================================================================
    
    # Email downloads - every 2 minutes for maximum responsiveness
    scheduler.add_job(
        async_email_download_wrapper,
        "interval",
        minutes=2,
        executor='default',
        id="email_download",
        name="Email Download Task (Every 2 Minutes) - UNLIMITED PERFORMANCE",
        replace_existing=True,
    )

    # Statement downloads - every 6 hours for maximum responsiveness
    scheduler.add_job(
        async_statement_download_wrapper,
        "interval",
        hours=6,
        executor='default',
        id="statement_download",
        name="Statement Download Task (Every 6 Hours) - UNLIMITED PERFORMANCE",
        replace_existing=True,
    )

    # Failed invoice recovery - every 30 minutes for maximum responsiveness
    scheduler.add_job(
        async_failed_invoice_recovery_wrapper,
        "interval",
        minutes=30,
        executor='default',
        id="failed_invoice_recovery",
        name="Failed Invoice Recovery Task (Every 30 Minutes) - UNLIMITED PERFORMANCE",
        replace_existing=True,
    )

    # Missing invoice downloads - every 2 hours for maximum responsiveness
    scheduler.add_job(
        async_missing_invoice_download_wrapper,
        "interval",
        hours=2,
        executor='default',
        id="missing_invoice_download",
        name="Missing Invoice Download Task (Every 2 Hours) - UNLIMITED PERFORMANCE",
        replace_existing=True,
    )

    # =============================================================================
    # CRON JOBS - UNLIMITED PERFORMANCE
    # =============================================================================
    
    # Daily mapping updates - every day at 2 AM
    scheduler.add_job(
        scheduled_all_mappings_update,
        "cron",
        hour=2,
        minute=0,
        executor='default',
        id="daily_mappings_update",
        name="Daily All Mappings Update - UNLIMITED PERFORMANCE",
        replace_existing=True,
    )

    # Weekly Google Sheet sync - every Sunday at 3 AM
    scheduler.add_job(
        scheduled_google_sheet_sync,
        "cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        executor='default',
        id="weekly_google_sync",
        name="Weekly Google Sheet Sync - UNLIMITED PERFORMANCE",
        replace_existing=True,
    )

    # Memory cleanup - every 4 hours (minimal impact)
    scheduler.add_job(
        scheduled_memory_cleanup,
        "interval",
        hours=4,
        executor='default',
        id="memory_cleanup",
        name="Memory Cleanup Task (Every 4 Hours) - UNLIMITED PERFORMANCE",
        replace_existing=True,
    )

    # =============================================================================
    # START SCHEDULER - UNLIMITED PERFORMANCE
    # =============================================================================
    
    try:
        scheduler.start()
        logger.info("UNLIMITED PERFORMANCE Scheduler started successfully")
        logger.info("Scheduler initialized with unlimited performance")
        logger.info("All restrictions removed for maximum speed and scalability")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        raise

    return scheduler


def get_scheduler_instance():
    """Get the global scheduler instance."""
    try:
        from mpi_backend.utils.quickbooks_priority import get_scheduler_instance
        return get_scheduler_instance()
    except ImportError:
        logger.warning("Could not import get_scheduler_instance")
        return None

# UNLIMITED PERFORMANCE wrapper functions for background tasks
def async_email_download_wrapper():
    """UNLIMITED PERFORMANCE wrapper for email download."""
    try:
        logger.info("Starting email download task - UNLIMITED PERFORMANCE")
        # Import and run the actual task
        from mpi_backend.background.tasks.email_download import download_emails
        download_emails()
        logger.info("Email download task completed - UNLIMITED PERFORMANCE")
    except Exception as e:
        logger.error("Email download task failed: %s", e)

def async_statement_download_wrapper():
    """UNLIMITED PERFORMANCE wrapper for statement download."""
    try:
        logger.info("Starting statement download task - UNLIMITED PERFORMANCE")
        # Import and run the actual task
        from mpi_backend.background.tasks.statement_download import download_statements
        download_statements()
        logger.info("Statement download task completed - UNLIMITED PERFORMANCE")
    except Exception as e:
        logger.error("Statement download task failed: %s", e)

def async_failed_invoice_recovery_wrapper():
    """UNLIMITED PERFORMANCE wrapper for failed invoice recovery."""
    try:
        logger.info("Starting failed invoice recovery task - UNLIMITED PERFORMANCE")
        # Import and run the actual task
        from mpi_backend.background.tasks.invoice_recovery import recover_failed_invoices
        recover_failed_invoices()
        logger.info("Failed invoice recovery task completed - UNLIMITED PERFORMANCE")
    except Exception as e:
        logger.error("Failed invoice recovery task failed: %s", e)

def async_missing_invoice_download_wrapper():
    """UNLIMITED PERFORMANCE wrapper for missing invoice download."""
    try:
        logger.info("Starting missing invoice download task - UNLIMITED PERFORMANCE")
        # Import and run the actual task
        from mpi_backend.background.tasks.missing_invoice import download_missing_invoices
        download_missing_invoices()
        logger.info("Missing invoice download task completed - UNLIMITED PERFORMANCE")
    except Exception as e:
        logger.error("Missing invoice download task failed: %s", e)

def scheduled_uidi_no_match_update():
    """UNLIMITED PERFORMANCE wrapper for UIDI/NO Match update."""
    try:
        logger.info("Starting UIDI/NO Match update task - UNLIMITED PERFORMANCE")
        # Import and run the actual task
        from mpi_backend.background.tasks.mapping_updates import update_uidi_no_match
        update_uidi_no_match()
        logger.info("UIDI/NO Match update task completed - UNLIMITED PERFORMANCE")
    except Exception as e:
        logger.error("UIDI/NO Match update task failed: %s", e)

def scheduled_all_mappings_update():
    """UNLIMITED PERFORMANCE wrapper for all mappings update."""
    try:
        logger.info("Starting all mappings update task - UNLIMITED PERFORMANCE")
        # Import and run the actual task
        from mpi_backend.background.tasks.mapping_updates import update_all_mappings
        update_all_mappings()
        logger.info("All mappings update task completed - UNLIMITED PERFORMANCE")
    except Exception as e:
        logger.error("All mappings update task failed: %s", e)

def scheduled_google_sheet_sync():
    """UNLIMITED PERFORMANCE wrapper for Google Sheet sync."""
    try:
        logger.info("Starting Google Sheet sync task - UNLIMITED PERFORMANCE")
        # Import and run the actual task
        from mpi_backend.background.tasks.google_sync import sync_google_sheets
        sync_google_sheets()
        logger.info("Google Sheet sync task completed - UNLIMITED PERFORMANCE")
    except Exception as e:
        logger.error("Google Sheet sync task failed: %s", e)

def scheduled_memory_cleanup():
    """UNLIMITED PERFORMANCE memory cleanup."""
    try:
        logger.info("Starting memory cleanup task - UNLIMITED PERFORMANCE")
        # Simple cleanup without restrictions
        import gc
        collected = gc.collect()
        logger.info("Memory cleanup completed - collected %s objects", collected)
    except Exception as e:
        logger.error("Memory cleanup failed: %s", e)

