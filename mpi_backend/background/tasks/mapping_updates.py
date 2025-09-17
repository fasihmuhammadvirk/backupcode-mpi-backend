"""
Mapping Updates Task for Background Scheduler
Updates UIDI/NO matches and all mappings automatically
"""

import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from mpi_backend.database import SessionLocal
from mpi_backend.database.controllers.GoogleSheetSyncController import (
    GoogleSheetSyncController
)

logger = logging.getLogger(__name__)


def update_uidi_no_match():
    """Update UIDI/NO matches using the existing
    GoogleSheetSyncController"""
    try:
        logger.info("Starting UIDI/NO match update task")
        
        # Use database session
        db = SessionLocal()
        try:
            sync_controller = GoogleSheetSyncController(db)
            result = sync_controller.perform_uidi_update_operation()

            if result.get("success"):
                logger.info("UIDI/NO match update task completed successfully")
            else:
                error_msg = result.get('message', 'Unknown error')
                logger.error(f"UIDI/NO match update failed: {error_msg}")
                raise Exception(result.get('message', 'UIDI update failed'))

        finally:
            db.close()

    except Exception as e:
        logger.error(f"UIDI/NO match update task failed: {e}")
        raise



def update_all_mappings():
    """Update all mappings using the existing
    GoogleSheetSyncController"""
    try:
        logger.info("Starting all mappings update task")
        
        # Use database session
        db = SessionLocal()
        try:
            sync_controller = GoogleSheetSyncController(db)
            result = sync_controller.perform_all_mappings_update_operation()

            if result.get("success"):
                logger.info("All mappings update task completed successfully")
            else:
                error_msg = result.get('message', 'Unknown error')
                logger.error(f"All mappings update failed: {error_msg}")
                raise Exception(result.get('message', 'All mappings update failed'))

        finally:
            db.close()

    except Exception as e:
        logger.error(f"All mappings update task failed: {e}")
        raise


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
