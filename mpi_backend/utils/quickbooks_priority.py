"""
ENHANCED QuickBooks Priority Control Utilities

This module provides enterprise-grade priority control for QuickBooks
operations, specifically giving ABSOLUTE PRIORITY to migrate-all operations
over all background tasks. Separated from routes to avoid circular imports.
"""

import threading
import os
import logging
from typing import Dict, Any
from apscheduler.schedulers.background import BackgroundScheduler

# Set up logging
logger = logging.getLogger(__name__)

# ENHANCED: Thread-safe priority coordination system
_qb_export_lock = threading.Lock()
_qb_export_active = False
_migrate_all_active = False  # NEW: Specific tracking for migrate-all
_scheduler_instance = None   # NEW: Global scheduler reference

# Load configuration
QB_PRIORITY_MODE = os.getenv("QB_PRIORITY_MODE", "true").lower() == "true"
QB_PAUSE_BACKGROUND_JOBS = os.getenv(
    "QB_PAUSE_BACKGROUND_JOBS", "true").lower() == "true"
QB_DEDICATED_POOL_SIZE = int(os.getenv("QB_DEDICATED_POOL_SIZE", "15"))
QB_EXPORT_BATCH_SIZE = int(os.getenv("EXPORT_BATCH_SIZE", "1000"))

# NEW: Scheduler jobs that will be paused during migrate-all
BACKGROUND_JOB_IDS = [
    "email_download",
    "statement_download", 
    "google_sheets_sync",
    "update_all_mappings_daily"
]


def set_scheduler_instance(scheduler: BackgroundScheduler):
    """Set the global scheduler instance for dynamic job control"""
    global _scheduler_instance
    _scheduler_instance = scheduler
    logger.info("Scheduler instance registered for dynamic job control")


def pause_background_jobs():
    """ENHANCED: Signal to pause non-critical background jobs"""
    global _qb_export_active
    if QB_PAUSE_BACKGROUND_JOBS:
        with _qb_export_lock:
            _qb_export_active = True
        logger.info(
            "⏸️  Background jobs paused for QuickBooks priority export")


def pause_all_background_jobs_for_migrate_all():
    """ABSOLUTE PRIORITY: Pause ALL background jobs for migrate-all 
    operation"""
    global _qb_export_active, _migrate_all_active, _scheduler_instance
    
    if not QB_PAUSE_BACKGROUND_JOBS:
        return
        
    with _qb_export_lock:
        _qb_export_active = True
        _migrate_all_active = True
        
        # ENHANCED: Dynamically pause scheduler jobs if available
        if _scheduler_instance:
            paused_jobs = []
            for job_id in BACKGROUND_JOB_IDS:
                try:
                    job = _scheduler_instance.get_job(job_id)
                    if job:
                        _scheduler_instance.pause_job(job_id)
                        paused_jobs.append(job_id)
                except Exception as e:
                    logger.warning(f"Could not pause job {job_id}: {e}")
            
            if paused_jobs:
                logger.info(
                    f"ABSOLUTE PRIORITY: Paused scheduler jobs: "
                    f"{paused_jobs}")
            else:
                logger.info(
                    "ABSOLUTE PRIORITY: All background jobs paused via "
                    "signal")
        else:
            logger.info(
                "ABSOLUTE PRIORITY: All background jobs paused via signal")


def resume_background_jobs():
    """ENHANCED: Signal to resume background jobs"""
    global _qb_export_active
    if QB_PAUSE_BACKGROUND_JOBS:
        with _qb_export_lock:
            _qb_export_active = False
        logger.info("Background jobs resumed after QuickBooks export")


def resume_all_background_jobs_from_migrate_all():
    """ABSOLUTE PRIORITY: Resume ALL background jobs after migrate-all
    operation"""
    global _qb_export_active, _migrate_all_active, _scheduler_instance
    
    if not QB_PAUSE_BACKGROUND_JOBS:
        return
        
    with _qb_export_lock:
        _qb_export_active = False
        _migrate_all_active = False
        
        # ENHANCED: Dynamically resume scheduler jobs if available
        if _scheduler_instance:
            resumed_jobs = []
            for job_id in BACKGROUND_JOB_IDS:
                try:
                    job = _scheduler_instance.get_job(job_id)
                    if job:
                        _scheduler_instance.resume_job(job_id)
                        resumed_jobs.append(job_id)
                except Exception as e:
                    logger.warning(f"Could not resume job {job_id}: {e}")
            
            if resumed_jobs:
                logger.info(
                    f"PRIORITY RELEASED: Resumed scheduler jobs: "
                    f"{resumed_jobs}")
            else:
                logger.info(
                    "PRIORITY RELEASED: All background jobs resumed via "
                    "signal")
        else:
            logger.info(
                "PRIORITY RELEASED: All background jobs resumed via "
                "signal")


def is_qb_export_active() -> bool:
    """Check if QuickBooks export is currently active"""
    global _qb_export_active
    with _qb_export_lock:
        return _qb_export_active


def is_migrate_all_active() -> bool:
    """NEW: Check if migrate-all operation is currently active (highest
    priority)"""
    global _migrate_all_active
    with _qb_export_lock:
        return _migrate_all_active


def get_qb_priority_status() -> Dict[str, Any]:
    """ENHANCED: Get current QuickBooks priority system status"""
    return {
        "priority_mode_enabled": QB_PRIORITY_MODE,
        "background_job_pausing": QB_PAUSE_BACKGROUND_JOBS,
        "export_currently_active": is_qb_export_active(),
        "migrate_all_active": is_migrate_all_active(),  # NEW
        "dedicated_pool_size": QB_DEDICATED_POOL_SIZE,
        "export_batch_size": QB_EXPORT_BATCH_SIZE,
        "scheduler_available": _scheduler_instance is not None,  # NEW
        "pauseable_jobs": BACKGROUND_JOB_IDS  # NEW
    } 