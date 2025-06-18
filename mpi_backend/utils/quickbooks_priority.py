"""
QuickBooks Priority Control Utilities

This module contains functions for controlling background job priority
during QuickBooks exports. Separated from routes to avoid circular imports.
"""

import threading
import os
import sys
import logging
from typing import Dict, Any, Optional

# Set up logging
logger = logging.getLogger(__name__)

# Thread-safe lock for QB export coordination
_qb_export_lock = threading.Lock()
_qb_export_active = False
_qb_export_start_time = None

# Load configuration
QB_PRIORITY_MODE = os.getenv("QB_PRIORITY_MODE", "false").lower() == "true"
QB_PAUSE_BACKGROUND_JOBS = os.getenv("QB_PAUSE_BACKGROUND_JOBS", "true").lower() == "true"
QB_DEDICATED_POOL_SIZE = int(os.getenv("QB_DEDICATED_POOL_SIZE", "15"))
QB_EXPORT_BATCH_SIZE = int(os.getenv("EXPORT_BATCH_SIZE", "1000"))

def pause_background_jobs():
    """Signal to pause non-critical background jobs"""
    global _qb_export_active
    if QB_PAUSE_BACKGROUND_JOBS:
        with _qb_export_lock:
            _qb_export_active = True
        try:
            logger.info("Background jobs paused for QuickBooks priority export")
        except Exception:
            # Catch any encoding errors or other issues
            pass

def resume_background_jobs():
    """Signal to resume background jobs"""
    global _qb_export_active
    if QB_PAUSE_BACKGROUND_JOBS:
        with _qb_export_lock:
            _qb_export_active = False
        try:
            logger.info("Background jobs resumed after QuickBooks export")
        except Exception:
            # Catch any encoding errors or other issues
            pass

def is_qb_export_active() -> bool:
    """Check if QuickBooks export is currently active"""
    global _qb_export_active
    with _qb_export_lock:
        return _qb_export_active

def get_qb_priority_status() -> Dict[str, Any]:
    """Get current QuickBooks priority system status"""
    return {
        "priority_mode_enabled": QB_PRIORITY_MODE,
        "background_job_pausing": QB_PAUSE_BACKGROUND_JOBS,
        "export_currently_active": is_qb_export_active(),
        "dedicated_pool_size": QB_DEDICATED_POOL_SIZE,
        "export_batch_size": QB_EXPORT_BATCH_SIZE
    }

def is_windows() -> bool:
    """Check if running on Windows platform"""
    return sys.platform.startswith('win') 