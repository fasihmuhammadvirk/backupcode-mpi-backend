#!/usr/bin/env python3
"""
Enhanced Google Sheet Sync Controller - Fixed version with proper temporary/permanent mapping handling.

This controller provides enhanced synchronization functionality with proper validation
and categorization of temporary vs permanent mappings.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from mpi_backend.utils.google_sheets_extractors.google_sheets_mapping_extractor import (
    EnhancedGoogleSheetDataExtractor
)
from mpi_backend.utils.google_sheets_extractors.temporary_mapping_detector import (
    TemporaryMappingExtractor
)
from mpi_backend.utils.mapping_sync_utils.temporary_mapping_sync_handler import (
    TemporaryMappingSync
)
from mpi_backend.database.controllers.ItemsMappingController import (
    ItemsMappingController
)
from mpi_backend.database.controllers.TemporaryItemMappingController import (
    TemporaryItemMappingController
)
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID,
    GOOGLE_API_KEY,
    DEFAULT_OUTPUT_FILE,
    SKIP_SHEETS,
    MAPPING_CONFIG
)
from mpi_backend.utils.mapping_stats_manager import MappingStatsManager

# Set up logging
logger = logging.getLogger(__name__)


class GoogleSheetSyncController:
    """Enhanced controller for synchronizing data from Google Sheets to the database."""

    # Class level variables to track sync status
    _sync_task_running = False
    _last_sync_time = None

    # Track which operation is running and last run times
    _current_operation = None  # Can be 'sync', 'update_no_match_uidi', 'update_all'
    _current_sub_operation = None  # Track specific job within operation
    _last_update_no_match_uidi_time = None
    _last_update_all_time = None
    _last_update_invalid_time = None  # For backward compatibility

    # Percentage tracking for background jobs
    _current_percentage = 0
    _total_steps = 0
    _current_step = 0
    _step_progress = 0  # Progress within current step (0-100)
    _step_weight = 0    # Weight of current step in overall progress
    
    # Real-time progress tracking
    _total_items_to_process = 0
    _items_processed = 0
    _last_progress_update = None

    # Thread pool for background operations
    _executor = ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="sync_worker")

    def __init__(self, db: Session):
        """
        Initialize the EnhancedGoogleSheetSyncController.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.mapping_controller = ItemsMappingController(db)
        self.temp_mapping_controller = TemporaryItemMappingController(db)
        self.temp_mapping_sync = TemporaryMappingSync(db)
        self.logger = logging.getLogger(f"{__name__}")

    @classmethod
    def execute_sync_task(cls, db: Session = None, operation: str = 'sync'):
        """
        Execute a sync task with proper error handling and status tracking.
        This method now runs asynchronously to prevent blocking the application.

        Args:
            db: Database session
            operation: Type of operation to perform
        """
        if cls._sync_task_running:
            logger.warning(
                f"Sync task already running: {cls._current_operation}")
            return {
                "success": False,
                "message": f"Sync task already running: {cls._current_operation}",
                "timestamp": datetime.now(),
                "operation": operation
            }

        # Set status immediately to prevent blocking
        cls._sync_task_running = True
        cls._current_operation = operation
        cls._current_sub_operation = None

        # Return immediately with status, actual work happens in background
        logger.info(f"Sync task started: {operation}")
        return {
            "success": True,
            "message": f"Sync task started: {operation}",
            "timestamp": datetime.now(),
            "operation": operation
        }

    @classmethod
    def _execute_sync_task_worker(cls, db: Session = None, operation: str = 'sync'):
        """
        Internal worker method that actually performs the sync task.
        This runs in a separate thread to prevent blocking the application.
        """
        def _run_sync_task():
            """Inner function that runs the actual sync task in a separate thread."""
            try:
                # Set the operation status at the beginning
                cls._sync_task_running = True
                cls._current_operation = operation
                cls._current_sub_operation = "starting"
                
                # Initialize progress tracking based on operation type
                if operation == 'sync':
                    cls._reset_progress()
                    cls._total_steps = 3  # Google Sheets sync has 3 steps
                elif operation == 'update_no_match_uidi':
                    cls._reset_progress()
                    cls._total_steps = 3  # UIDI update has 3 steps
                elif operation == 'update_all':
                    cls._reset_progress()
                    cls._total_steps = 3  # Full update has 3 steps
                else:
                    cls._reset_progress()
                    cls._total_steps = 1  # Default to 1 step

                # Create a new database session for this thread
                from mpi_backend.database import SessionLocal
                thread_db = SessionLocal()

                try:
                    controller = cls(thread_db)
                    result = controller.perform_sync_task(operation)
                    logger.info(f"Sync task completed: {operation}")
                    return result
                finally:
                    thread_db.close()

            except Exception as e:
                logger.error(f"Sync task failed: {str(e)}")
                return {
                    "success": False,
                    "message": f"Sync task failed: {str(e)}",
                    "timestamp": datetime.now(),
                    "operation": operation
                }
            finally:
                cls._sync_task_running = False
                cls._current_operation = None
                cls._current_sub_operation = None
                cls._reset_progress()  # Reset progress when job completes

        # Submit the task to the thread pool and return immediately
        future = cls._executor.submit(_run_sync_task)

        # Return immediately - the task will run in the background
        return {
            "success": True,
            "message": f"Sync task submitted to background thread: {operation}",
            "timestamp": datetime.now(),
            "operation": operation
        }

    @classmethod
    def shutdown(cls):
        """
        Shutdown the thread pool executor gracefully.
        This should be called when the application is shutting down.
        """
        try:
            cls._executor.shutdown(wait=True, timeout=30)
            logger.info("Thread pool executor shutdown completed")
        except Exception as e:
            logger.error(f"Error shutting down thread pool executor: {str(e)}")

    @classmethod
    def get_sync_status(cls) -> Dict[str, Any]:
        """
        Get the current sync status.

        Returns:
            Dictionary with sync status information
        """
        # Load persisted timestamps from stats file as fallback so values survive restarts
        try:
            stats_manager = MappingStatsManager()
            item_stats = stats_manager.get_item_mapping_stats()  # contains last_sync_time
            overall_stats = stats_manager.get_overall_stats()    # contains last_uidi_update, last_all_update
        except Exception:
            item_stats, overall_stats = {}, {}

        def _normalize_time(value):
            # Return ISO string or None
            if not value:
                return None
            try:
                # If it's already a string (from JSON), return as-is
                if isinstance(value, str):
                    return value
                # If it's a datetime, convert to isoformat
                return value.isoformat()
            except Exception:
                return str(value)

        last_sync_time = cls._last_sync_time or item_stats.get("last_sync_time")
        last_uidi_time = cls._last_update_no_match_uidi_time or overall_stats.get("last_uidi_update")
        last_all_time = cls._last_update_all_time or overall_stats.get("last_all_update")

        return {
            "is_running": cls._sync_task_running,
            "current_operation": cls._current_operation,
            "current_sub_operation": cls._current_sub_operation,
            "last_sync_time": _normalize_time(last_sync_time),
            "last_update_no_match_uidi_time": _normalize_time(last_uidi_time),
            "last_update_all_time": _normalize_time(last_all_time),
            "last_update_invalid_time": _normalize_time(cls._last_update_invalid_time),
            "percentage": cls._current_percentage,
            "total_steps": cls._total_steps,
            "current_step": cls._current_step,
            "step_progress": cls._step_progress,
            "total_items_to_process": cls._total_items_to_process,
            "items_processed": cls._items_processed,
        }

    @classmethod
    def _update_progress(cls, current_step: int, total_steps: int, 
                        sub_operation: str = None, step_progress: int = 0):
        """
        Update the progress percentage for background jobs with granular tracking.
        
        Args:
            current_step: Current step number
            total_steps: Total number of steps
            sub_operation: Current sub-operation description
            step_progress: Progress within current step (0-100)
        """
        cls._current_step = current_step
        cls._total_steps = total_steps
        cls._step_progress = step_progress
        
        # Calculate overall percentage with granular step progress
        if total_steps > 0:
            # Each step contributes equally to overall progress
            step_weight = 100 / total_steps
            # Calculate progress: completed steps + current step progress
            completed_steps_progress = (current_step - 1) * step_weight
            current_step_progress = (step_progress / 100) * step_weight
            cls._current_percentage = int(completed_steps_progress + current_step_progress)
        else:
            cls._current_percentage = 0
        
        if sub_operation:
            cls._current_sub_operation = sub_operation
            
        logger.info(f"Progress: {cls._current_percentage}% (Step {current_step}/{total_steps}, Step Progress: {step_progress}%) - {sub_operation or 'Unknown operation'}")

    @classmethod
    def _update_step_progress(cls, step_progress: int, sub_operation: str = None):
        """
        Update progress within the current step (0-100%).
        
        Args:
            step_progress: Progress within current step (0-100)
            sub_operation: Optional sub-operation description
        """
        cls._step_progress = max(0, min(100, step_progress))  # Clamp to 0-100
        
        # Recalculate overall percentage
        if cls._total_steps > 0:
            step_weight = 100 / cls._total_steps
            completed_steps_progress = (cls._current_step - 1) * step_weight
            current_step_progress = (cls._step_progress / 100) * step_weight
            cls._current_percentage = int(completed_steps_progress + current_step_progress)
        
        if sub_operation:
            cls._current_sub_operation = sub_operation
            
        logger.info(f"Step Progress: {cls._current_percentage}% (Step {cls._current_step}/{cls._total_steps}, Step Progress: {cls._step_progress}%) - {sub_operation or 'Unknown operation'}")

    @classmethod
    def _reset_progress(cls):
        """Reset progress tracking variables."""
        cls._current_percentage = 0
        cls._total_steps = 0
        cls._current_step = 0
        cls._step_progress = 0
        cls._current_sub_operation = None
        cls._total_items_to_process = 0
        cls._items_processed = 0
        cls._last_progress_update = None

    @classmethod
    def _set_total_items(cls, total_items: int, step_name: str):
        """
        Set the total number of items to process for real-time progress tracking.
        
        Args:
            total_items: Total number of items to process in current step
            step_name: Name of the current step for logging
        """
        cls._total_items_to_process = total_items
        cls._items_processed = 0
        cls._last_progress_update = None
        logger.info(f"Starting {step_name} with {total_items} items to process")

    @classmethod
    def _update_item_progress(cls, items_processed: int = None, step_name: str = None):
        """
        Update progress as items are processed in real-time.
        
        Args:
            items_processed: Number of items processed so far (increments by 1 if None)
            step_name: Optional step name for logging
        """
        if items_processed is not None:
            cls._items_processed = items_processed
        else:
            cls._items_processed += 1
        
        if cls._total_items_to_process > 0:
            # Calculate step progress based on items processed
            step_progress = int((cls._items_processed / cls._total_items_to_process) * 100)
            cls._step_progress = step_progress
            
            # Recalculate overall percentage
            if cls._total_steps > 0:
                step_weight = 100 / cls._total_steps
                completed_steps_progress = (cls._current_step - 1) * step_weight
                current_step_progress = (step_progress / 100) * step_weight
                cls._current_percentage = int(completed_steps_progress + current_step_progress)
            
            # Log progress every 10 items or at major milestones to avoid spam
            if (cls._items_processed % 10 == 0 or 
                cls._items_processed in [cls._total_items_to_process // 4, 
                                       cls._total_items_to_process // 2, 
                                       3 * cls._total_items_to_process // 4] or
                cls._items_processed == cls._total_items_to_process):
                
                logger.info(f"Live Progress: {cls._current_percentage}% (Step {cls._current_step}/{cls._total_steps}, "
                           f"Items: {cls._items_processed}/{cls._total_items_to_process} - {step_progress}%) "
                           f"- {step_name or 'Processing'}")
        
        # Update sub-operation if provided
        if step_name:
            cls._current_sub_operation = step_name

    def perform_sync_task(self, operation: str = 'sync') -> Dict[str, Any]:
        """
        Perform the specified sync task with enhanced validation.

        Args:
            operation: Type of operation to perform

        Returns:
            Dictionary with operation results
        """
        try:
            self.logger.info(f"Starting enhanced sync task: {operation}")

            # Handle different operations
            if operation == 'update_no_match_uidi':
                return self._perform_uidi_update_operation()
            elif operation == 'update_all':
                return self._perform_full_update_operation()
            else:
                # Default to syncing from Google Sheets only
                return self._perform_google_sheets_sync_operation()

        except Exception as e:
            self.logger.error(
                f"Failed to perform sync task {operation}: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to perform sync task {operation}: {str(e)}",
                "timestamp": datetime.now(),
                "operation": operation
            }

    def _perform_google_sheets_sync_operation(self) -> Dict[str, Any]:
        """
        Perform Google Sheets sync operation with enhanced validation.

        Returns:
            Dictionary with sync results
        """
        self.__class__._current_sub_operation = "syncing_google_sheets"
        self.__class__._update_progress(1, 3, "syncing_google_sheets", 0)

        # Step 1: Extract data using enhanced extractor
        extract_result = self._extract_with_enhanced_extractor()
        
        # Update step progress to 100% when extraction completes
        self.__class__._update_step_progress(100, "syncing_google_sheets")

        if not extract_result["success"]:
            return extract_result

        # Step 2: Process and save mappings with proper categorization
        self.__class__._update_progress(2, 3, "processing_mappings", 0)
        process_result = self._process_and_save_mappings(extract_result)
        
        # Update step progress to 100% when processing completes
        self.__class__._update_step_progress(100, "processing_mappings")

        # Step 3: Sync temporary mappings
        self.__class__._current_sub_operation = "syncing_temporary_mappings"
        self.__class__._update_progress(3, 3, "syncing_temporary_mappings", 0)
        temp_result = self._sync_temporary_mappings()
        
        # Update step progress to 100% when temporary sync completes
        self.__class__._update_step_progress(100, "syncing_temporary_mappings")

        # Combine results
        final_result = {
            "success": extract_result["success"] and process_result["success"],
            "message": (
                f"Enhanced sync completed: {extract_result['statistics']['permanent_mappings']} "
                f"permanent mappings, {extract_result['statistics']['temporary_mappings']} "
                f"temporary mappings processed"
            ),
            "extraction_result": extract_result,
            "processing_result": process_result,
            "temporary_mapping_result": temp_result,
            "timestamp": datetime.now(),
            "operation": "sync"
        }

        # Update last sync time on success and persist to stats file
        if final_result["success"]:
            now_ts = datetime.now()
            self.__class__._last_sync_time = now_ts
            try:
                stats_manager = MappingStatsManager()
                stats_manager.update_sync_times("item_sync", timestamp=now_ts)
            except Exception as e:
                logger.error(f"Error persisting item sync time: {str(e)}")

        # Log comprehensive summary at the end
        self._log_comprehensive_summary(
            extract_result, process_result, temp_result)

        return final_result

    def _perform_uidi_update_operation(self) -> Dict[str, Any]:
        """
        Perform UIDI update operation with enhanced validation.

        Returns:
            Dictionary with update results
        """
        # Step 1: Sync from Google Sheets to get latest mappings
        self.__class__._current_sub_operation = "syncing_google_sheets"
        self.__class__._update_progress(1, 3, "syncing_google_sheets", 0)
        sync_result = self._perform_google_sheets_sync_operation()
        
        # Update step progress to 100% when sync completes
        self.__class__._update_step_progress(100, "syncing_google_sheets")

        if not sync_result["success"]:
            return sync_result

        # Step 2: Sync temporary mappings and save to temp-item-mapping.json
        self.__class__._current_sub_operation = "syncing_temporary_mappings"
        self.__class__._update_progress(2, 3, "syncing_temporary_mappings", 0)
        temp_result = self._sync_temporary_mappings()
        
        # Update step progress to 100% when temporary sync completes
        self.__class__._update_step_progress(100, "syncing_temporary_mappings")

        # Step 3: Update No Match / UIDI mappings using the newly synced data
        self.__class__._current_sub_operation = "updating_uidi_items"
        self.__class__._update_progress(3, 3, "updating_uidi_items", 0)
        update_result = self.mapping_controller.update_no_match_uidi_mappings()
        
        # Update step progress to 100% when UIDI update completes
        self.__class__._update_step_progress(100, "updating_uidi_items")

        # Update last UIDI update time
        if update_result.get("status") == "success":
            self.__class__._last_update_no_match_uidi_time = datetime.now()
            # Update stats file
            try:
                stats_manager = MappingStatsManager()
                stats_manager.update_sync_times("uidi_update")
            except Exception as e:
                logger.error(f"Error updating stats file: {str(e)}")

        # Log comprehensive summary for UIDI update operation
        self._log_uidi_update_summary(sync_result, update_result, temp_result)

        # Combine results
        return {
            "success": sync_result["success"] and update_result.get("status") == "success",
            "message": (
                f"UIDI update completed: {sync_result['extraction_result']['statistics']['permanent_mappings']} "
                f"mappings synced, {update_result.get('items_updated', 0)} items updated"
            ),
            "sync_result": sync_result,
            "update_result": update_result,
            "timestamp": datetime.now(),
            "operation": "update_no_match_uidi"
        }

    def _perform_full_update_operation(self) -> Dict[str, Any]:
        """
        Perform full update operation with enhanced validation.

        Returns:
            Dictionary with update results
        """
        # Step 1: Sync from Google Sheets to get latest mappings
        self.__class__._current_sub_operation = "syncing_google_sheets"
        self.__class__._update_progress(1, 3, "syncing_google_sheets", 0)
        sync_result = self._perform_google_sheets_sync_operation()
        
        # Update step progress to 100% when sync completes
        self.__class__._update_step_progress(100, "syncing_google_sheets")

        if not sync_result["success"]:
            return sync_result

        # Step 2: Sync temporary mappings and save to temp-item-mapping.json
        self.__class__._current_sub_operation = "syncing_temporary_mappings"
        self.__class__._update_progress(2, 3, "syncing_temporary_mappings", 0)
        temp_result = self._sync_temporary_mappings()
        
        # Update step progress to 100% when temporary sync completes
        self.__class__._update_step_progress(100, "syncing_temporary_mappings")

        # Step 3: Update all mappings using the newly synced data
        self.__class__._current_sub_operation = "updating_all_items"
        self.__class__._update_progress(3, 3, "updating_all_items", 0)
        update_result = self.mapping_controller.update_all_mappings()
        
        # Update step progress to 100% when all mappings update completes
        self.__class__._update_step_progress(100, "updating_all_items")

        # Update last full update time
        if update_result.get("status") == "success":
            self.__class__._last_update_all_time = datetime.now()
            # Update stats file
            try:
                stats_manager = MappingStatsManager()
                stats_manager.update_sync_times("all_update")
            except Exception as e:
                logger.error(f"Error updating stats file: {str(e)}")

        # Log comprehensive summary for full update operation
        self._log_full_update_summary(sync_result, update_result, temp_result)

        # Combine results
        return {
            "success": sync_result["success"] and update_result.get("status") == "success",
            "message": (
                f"Full update completed: {sync_result['extraction_result']['statistics']['permanent_mappings']} "
                f"mappings synced, {update_result.get('items_updated', 0)} items updated"
            ),
            "sync_result": sync_result,
            "update_result": update_result,
            "timestamp": datetime.now(),
            "operation": "update_all"
        }

    def _extract_with_enhanced_extractor(self) -> Dict[str, Any]:
        """
        Extract data using the enhanced extractor.

        Returns:
            Dictionary with extraction results
        """
        try:
            self.logger.info(
                "Starting enhanced data extraction from Google Sheets")

            # Create enhanced extractor
            extractor = EnhancedGoogleSheetDataExtractor(
                sheet_id=DEFAULT_SHEET_ID,
                api_key=GOOGLE_API_KEY,
                output_file=DEFAULT_OUTPUT_FILE,
                skip_sheets=SKIP_SHEETS,
                batch_size=MAPPING_CONFIG["batch_size"],
                fuzzy_threshold=MAPPING_CONFIG["fuzzy_threshold"]
            )

            # Process all sheets with progress tracking
            # Update progress to 25% when extraction starts
            self.__class__._update_step_progress(25, "extracting_data")
            
            result = extractor.process_all_sheets()
            
            # Update progress to 75% when extraction completes
            self.__class__._update_step_progress(75, "extracting_data")

            if result["success"]:
                self.logger.info(
                    f"Enhanced extraction completed: {result['statistics']['total_extracted']} items extracted"
                )
                # Update progress to 100% when extraction is fully complete
                self.__class__._update_step_progress(100, "extracting_data")
            else:
                self.logger.error(
                    f"Enhanced extraction failed: {result['message']}")

            return result

        except Exception as e:
            self.logger.error(f"Error in enhanced extraction: {str(e)}")
            return {
                "success": False,
                "message": f"Enhanced extraction failed: {str(e)}",
                "statistics": {
                    "total_extracted": 0,
                    "permanent_mappings": 0,
                    "temporary_mappings": 0,
                    "invalid_mappings": 0,
                    "sheets_processed": 0
                }
            }

    def _process_and_save_mappings(self, extract_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process and save mappings with proper categorization.

        Args:
            extract_result: Results from the enhanced extractor

        Returns:
            Dictionary with processing results
        """
        try:
            self.logger.info(
                "Processing and saving mappings with proper categorization")

            permanent_mappings = extract_result.get("permanent_mappings", [])
            temporary_mappings = extract_result.get("temporary_mappings", [])
            invalid_mappings = extract_result.get("invalid_mappings", [])

            # Process permanent mappings
            permanent_saved = 0
            permanent_updated = 0
            permanent_created = 0
            permanent_errors = 0

            total_permanent = len(permanent_mappings)
            self.logger.info(
                f"Processing {total_permanent} permanent mappings...")
            
            # Set up real-time progress tracking for this step
            self.__class__._set_total_items(total_permanent, "processing_permanent_mappings")

            for idx, mapping in enumerate(permanent_mappings, 1):
                try:
                    # Validate mapping data before processing (only for permanent mappings)
                    if not self._validate_mapping_data(mapping):
                        permanent_errors += 1
                        self.logger.warning(
                            f"Invalid mapping data at index {idx}, skipping")
                        continue

                    mapping_data = {
                        "mpi_code": mapping["mpi_code"],
                        "description": mapping["description"],
                        "google_sheet_name": mapping["google_sheet_name"],
                        "supplier_item_ids": mapping["supplier_item_ids"],
                        # Add supplier_id field
                        "supplier_id": mapping["supplier_id"]
                    }

                    result = self.mapping_controller.update_mapping(
                        supplier_id=mapping["supplier_id"],
                        mapping_data=mapping_data
                    )

                    if result.get("status") == "success":
                        permanent_saved += 1
                        if result.get("action") == "update":
                            permanent_updated += 1
                        elif result.get("action") == "create":
                            permanent_created += 1
                    elif result.get("status") == "skipped_duplicate":
                        # Count as skipped, not as error
                        self.logger.debug(
                            f"Skipped duplicate mapping: {result.get('message')}")
                    else:
                        permanent_errors += 1
                        self.logger.warning(
                            f"Failed to save permanent mapping: {result.get('message')}")

                except Exception as e:
                    permanent_errors += 1
                    self.logger.error(
                        f"Error saving permanent mapping: {str(e)}")
                    # Continue processing other mappings instead of stopping
                    continue

                # Update real-time progress as each mapping is processed
                self.__class__._update_item_progress(idx, "processing_permanent_mappings")

                # Log progress every 100 items or at 25%, 50%, 75%
                if idx % 100 == 0 or idx in [total_permanent // 4, total_permanent // 2, 3 * total_permanent // 4]:
                    progress_percent = int((idx / total_permanent) * 100)
                    self.logger.info(
                        f"Permanent mappings progress: {progress_percent}% ({idx}/{total_permanent}) - saved: {permanent_saved}, errors: {permanent_errors}")

            # Process temporary mappings
            temp_saved = 0
            temp_errors = 0

            for mapping in temporary_mappings:
                try:
                    # Save to temporary storage
                    self.temp_mapping_controller.create_temporary_mapping(
                        original_item=mapping["supplier_item_ids"],
                        original_description=mapping["description"],
                        sheet_name=mapping["google_sheet_name"]
                    )
                    temp_saved += 1

                except Exception as e:
                    temp_errors += 1
                    self.logger.error(
                        f"Error saving temporary mapping: {str(e)}")

            # Log invalid mappings
            if invalid_mappings:
                self.logger.warning(
                    f"Found {len(invalid_mappings)} invalid mappings that were skipped")

            return {
                "success": True,
                "message": (
                    f"Processing completed: {permanent_created} new mappings created, "
                    f"{permanent_updated} existing mappings updated, "
                    f"{temp_saved} temporary mappings saved, {len(invalid_mappings)} invalid mappings skipped"
                ),
                "permanent_saved": permanent_saved,
                "permanent_created": permanent_created,
                "permanent_updated": permanent_updated,
                "permanent_errors": permanent_errors,
                "temporary_saved": temp_saved,
                "temporary_errors": temp_errors,
                "invalid_count": len(invalid_mappings)
            }

        except Exception as e:
            self.logger.error(
                f"Error processing and saving mappings: {str(e)}")
            return {
                "success": False,
                "message": f"Error processing and saving mappings: {str(e)}",
                "permanent_saved": 0,
                "permanent_errors": 0,
                "temporary_saved": 0,
                "temporary_errors": 0,
                "invalid_count": 0
            }

    def _sync_temporary_mappings(self) -> Dict[str, Any]:
        """
        Sync temporary mappings and update invoice items.

        Returns:
            Dictionary with temporary mapping sync results
        """
        try:
            self.logger.info(
                "Syncing temporary mappings and updating invoice items")

            # Use the existing temporary mapping sync functionality
            result = self.temp_mapping_sync.perform_complete_temporary_mapping_sync(
                sheet_id=DEFAULT_SHEET_ID,
                api_key=GOOGLE_API_KEY,
                skip_sheets=SKIP_SHEETS
            )

            if result["success"]:
                self.logger.info(
                    f"Temporary mapping sync completed: {result['extraction_result']['total_mappings_extracted']} "
                    f"mappings extracted, {result['update_result']['items_updated']} items updated"
                )
            else:
                self.logger.warning(
                    f"Temporary mapping sync failed: {result['message']}")

            return result

        except Exception as e:
            self.logger.error(f"Error syncing temporary mappings: {str(e)}")
            return {
                "success": False,
                "message": f"Error syncing temporary mappings: {str(e)}",
                "extraction_result": {"total_mappings_extracted": 0},
                "update_result": {"items_updated": 0}
            }

    def _log_comprehensive_summary(self, extract_result: Dict[str, Any], process_result: Dict[str, Any], temp_result: Dict[str, Any]) -> None:
        """
        Log comprehensive summary of extraction and processing results.

        Args:
            extract_result: Results from the enhanced extractor
            process_result: Results from processing and saving mappings
            temp_result: Results from temporary mapping sync
        """
        try:
            # Extract statistics
            extract_stats = extract_result.get("statistics", {})
            process_stats = process_result or {}
            temp_stats = temp_result or {}

            # Calculate totals
            total_extracted = extract_stats.get("total_extracted", 0)
            total_permanent = extract_stats.get("permanent_mappings", 0)
            total_temporary = extract_stats.get("temporary_mappings", 0)
            total_invalid = extract_stats.get("invalid_mappings", 0)
            sheets_processed = extract_stats.get("sheets_processed", 0)

            # Processing results
            permanent_created = process_stats.get("permanent_created", 0)
            permanent_updated = process_stats.get("permanent_updated", 0)
            permanent_errors = process_stats.get("permanent_errors", 0)
            temporary_saved = process_stats.get("temporary_saved", 0)
            temporary_errors = process_stats.get("temporary_errors", 0)

            # Temporary mapping sync results
            temp_extracted = temp_stats.get("extraction_result", {}).get(
                "total_mappings_extracted", 0)
            temp_updated = temp_stats.get(
                "update_result", {}).get("items_updated", 0)

            # Log comprehensive summary
            self.logger.info("=" * 80)
            self.logger.info(
                "COMPREHENSIVE EXTRACTION AND MAPPING UPDATE SUMMARY")
            self.logger.info("=" * 80)

            # Extraction Summary
            self.logger.info("📊 EXTRACTION SUMMARY:")
            self.logger.info(
                f"   • Total Sheets Processed: {sheets_processed}")
            self.logger.info(f"   • Total Items Extracted: {total_extracted}")
            self.logger.info(f"   • Permanent Mappings: {total_permanent}")
            self.logger.info(f"   • Temporary Mappings: {total_temporary}")
            self.logger.info(f"   • Invalid Mappings: {total_invalid}")

            # Processing Summary
            self.logger.info("🔄 PROCESSING SUMMARY:")
            self.logger.info(
                f"   • Permanent Mappings Created: {permanent_created}")
            self.logger.info(
                f"   • Permanent Mappings Updated: {permanent_updated}")
            self.logger.info(
                f"   • Permanent Mapping Errors: {permanent_errors}")
            self.logger.info(
                f"   • Temporary Mappings Saved: {temporary_saved}")
            self.logger.info(
                f"   • Temporary Mapping Errors: {temporary_errors}")

            # Temporary Sync Summary
            self.logger.info("🔄 TEMPORARY MAPPING SYNC SUMMARY:")
            self.logger.info(
                f"   • Temporary Items Extracted: {temp_extracted}")
            self.logger.info(f"   • Invoice Items Updated: {temp_updated}")

            # Success Rates
            if total_permanent > 0:
                permanent_success_rate = (
                    (permanent_created + permanent_updated) / total_permanent) * 100
                self.logger.info(
                    f"   • Permanent Mapping Success Rate: {permanent_success_rate:.1f}%")

            if total_temporary > 0:
                temp_success_rate = (temporary_saved / total_temporary) * 100
                self.logger.info(
                    f"   • Temporary Mapping Success Rate: {temp_success_rate:.1f}%")

            # Overall Summary
            self.logger.info("📈 OVERALL SUMMARY:")
            self.logger.info(f"   • Total Items Processed: {total_extracted}")
            self.logger.info(
                f"   • Total Mappings Updated: {permanent_created + permanent_updated + temporary_saved}")
            self.logger.info(
                f"   • Total Errors: {permanent_errors + temporary_errors}")

            # Status
            if extract_result.get("success") and process_result.get("success"):
                self.logger.info("✅ SYNC STATUS: SUCCESSFUL")
            else:
                self.logger.info("❌ SYNC STATUS: FAILED")

            self.logger.info("=" * 80)

        except Exception as e:
            self.logger.error(f"Error logging comprehensive summary: {str(e)}")

    def _log_full_update_summary(self, sync_result: Dict[str, Any], update_result: Dict[str, Any], temp_result: Dict[str, Any] = None) -> None:
        """
        Log comprehensive summary for full update operation.

        Args:
            sync_result: Results from Google Sheets sync
            update_result: Results from updating all mappings
            temp_result: Results from temporary mapping sync
        """
        try:
            # Extract sync statistics
            sync_extract_result = sync_result.get("extraction_result", {})
            sync_process_result = sync_result.get("processing_result", {})
            sync_temp_result = sync_result.get("temporary_mapping_result", {})

            sync_stats = sync_extract_result.get("statistics", {})
            process_stats = sync_process_result or {}
            temp_stats = sync_temp_result or {}

            # Calculate sync totals
            total_extracted = sync_stats.get("total_extracted", 0)
            total_permanent = sync_stats.get("permanent_mappings", 0)
            total_temporary = sync_stats.get("temporary_mappings", 0)
            sheets_processed = sync_stats.get("sheets_processed", 0)

            # Processing results
            permanent_created = process_stats.get("permanent_created", 0)
            permanent_updated = process_stats.get("permanent_updated", 0)
            temporary_saved = process_stats.get("temporary_saved", 0)

            # Update results
            items_updated = update_result.get("items_updated", 0)
            update_status = update_result.get("status", "unknown")

            # Log comprehensive summary
            self.logger.info("=" * 80)
            self.logger.info("FULL UPDATE OPERATION - COMPREHENSIVE SUMMARY")
            self.logger.info("=" * 80)

            # Phase 1: Google Sheets Sync
            self.logger.info("📊 PHASE 1 - GOOGLE SHEETS SYNC:")
            self.logger.info(f"   • Sheets Processed: {sheets_processed}")
            self.logger.info(f"   • Total Items Extracted: {total_extracted}")
            self.logger.info(f"   • Permanent Mappings: {total_permanent}")
            self.logger.info(f"   • Temporary Mappings: {total_temporary}")
            self.logger.info(f"   • Permanent Created: {permanent_created}")
            self.logger.info(f"   • Permanent Updated: {permanent_updated}")
            self.logger.info(f"   • Temporary Saved: {temporary_saved}")

            # Phase 2: Temporary Mapping Sync (if available)
            if temp_result:
                temp_extracted = temp_result.get("extraction_result", {}).get(
                    "total_mappings_extracted", 0)
                temp_updated = temp_result.get(
                    "update_result", {}).get("items_updated", 0)
                self.logger.info("📋 PHASE 2 - TEMPORARY MAPPING SYNC:")
                self.logger.info(
                    f"   • Temporary Mappings Extracted: {temp_extracted}")
                self.logger.info(f"   • Invoice Items Updated: {temp_updated}")

            # Phase 3: All Items Update
            self.logger.info("🔄 PHASE 3 - ALL ITEMS UPDATE:")
            self.logger.info(f"   • Update Status: {update_status}")
            self.logger.info(f"   • Invoice Items Updated: {items_updated}")

            # Overall Summary
            self.logger.info("📈 OVERALL FULL UPDATE SUMMARY:")
            self.logger.info(f"   • Total Items Extracted: {total_extracted}")
            self.logger.info(
                f"   • Total Mappings Processed: {permanent_created + permanent_updated + temporary_saved}")
            self.logger.info(
                f"   • Total Invoice Items Updated: {items_updated}")

            # Success Status
            if sync_result.get("success") and update_result.get("status") == "success":
                self.logger.info("✅ FULL UPDATE STATUS: SUCCESSFUL")
            else:
                self.logger.info("❌ FULL UPDATE STATUS: FAILED")

            self.logger.info("=" * 80)

        except Exception as e:
            self.logger.error(f"Error logging full update summary: {str(e)}")

    def _log_uidi_update_summary(self, sync_result: Dict[str, Any], update_result: Dict[str, Any], temp_result: Dict[str, Any] = None) -> None:
        """
        Log comprehensive summary for UIDI update operation.

        Args:
            sync_result: Results from Google Sheets sync
            update_result: Results from updating UIDI mappings
            temp_result: Results from temporary mapping sync
        """
        try:
            # Extract sync statistics
            sync_extract_result = sync_result.get("extraction_result", {})
            sync_process_result = sync_result.get("processing_result", {})
            sync_temp_result = sync_result.get("temporary_mapping_result", {})

            sync_stats = sync_extract_result.get("statistics", {})
            process_stats = sync_process_result or {}
            temp_stats = sync_temp_result or {}

            # Calculate sync totals
            total_extracted = sync_stats.get("total_extracted", 0)
            total_permanent = sync_stats.get("permanent_mappings", 0)
            total_temporary = sync_stats.get("temporary_mappings", 0)
            sheets_processed = sync_stats.get("sheets_processed", 0)

            # Processing results
            permanent_created = process_stats.get("permanent_created", 0)
            permanent_updated = process_stats.get("permanent_updated", 0)
            temporary_saved = process_stats.get("temporary_saved", 0)

            # Update results
            items_updated = update_result.get("items_updated", 0)
            update_status = update_result.get("status", "unknown")

            # Log comprehensive summary
            self.logger.info("=" * 80)
            self.logger.info("UIDI UPDATE OPERATION - COMPREHENSIVE SUMMARY")
            self.logger.info("=" * 80)

            # Phase 1: Google Sheets Sync
            self.logger.info("📊 PHASE 1 - GOOGLE SHEETS SYNC:")
            self.logger.info(f"   • Sheets Processed: {sheets_processed}")
            self.logger.info(f"   • Total Items Extracted: {total_extracted}")
            self.logger.info(f"   • Permanent Mappings: {total_permanent}")
            self.logger.info(f"   • Temporary Mappings: {total_temporary}")
            self.logger.info(f"   • Permanent Created: {permanent_created}")
            self.logger.info(f"   • Permanent Updated: {permanent_updated}")
            self.logger.info(f"   • Temporary Saved: {temporary_saved}")

            # Phase 2: Temporary Mapping Sync (if available)
            if temp_result:
                temp_extracted = temp_result.get("extraction_result", {}).get(
                    "total_mappings_extracted", 0)
                temp_updated = temp_result.get(
                    "update_result", {}).get("items_updated", 0)
                self.logger.info("📋 PHASE 2 - TEMPORARY MAPPING SYNC:")
                self.logger.info(
                    f"   • Temporary Mappings Extracted: {temp_extracted}")
                self.logger.info(f"   • Invoice Items Updated: {temp_updated}")

            # Phase 3: UIDI Items Update
            self.logger.info("🔄 PHASE 3 - UIDI ITEMS UPDATE:")
            self.logger.info(f"   • Update Status: {update_status}")
            self.logger.info(f"   • UIDI Items Updated: {items_updated}")

            # Overall Summary
            self.logger.info("📈 OVERALL UIDI UPDATE SUMMARY:")
            self.logger.info(f"   • Total Items Extracted: {total_extracted}")
            self.logger.info(
                f"   • Total Mappings Processed: {permanent_created + permanent_updated + temporary_saved}")
            self.logger.info(f"   • Total UIDI Items Updated: {items_updated}")

            # Success Status
            if sync_result.get("success") and update_result.get("status") == "success":
                self.logger.info("✅ UIDI UPDATE STATUS: SUCCESSFUL")
            else:
                self.logger.info("❌ UIDI UPDATE STATUS: FAILED")

            self.logger.info("=" * 80)

        except Exception as e:
            self.logger.error(f"Error logging UIDI update summary: {str(e)}")

    def _validate_mapping_data(self, mapping: Dict[str, Any]) -> bool:
        """
        Validate mapping data before processing to ensure all required fields are present.
        This method is specifically for permanent mappings (not temporary ones).

        Args:
            mapping: Mapping data to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            # Check if this is a temporary mapping (supplier_id = 0)
            if mapping.get("supplier_id") == 0:
                # This is a temporary mapping, skip validation
                return True

            required_fields = [
                "mpi_code", "description", "supplier_item_ids",
                "supplier_id", "google_sheet_name"
            ]

            for field in required_fields:
                if field not in mapping:
                    self.logger.warning(
                        f"Missing required field '{field}' in mapping")
                    return False

                if not mapping[field]:
                    self.logger.warning(
                        f"Empty required field '{field}' in mapping")
                    return False

            # Validate supplier_id is a valid integer (for permanent mappings)
            try:
                supplier_id = int(mapping["supplier_id"])
                if supplier_id <= 0:
                    self.logger.warning(f"Invalid supplier_id: {supplier_id}")
                    return False
            except (ValueError, TypeError):
                self.logger.warning(
                    f"Invalid supplier_id format: {mapping['supplier_id']}")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error validating mapping data: {str(e)}")
            return False
