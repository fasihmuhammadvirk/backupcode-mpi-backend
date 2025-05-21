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
        # Operation display names mapping
        operation_display = {
            "sync": "Synchronization",
            "update_no_match_uidi": "No Match / UIDI Update",
            "update_all": "Full Update"
        }.get(status['current_operation'], status['current_operation'])
        
        return SyncMappingsResponse(
            success=False,
            message=f"Cannot start operation: {operation_display} is already in progress",
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
def sync_status(
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Check the status of synchronization tasks.
    
    Returns:
        dict: Current sync status including running operations and timestamps
    """
    sync_controller = GoogleSheetSyncController(db)
    status = sync_controller.get_sync_status()
    
    # Format the response with clear status information
    operation_display = {
        None: "No operation in progress",
        "sync": "Synchronizing data",
        "update_no_match_uidi": "Updating No Match / UIDI Mappings",
        "update_all": "Updating All Mappings"
    }
    
    return {
        "status": "running" if status["is_running"] else "idle",
        "current_operation": operation_display.get(status["current_operation"], status["current_operation"]),
        "last_sync_time": status["last_sync_time"],
        "last_no_match_uidi_update": status["last_update_no_match_uidi_time"],
        "last_full_update": status["last_update_all_time"]
    }

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
    - mpi_item is None or empty

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
            "sync": "Synchronization",
            "update_no_match_uidi": "No Match / UIDI Update",
            "update_all": "Full Update"
        }.get(status['current_operation'], status['current_operation'])
        
        return {
            "status": "error",
            "message": f"Cannot start operation: {operation_display} is already in progress",
            "timestamp": datetime.now().isoformat()
        }

    try:
        # Start sync with update_no_match_uidi operation
        background_tasks.add_task(
            GoogleSheetSyncController.execute_sync_task, 
            db, 
            'update_no_match_uidi'
        )
        
        return {
            "status": "success",
            "message": "No Match / UIDI update task has been started in the background",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to start No Match / UIDI update: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to start No Match / UIDI update: {str(e)}",
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
            "sync": "Synchronization",
            "update_no_match_uidi": "No Match / UIDI Update",
            "update_all": "Full Update"
        }.get(status['current_operation'], status['current_operation'])
        
        return {
            "status": "error",
            "message": f"Cannot start operation: {operation_display} is already in progress",
            "timestamp": datetime.now().isoformat()
        }

    try:
        # Start sync with update_all operation
        background_tasks.add_task(
            GoogleSheetSyncController.execute_sync_task,
            db,
            'update_all'
        )

        return {
            "status": "success",
            "message": "Full update task has been started in the background",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to start full update: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to start full update: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }
