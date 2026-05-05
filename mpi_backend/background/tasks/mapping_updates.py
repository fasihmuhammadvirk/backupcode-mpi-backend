"""
Mapping Updates Task for Background Scheduler
Updates UIDI/NO matches and all mappings automatically
"""

import logging

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
            result = sync_controller._perform_uidi_update_operation()

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
            result = sync_controller._perform_full_update_operation()

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


def sync_item_mappings():
    """
    Sync item mappings from Google Sheets - nightly scheduled task.

    This function is called by the scheduler to automatically sync
    item mappings from Google Sheets. It uses the GoogleSheetSyncController
    to execute the sync operation synchronously, waiting for completion.

    Raises:
        Exception: If the sync task fails or encounters an error
    """
    try:
        logger.info("Starting nightly item mapping sync task")

        db = SessionLocal()
        try:
            sync_controller = GoogleSheetSyncController(db)
            result = sync_controller._perform_google_sheets_sync_operation()

            if result.get("success"):
                logger.info(
                    "Nightly item mapping sync task completed successfully"
                )
            else:
                error_msg = result.get("message", "Unknown error")
                logger.error(
                    f"Nightly item mapping sync failed: {error_msg}"
                )
                raise Exception(
                    result.get('message', 'Sync task failed')
                )
        finally:
            db.close()
    except Exception as e:
        logger.exception(
            f"Nightly item mapping sync task failed: {e}"
        )
        raise


