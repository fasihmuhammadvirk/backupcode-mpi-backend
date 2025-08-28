"""
Simple, Unrestricted APScheduler Configuration for MPI Backend
No restrictions, no memory management, no performance monitoring.
"""

import logging
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.pool import ThreadPoolExecutor as APSchedulerThreadPool

# Import business logic tasks
from mpi_backend.utils.quickbooks_priority import set_scheduler_instance

logger = logging.getLogger(__name__)

# Simple, unrestricted configuration
JOB_COALESCE_TIME = 1800  # 30 minutes grace period

def init_scheduler() -> BackgroundScheduler:
    """
    Create a simple, unrestricted APScheduler with no restrictions.
    """
    
    # Simple executor configuration - no restrictions
    executors = {
        'default': APSchedulerThreadPool(100),  # Large pool size, no restrictions
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
        async_email_download_wrapper,
        "interval",
        minutes=5,
        executor='default',
        id="email_download",
        name="Email Download Task (Every 5 Minutes)",
        replace_existing=True,
    )

    # Statement downloads - every 12 hours
    scheduler.add_job(
        async_statement_download_wrapper,
        "interval",
        hours=12,
        executor='default',
        id="statement_download",
        name="Statement Download Task (Every 12 Hours)",
        replace_existing=True,
    )

    # Failed invoice recovery - every hour
    scheduler.add_job(
        async_failed_invoice_recovery_wrapper,
        "interval",
        hours=1,
        executor='default',
        id="failed_invoice_recovery",
        name="Failed Invoice Recovery Task (Every 1 Hour)",
        replace_existing=True,
    )

    # Missing invoice downloads - every 5 hours
    scheduler.add_job(
        async_missing_invoice_download_wrapper,
        "interval",
        hours=5,
        executor='default',
        id="missing_invoice_download",
        name="Missing Invoice Download Task (Every 5 Hours)",
        replace_existing=True,
    )

    # =============================================================================
    # CRON JOBS - No restrictions
    # =============================================================================
    
    # UIDI/NO Match updates - Daily at 6 AM PKT (1 AM UTC)
    scheduler.add_job(
        scheduled_uidi_no_match_update,
        CronTrigger(hour=1, minute=0, timezone=pytz.utc),
        executor='default',
        id="daily_uidi_no_match_update",
        name="Daily UIDI/NO Match Update (6 AM PKT)",
        replace_existing=True,
    )

    # All Mappings update - Saturday at 8 AM PKT (3 AM UTC)
    scheduler.add_job(
        scheduled_all_mappings_update,
        CronTrigger(hour=3, minute=0, timezone=pytz.utc, day_of_week=5),
        executor='default',
        id="weekly_all_mappings_update",
        name="Weekly All Mappings Update (Saturday 8 AM PKT)",
        replace_existing=True,
    )

    # Google Sheet sync - every 2 hours
    scheduler.add_job(
        scheduled_google_sheet_sync,
        "interval",
        hours=2,
        executor='default',
        id="google_sheet_sync",
        name="Google Sheet Sync (Every 2 Hours)",
        replace_existing=True,
    )

    # Memory cleanup - every 6 hours
    scheduler.add_job(
        scheduled_memory_cleanup,
        "interval",
        hours=6,
        executor='default',
        id="memory_cleanup",
        name="Memory Cleanup (Every 6 Hours)",
        replace_existing=True,
    )

    logger.info("Scheduler initialized successfully with no restrictions")
    return scheduler

def start_scheduler():
    """Start the scheduler with no restrictions."""
    try:
        scheduler = init_scheduler()
        scheduler.start()
        logger.info("Scheduler started successfully - no restrictions applied")
        return scheduler
    except Exception as e:
        logger.error("Failed to start scheduler: %s", e)
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
        from mpi_backend.utils.quickbooks_priority import get_scheduler_instance
        return get_scheduler_instance()
    except ImportError:
        logger.warning("Could not import get_scheduler_instance")
        return None

# Simple wrapper functions for background tasks
def async_email_download_wrapper():
    """Simple wrapper for email download - no restrictions."""
    try:
        logger.info("Starting email download task")
        # Import and run the actual task
        from mpi_backend.background.tasks.email_download import download_emails
        download_emails()
        logger.info("Email download task completed")
    except Exception as e:
        logger.error("Email download task failed: %s", e)

def async_statement_download_wrapper():
    """Simple wrapper for statement download - no restrictions."""
    try:
        logger.info("Starting statement download task")
        # Import and run the actual task
        from mpi_backend.background.tasks.statement_download import download_statements
        download_statements()
        logger.info("Statement download task completed")
    except Exception as e:
        logger.error("Statement download task failed: %s", e)

def async_failed_invoice_recovery_wrapper():
    """Simple wrapper for failed invoice recovery - no restrictions."""
    try:
        logger.info("Starting failed invoice recovery task")
        # Import and run the actual task
        from mpi_backend.background.tasks.invoice_recovery import recover_failed_invoices
        recover_failed_invoices()
        logger.info("Failed invoice recovery task completed")
    except Exception as e:
        logger.error("Failed invoice recovery task failed: %s", e)

def async_missing_invoice_download_wrapper():
    """Simple wrapper for missing invoice download - no restrictions."""
    try:
        logger.info("Starting missing invoice download task")
        # Import and run the actual task
        from mpi_backend.background.tasks.missing_invoice import download_missing_invoices
        download_missing_invoices()
        logger.info("Missing invoice download task completed")
    except Exception as e:
        logger.error("Missing invoice download task failed: %s", e)

def scheduled_uidi_no_match_update():
    """Simple wrapper for UIDI/NO Match update - no restrictions."""
    try:
        logger.info("Starting UIDI/NO Match update task")
        # Import and run the actual task
        from mpi_backend.background.tasks.mapping_updates import update_uidi_no_match
        update_uidi_no_match()
        logger.info("UIDI/NO Match update task completed")
    except Exception as e:
        logger.error("UIDI/NO Match update task failed: %s", e)

def scheduled_all_mappings_update():
    """Simple wrapper for all mappings update - no restrictions."""
    try:
        logger.info("Starting all mappings update task")
        # Import and run the actual task
        from mpi_backend.background.tasks.mapping_updates import update_all_mappings
        update_all_mappings()
        logger.info("All mappings update task completed")
    except Exception as e:
        logger.error("All mappings update task failed: %s", e)

def scheduled_google_sheet_sync():
    """Simple wrapper for Google Sheet sync - no restrictions."""
    try:
        logger.info("Starting Google Sheet sync task")
        # Import and run the actual task
        from mpi_backend.background.tasks.google_sync import sync_google_sheets
        sync_google_sheets()
        logger.info("Google Sheet sync task completed")
    except Exception as e:
        logger.error("Google Sheet sync task failed: %s", e)

def scheduled_memory_cleanup():
    """Simple memory cleanup - no restrictions."""
    try:
        logger.info("Starting memory cleanup task")
        # Simple cleanup without restrictions
        import gc
        collected = gc.collect()
        logger.info("Memory cleanup completed - collected %s objects", collected)
    except Exception as e:
        logger.error("Memory cleanup failed: %s", e)

