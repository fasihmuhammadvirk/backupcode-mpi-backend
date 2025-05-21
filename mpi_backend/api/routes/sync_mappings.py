from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime

from mpi_backend.database import get_db
from mpi_backend.database.controllers import (
    GoogleSheetSyncController,
    ItemsMappingController
)
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.database.schemas import SyncMappingsResponse

import logging

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["Sync Mapping"])


@router.post("/mapping", response_model=SyncMappingsResponse)
def sync_mapping(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Manually trigger synchronization of mappings from Google Sheets.
    
    If a sync task is already running, returns a message indicating that.
    Otherwise, starts the sync process in the background.
    
    Returns:
        SyncMappingsResponse: Success status, message, and timestamp
    """
    sync_controller = GoogleSheetSyncController(db)
    status = sync_controller.get_sync_status()
    
    if status["is_running"]:
        # Convert operation name to user-friendly format
        operation_display = {
            "sync": "Sync",
            "update_invalid": "Update No Match / UIDI Mappings",
            "update_all": "Update All Mappings"
        }.get(status['current_operation'], status['current_operation'])
        
        return SyncMappingsResponse(
            success=False,
            message=f"Cannot start Sync: A {operation_display} operation is already running",
            timestamp=datetime.now()
        )
    
    # Start sync in the background
    background_tasks.add_task(GoogleSheetSyncController.execute_sync_task, db, 'sync')
    
    return SyncMappingsResponse(
        success=True,
        message="Sync task started manually",
        timestamp=datetime.now()
    )


@router.get("/status")
def sync_status(token: str = Depends(JWTBearer())):
    """
    Check the status of the sync task.
    
    Returns:
        Dict with the current status of the sync task, including which operation is running
        and when each operation was last run
    """
    status = GoogleSheetSyncController.get_sync_status()
    
    # No additional processing needed as the controller now returns all necessary information
    return status

@router.post("/update-no-match-uidi-mappings")
def update_no_match_uidi_mappings(
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer())
):
    """
    Syncs mappings from Google Sheets, then updates No Match / UIDI mappings.
    Update all items with No Match / UIDI mappings by finding matches in the
    ItemsMapping table.

    Targets items where:
    - mpi_item is exactly "no match" (case insensitive)
    - mpi_item starts with "UIDI"

    For each item, tries to find a match in the ItemsMapping table based on the
    org_item (item) and org_description (description) fields.

    Returns:
        Dict with status and count of updated items
    """
    sync_controller = GoogleSheetSyncController(db)
    status = sync_controller.get_sync_status()

    if status["is_running"]:
        # Convert operation name to user-friendly format
        operation_display = {
            "sync": "Sync",
            "update_invalid": "Update No Match / UIDI Mappings",
            "update_all": "Update All Mappings"
        }.get(status['current_operation'], status['current_operation'])
        
        return {
            "status": "error",
            "message": f"Cannot start Update No Match / UIDI Mappings: A {operation_display} operation is already running",
            "timestamp": datetime.now().isoformat()
        }

    # Start sync with update_no_match_uidi operation
    background_tasks.add_task(GoogleSheetSyncController.execute_sync_task, db, 'update_no_match_uidi')

    controller = ItemsMappingController(db)
    result = controller.update_no_match_uidi_mappings()
    
    return {
        **result,
        "timestamp": datetime.now().isoformat()
    }

@router.post("/update-all-mappings")
def update_all_mappings(
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer())
):
    """
    Syncs mappings from Google Sheets, then
    Update all invoice items by applying the latest mappings from the
    ItemsMapping table.

    This is useful for propagating mapping changes to all related invoice items
    after bulk changes to the mappings table or data migrations.

    The task runs in the background to prevent blocking the application.

    Returns:
        Dict with status message indicating the task has been started

    """
    sync_controller = GoogleSheetSyncController(db)
    status = sync_controller.get_sync_status()

    if status["is_running"]:
        # Convert operation name to user-friendly format
        operation_display = {
            "sync": "Sync",
            "update_invalid": "Update No Match / UIDI Mappings",
            "update_all": "Update All Mappings"
        }.get(status['current_operation'], status['current_operation'])
        
        return {
            "status": "error",
            "message": f"Cannot start Update All Mappings: A {operation_display} operation is already running",
            "timestamp": datetime.now().isoformat()
        }

    # Start sync with update_all operation
    background_tasks.add_task(GoogleSheetSyncController.execute_sync_task, db, 'update_all')

    # Start the update all mappings task
    background_tasks.add_task(
        ItemsMappingController.execute_update_all_mappings_task,
        db
    )

    return {
        "status": "success",
        "message": "Sync + Update all mappings task has been started in background",
        "timestamp": datetime.now().isoformat()
    }
