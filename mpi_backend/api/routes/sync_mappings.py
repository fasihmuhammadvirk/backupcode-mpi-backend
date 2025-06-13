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
        # Get detailed job information
        operation = status["current_operation"]
        sub_operation = status["current_sub_operation"]
        
        # Determine what's currently running
        if operation == "update_no_match_uidi":
            if sub_operation == "syncing_google_sheets":
                blocking_job = "UIDI Update (Step 1/2: Syncing Google Sheets)"
            elif sub_operation == "updating_uidi_items":
                blocking_job = "UIDI Update (Step 2/2: Updating UIDI items)"
            else:
                blocking_job = "UIDI Update"
        elif operation == "update_all":
            if sub_operation == "syncing_google_sheets":
                blocking_job = "Full Update (Step 1/2: Syncing Google Sheets)"
            elif sub_operation == "updating_all_items":
                blocking_job = "Full Update (Step 2/2: Updating all items)"
            else:
                blocking_job = "Full Update"
        elif operation == "sync":
            blocking_job = "Google Sheets Sync"
        else:
            blocking_job = operation or "Unknown operation"
        
        return SyncMappingsResponse(
            success=False,
            message=f"Cannot start sync: {blocking_job} is currently running",
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
    
    # Determine detailed current operation description
    current_operation = "No operation in progress"
    
    if status["is_running"]:
        operation = status["current_operation"]
        sub_operation = status["current_sub_operation"]
        
        # Create detailed operation descriptions based on operation and sub-operation
        if operation == "sync":
            current_operation = "Synchronizing Google Sheets"
                
        elif operation == "update_no_match_uidi":
            if sub_operation == "syncing_google_sheets":
                current_operation = "Updating No Match / UIDI Mappings (Step 1/2: Syncing Google Sheets)"
            elif sub_operation == "updating_uidi_items":
                current_operation = "Updating No Match / UIDI Mappings (Step 2/2: Updating UIDI Items)"
            else:
                current_operation = "Updating No Match / UIDI Mappings"
                
        elif operation == "update_all":
            if sub_operation == "syncing_google_sheets":
                current_operation = "Updating All Mappings (Step 1/2: Syncing Google Sheets)"
            elif sub_operation == "updating_all_items":
                current_operation = "Updating All Mappings (Step 2/2: Updating All Items)"
            else:
                current_operation = "Updating All Mappings"
        else:
            # Fallback for unknown operations
            current_operation = operation or "Unknown operation"
    
    return {
        "status": "running" if status["is_running"] else "idle",
        "current_operation": current_operation,
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
        # Get detailed job information
        operation = status["current_operation"]
        sub_operation = status["current_sub_operation"]
        
        # Determine what's currently running
        if operation == "update_no_match_uidi":
            if sub_operation == "syncing_google_sheets":
                blocking_job = "UIDI Update (Step 1/2: Syncing Google Sheets)"
            elif sub_operation == "updating_uidi_items":
                blocking_job = "UIDI Update (Step 2/2: Updating UIDI items)"
            else:
                blocking_job = "UIDI Update"
        elif operation == "update_all":
            if sub_operation == "syncing_google_sheets":
                blocking_job = "Full Update (Step 1/2: Syncing Google Sheets)"
            elif sub_operation == "updating_all_items":
                blocking_job = "Full Update (Step 2/2: Updating all items)"
            else:
                blocking_job = "Full Update"
        elif operation == "sync":
            blocking_job = "Google Sheets Sync"
        else:
            blocking_job = operation or "Unknown operation"
        
        return {
            "status": "error",
            "message": f"Cannot start UIDI update: {blocking_job} is currently running",
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
        # Get detailed job information
        operation = status["current_operation"]
        sub_operation = status["current_sub_operation"]
        
        # Determine what's currently running
        if operation == "update_no_match_uidi":
            if sub_operation == "syncing_google_sheets":
                blocking_job = "UIDI Update (Step 1/2: Syncing Google Sheets)"
            elif sub_operation == "updating_uidi_items":
                blocking_job = "UIDI Update (Step 2/2: Updating UIDI items)"
            else:
                blocking_job = "UIDI Update"
        elif operation == "update_all":
            if sub_operation == "syncing_google_sheets":
                blocking_job = "Full Update (Step 1/2: Syncing Google Sheets)"
            elif sub_operation == "updating_all_items":
                blocking_job = "Full Update (Step 2/2: Updating all items)"
            else:
                blocking_job = "Full Update"
        elif operation == "sync":
            blocking_job = "Google Sheets Sync"
        else:
            blocking_job = operation or "Unknown operation"

        return {
            "status": "error",
            "message": f"Cannot start full update: {blocking_job} is currently running",
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
