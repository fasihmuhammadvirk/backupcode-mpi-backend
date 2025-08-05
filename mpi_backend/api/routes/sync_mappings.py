from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime

from mpi_backend.database import get_db
from mpi_backend.database.controllers import GoogleSheetSyncController
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
    Manually trigger enhanced synchronization of mappings from Google Sheets.
    
    **Summary:**
        Initiates a manual synchronization process to update item mappings
        from Google Sheets. This endpoint provides enhanced synchronization
        with better handling of temporary and permanent mappings. If a sync
        task is already running, it returns a detailed status message.
        
    **Background Tasks:**
        - **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing
        
    **Authentication:**
        - **token** (`str`): JWT Bearer token required for access
        
    **Returns:**
        - **SyncMappingsResponse**: Response model with success status, message, and timestamp
        
    **Response Example - Success:**
    ```json
    {
        "success": true,
        "message": "Sync task started manually",
        "timestamp": "2024-12-19T14:30:25.123456"
    }
    ```
    
    **Response Example - Already Running:**
    ```json
    {
        "success": false,
        "message": "Cannot start sync: Google Sheets Sync is currently running",
        "timestamp": "2024-12-19T14:30:25.123456"
    }
    ```
    
    **Process Flow:**
        1. Checks current sync status
        2. If sync is running, returns detailed blocking job information
        3. If no sync is running, starts enhanced sync in background
        4. Returns immediate response with task status
        
    **Sync Operations:**
        - **Google Sheets Sync**: Basic synchronization from Google Sheets
        - **UIDI Update**: Updates No Match / UIDI mappings (3-step process)
        - **Full Update**: Updates all mappings (3-step process)
        
    **Blocking Job Detection:**
        - Detects currently running sync operations
        - Provides detailed step-by-step progress information
        - Prevents multiple sync operations from running simultaneously
        - Returns specific blocking job descriptions
        
    **Background Processing:**
        - Uses GoogleSheetSyncController for enhanced sync
        - Runs in background to prevent API blocking
        - Provides detailed operation tracking
        - Handles temporary and permanent mapping updates
        
    **Error Codes:**
        - **401**: Unauthorized (invalid or missing token)
        - **500**: Database error or sync controller failure
        
    **Notes:**
        - Only one sync operation can run at a time
        - Background processing prevents API timeout
        - Enhanced sync provides better mapping accuracy
        - Detailed status reporting for monitoring
        - Automatic conflict resolution for concurrent requests
    """
    # Use enhanced sync controller for better temporary/permanent mapping handling
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

    # Start enhanced sync in the background using the worker method
    background_tasks.add_task(
        GoogleSheetSyncController._execute_sync_task_worker, db, 'sync')

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
    
    **Summary:**
        Retrieves the current status of all synchronization operations
        including running tasks, completed operations, and timestamps.
        Provides detailed information about the current operation
        and its progress through multi-step processes.
        
    **Authentication:**
        - **token** (`str`): JWT Bearer token required for access
        
    **Returns:**
        - **dict**: Current sync status with detailed operation information
        
    **Response Example - Idle:**
    ```json
    {
        "status": "idle",
        "current_operation": "No operation in progress",
        "last_sync_time": "2024-12-19T14:30:25.123456",
        "last_no_match_uidi_update": "2024-12-19T14:25:10.123456",
        "last_full_update": "2024-12-19T14:20:15.123456"
    }
    ```
    
    **Response Example - Running:**
    ```json
    {
        "status": "running",
        "current_operation": "Updating No Match / UIDI Mappings (Step 2/3: Syncing Temporary Mappings)",
        "last_sync_time": "2024-12-19T14:30:25.123456",
        "last_no_match_uidi_update": "2024-12-19T14:25:10.123456",
        "last_full_update": "2024-12-19T14:20:15.123456"
    }
    ```
    
    **Response Fields:**
        - **status** (`str`): "running" or "idle"
        - **current_operation** (`str`): Detailed description of current operation
        - **last_sync_time** (`str`): Timestamp of last basic sync
        - **last_no_match_uidi_update** (`str`): Timestamp of last UIDI update
        - **last_full_update** (`str`): Timestamp of last full update
        
    **Operation Types:**
        - **Google Sheets Sync**: Basic synchronization from Google Sheets
        - **UIDI Update**: 3-step process for No Match / UIDI mappings
        - **Full Update**: 3-step process for all mappings
        
    **Step-by-Step Progress:**
        - **Step 1**: Syncing Google Sheets
        - **Step 2**: Syncing Temporary Mappings
        - **Step 3**: Updating Items
        
    **Status Detection:**
        - Real-time operation status checking
        - Detailed sub-operation tracking
        - Progress indication for multi-step processes
        - Historical timestamp tracking
        
    **Error Codes:**
        - **401**: Unauthorized (invalid or missing token)
        - **500**: Database error or sync controller failure
        
    **Use Cases:**
        - Monitoring sync progress
        - Checking if sync is available
        - Tracking operation history
        - Frontend status display
        
    **Notes:**
        - Provides real-time status information
        - Tracks multiple operation types
        - Includes historical timestamps
        - Detailed progress reporting for long-running operations
        - Useful for frontend progress indicators
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
                current_operation = "Updating No Match / UIDI Mappings (Step 1/3: Syncing Google Sheets)"
            elif sub_operation == "syncing_temporary_mappings":
                current_operation = "Updating No Match / UIDI Mappings (Step 2/3: Syncing Temporary Mappings)"
            elif sub_operation == "updating_uidi_items":
                current_operation = "Updating No Match / UIDI Mappings (Step 3/3: Updating UIDI Items)"
            else:
                current_operation = "Updating No Match / UIDI Mappings"

        elif operation == "update_all":
            if sub_operation == "syncing_google_sheets":
                current_operation = "Updating All Mappings (Step 1/3: Syncing Google Sheets)"
            elif sub_operation == "syncing_temporary_mappings":
                current_operation = "Updating All Mappings (Step 2/3: Syncing Temporary Mappings)"
            elif sub_operation == "updating_all_items":
                current_operation = "Updating All Mappings (Step 3/3: Updating All Items)"
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
    Update No Match and UIDI item mappings from Google Sheets.
    
    **Summary:**
        Initiates a specialized synchronization process that targets items
        with "No Match" or UIDI mappings. This 3-step process syncs data
        from Google Sheets and then updates specific item mappings to improve
        data quality and mapping accuracy.
        
    **Background Tasks:**
        - **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing
        
    **Authentication:**
        - **token** (`str`): JWT Bearer token required for access
        
    **Returns:**
        - **dict**: Response with status, message, and timestamp
        
    **Response Example - Success:**
    ```json
    {
        "status": "success",
        "message": "No Match / UIDI update task has been started in the background",
        "timestamp": "2024-12-19T14:30:25.123456"
    }
    ```
    
    **Response Example - Already Running:**
    ```json
    {
        "status": "error",
        "message": "Cannot start UIDI update: UIDI Update (Step 2/3: Syncing Temporary Mappings) is currently running",
        "timestamp": "2024-12-19T14:30:25.123456"
    }
    ```
    
    **Target Items:**
        - **No Match Items**: Items where mpi_item is "no match" (case insensitive)
        - **UIDI Items**: Items where mpi_item starts with "UIDI"
        - **Empty Items**: Items where mpi_item is None or empty
        
    **3-Step Process:**
        1. **Step 1**: Sync Google Sheets data
        2. **Step 2**: Sync temporary mappings
        3. **Step 3**: Update UIDI items with new mappings
        
    **Mapping Logic:**
        - Searches ItemsMapping table for matches
        - Uses org_item (item) and org_description (description) fields
        - Applies enhanced mapping algorithms
        - Updates both temporary and permanent mappings
        
    **Process Flow:**
        1. Checks if any sync operation is currently running
        2. If running, returns detailed blocking job information
        3. If available, starts UIDI update in background
        4. Returns immediate response with task status
        
    **Background Processing:**
        - Runs in background to prevent API blocking
        - Uses GoogleSheetSyncController for enhanced processing
        - Provides detailed operation tracking
        - Handles large datasets efficiently
        
    **Error Codes:**
        - **401**: Unauthorized (invalid or missing token)
        - **500**: Database error or sync controller failure
        
    **Use Cases:**
        - Improving mapping accuracy for problematic items
        - Bulk updates of No Match items
        - UIDI item classification updates
        - Data quality improvement initiatives
        
    **Notes:**
        - Only one sync operation can run at a time
        - Background processing prevents API timeout
        - Enhanced mapping algorithms for better accuracy
        - Detailed progress tracking for long-running operations
        - Automatic conflict resolution for concurrent requests
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
                blocking_job = "UIDI Update (Step 1/3: Syncing Google Sheets)"
            elif sub_operation == "syncing_temporary_mappings":
                blocking_job = "UIDI Update (Step 2/3: Syncing Temporary Mappings)"
            elif sub_operation == "updating_uidi_items":
                blocking_job = "UIDI Update (Step 3/3: Updating UIDI items)"
            else:
                blocking_job = "UIDI Update"
        elif operation == "update_all":
            if sub_operation == "syncing_google_sheets":
                blocking_job = "Full Update (Step 1/3: Syncing Google Sheets)"
            elif sub_operation == "syncing_temporary_mappings":
                blocking_job = "Full Update (Step 2/3: Syncing Temporary Mappings)"
            elif sub_operation == "updating_all_items":
                blocking_job = "Full Update (Step 3/3: Updating all items)"
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
        # Start sync with update_no_match_uidi operation using the worker method
        background_tasks.add_task(
            GoogleSheetSyncController._execute_sync_task_worker,
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
    Update all invoice items with latest mappings from Google Sheets.
    
    **Summary:**
        Initiates a comprehensive synchronization process that updates all
        invoice items with the latest mappings from Google Sheets. This
        3-step process is useful for propagating mapping changes across
        the entire system after bulk updates or data migrations.
        
    **Background Tasks:**
        - **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing
        
    **Authentication:**
        - **token** (`str`): JWT Bearer token required for access
        
    **Returns:**
        - **dict**: Response with status, message, and timestamp
        
    **Response Example - Success:**
    ```json
    {
        "status": "success",
        "message": "Full update task has been started in the background",
        "timestamp": "2024-12-19T14:30:25.123456"
    }
    ```
    
    **Response Example - Already Running:**
    ```json
    {
        "status": "error",
        "message": "Cannot start full update: Full Update (Step 2/3: Syncing Temporary Mappings) is currently running",
        "timestamp": "2024-12-19T14:30:25.123456"
    }
    ```
    
    **3-Step Process:**
        1. **Step 1**: Sync Google Sheets data
        2. **Step 2**: Sync temporary mappings
        3. **Step 3**: Update all items with new mappings
        
    **Scope:**
        - **All Invoice Items**: Updates every invoice item in the system
        - **Comprehensive Coverage**: Ensures all items have latest mappings
        - **Bulk Processing**: Handles large datasets efficiently
        - **Data Consistency**: Maintains mapping consistency across system
        
    **Use Cases:**
        - After bulk mapping table changes
        - Data migration completion
        - System-wide mapping updates
        - Data quality improvement initiatives
        - Mapping table restructuring
        
    **Process Flow:**
        1. Checks if any sync operation is currently running
        2. If running, returns detailed blocking job information
        3. If available, starts full update in background
        4. Returns immediate response with task status
        
    **Background Processing:**
        - Runs in background to prevent API blocking
        - Uses GoogleSheetSyncController for enhanced processing
        - Provides detailed operation tracking
        - Handles large datasets efficiently
        
    **Performance Considerations:**
        - May take significant time for large datasets
        - Processes all invoice items in the system
        - Uses optimized batch processing
        - Provides progress tracking for long operations
        
    **Error Codes:**
        - **401**: Unauthorized (invalid or missing token)
        - **500**: Database error or sync controller failure
        
    **Notes:**
        - Only one sync operation can run at a time
        - Background processing prevents API timeout
        - Comprehensive system-wide update
        - Detailed progress tracking for long-running operations
        - Automatic conflict resolution for concurrent requests
        - Useful for system maintenance and data migration
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
                blocking_job = "UIDI Update (Step 1/3: Syncing Google Sheets)"
            elif sub_operation == "syncing_temporary_mappings":
                blocking_job = "UIDI Update (Step 2/3: Syncing Temporary Mappings)"
            elif sub_operation == "updating_uidi_items":
                blocking_job = "UIDI Update (Step 3/3: Updating UIDI items)"
            else:
                blocking_job = "UIDI Update"
        elif operation == "update_all":
            if sub_operation == "syncing_google_sheets":
                blocking_job = "Full Update (Step 1/3: Syncing Google Sheets)"
            elif sub_operation == "syncing_temporary_mappings":
                blocking_job = "Full Update (Step 2/3: Syncing Temporary Mappings)"
            elif sub_operation == "updating_all_items":
                blocking_job = "Full Update (Step 3/3: Updating all items)"
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
        # Start sync with update_all operation using the worker method
        background_tasks.add_task(
            GoogleSheetSyncController._execute_sync_task_worker,
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
