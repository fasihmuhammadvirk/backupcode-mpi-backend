"""
Google Sheet Sync Controller - Handles synchronization of mapping data from Google Sheets to the application database.
"""

import os
import json
import logging
from typing import Dict, List, Any, Set, Tuple
from datetime import datetime

from sqlalchemy.orm import Session

from mpi_backend.database.controllers import ItemsMappingController
from mpi_backend.utils.google_sheets import GoogleSheetDataExtractor
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID,
    DEFAULT_OUTPUT_FILE,
    GOOGLE_API_KEY,
    SKIP_SHEETS,
    MAPPING_CONFIG
)
from mpi_backend.database import SessionLocal

# Set up logging
logger = logging.getLogger(__name__)


class GoogleSheetSyncController:
    """Controller for synchronizing data from Google Sheets to the database."""

    # Class level variables to track sync status
    _sync_task_running = False
    _last_sync_time = None
    
    # Track which operation is running and last run times
    _current_operation = None  # Can be 'sync', 'update_no_match_uidi', 'update_all'
    _current_sub_operation = None  # Track specific job within operation
    _last_update_no_match_uidi_time = None
    _last_update_all_time = None
    _last_update_invalid_time = None  # For backward compatibility

    def __init__(self, db: Session):
        """
        Initialize the GoogleSheetSyncController.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.mapping_controller = ItemsMappingController(db)
        
    @classmethod
    def execute_sync_task(cls, db: Session = None, operation: str = 'sync'):
        """
        Execute the sync task with proper session management.
        
        Args:
            db: Database session. If None, a new session is created.
            operation: The operation being performed ('sync', 'update_no_match_uidi', or 'update_all')
            
        Returns:
            Dict with sync operation details
        """
        # If db is not provided, create a new session
        if db is None:
            db_session = SessionLocal()
            try:
                sync_controller = cls(db_session)
                return sync_controller.perform_sync_task(operation)
            finally:
                db_session.close()
        else:
            sync_controller = cls(db)
            return sync_controller.perform_sync_task(operation)

    @classmethod
    def get_sync_status(cls) -> Dict[str, Any]:
        """
        Get the current sync status.
        
        Returns:
            Dict with sync status information including which operation is running
            and when each operation was last run
        """
        # Use _last_update_no_match_uidi_time if available, fall back to _last_update_invalid_time for backward compatibility
        last_no_match_uidi_time = (
            cls._last_update_no_match_uidi_time or 
            cls._last_update_invalid_time
        )
        
        return {
            "is_running": cls._sync_task_running,
            "current_operation": cls._current_operation,
            "current_sub_operation": cls._current_sub_operation,
            "last_sync_time": (
                cls._last_sync_time.isoformat() 
                if cls._last_sync_time else None
            ),
            "last_update_no_match_uidi_time": (
                last_no_match_uidi_time.isoformat()
                if last_no_match_uidi_time else None
            ),
            "last_update_all_time": (
                cls._last_update_all_time.isoformat()
                if cls._last_update_all_time else None
            )
        }

    def perform_sync_task(self, operation: str = 'sync') -> Dict[str, Any]:
        """
        Performs the sync operation if no sync task is currently running.
        
        Args:
            operation: The operation being performed ('sync', 'update_no_match_uidi', or 'update_all')
            
        Returns:
            Dict with sync operation details
        """
        # Check if QuickBooks export is active and should pause
        try:
            from mpi_backend.api.routes.quickbooks import is_qb_export_active
            if is_qb_export_active():
                try:
                    logger.info("⏸️  Google Sheets sync paused - QuickBooks priority export in progress")
                except UnicodeEncodeError:
                    logger.info("Google Sheets sync paused - QuickBooks priority export in progress")
                return {
                    "success": False,
                    "message": "Sync paused for QuickBooks priority export",
                    "skipped": True
                }
        except ImportError:
            # If function not available, continue normally
            pass
        
        # If task is already running, skip this run
        if self.__class__._sync_task_running:
            logger.info(f"A {self.__class__._current_operation} task is already running, skipping this run")
            return {
                "success": False,
                "message": f"A {self.__class__._current_operation} task is already running",
                "skipped": True
            }

        try:
            self.__class__._sync_task_running = True
            self.__class__._current_operation = operation
            logger.info(f"Starting {operation} task...")

            # Handle different operations
            if operation == 'update_no_match_uidi':
                # Step 1: Sync from Google Sheets to get latest mappings
                self.__class__._current_sub_operation = "syncing_google_sheets"
                sync_result = self.sync_sheet_mappings(
                    sheet_id=DEFAULT_SHEET_ID,
                    output_file=DEFAULT_OUTPUT_FILE,
                    api_key=GOOGLE_API_KEY,
                    skip_sheets=SKIP_SHEETS,
                    batch_size=MAPPING_CONFIG["batch_size"],
                    fuzzy_threshold=MAPPING_CONFIG["fuzzy_threshold"]
                )
                
                # If sync failed, return the sync error
                if not sync_result.get("success"):
                    return sync_result
                
                # Step 2: Update No Match / UIDI mappings using the newly synced data
                self.__class__._current_sub_operation = "updating_uidi_items"
                result = self.mapping_controller.update_no_match_uidi_mappings()
                
                # Combine results
                result["sync_info"] = f"Synced {sync_result.get('new_mappings_count', 0)} new mappings from Google Sheets first"
                
            elif operation == 'update_all':
                # Step 1: Sync from Google Sheets to get latest mappings
                self.__class__._current_sub_operation = "syncing_google_sheets"
                sync_result = self.sync_sheet_mappings(
                    sheet_id=DEFAULT_SHEET_ID,
                    output_file=DEFAULT_OUTPUT_FILE,
                    api_key=GOOGLE_API_KEY,
                    skip_sheets=SKIP_SHEETS,
                    batch_size=MAPPING_CONFIG["batch_size"],
                    fuzzy_threshold=MAPPING_CONFIG["fuzzy_threshold"]
                )
                
                # If sync failed, return the sync error
                if not sync_result.get("success"):
                    return sync_result
                
                # Step 2: Update all mappings using the newly synced data
                self.__class__._current_sub_operation = "updating_all_items"
                result = self.mapping_controller.update_all_mappings()
                
                # Combine results
                result["sync_info"] = f"Synced {sync_result.get('new_mappings_count', 0)} new mappings from Google Sheets first"
                
            else:
                # Default to syncing from Google Sheets only
                self.__class__._current_sub_operation = "syncing_google_sheets"
                result = self.sync_sheet_mappings(
                    sheet_id=DEFAULT_SHEET_ID,
                    output_file=DEFAULT_OUTPUT_FILE,
                    api_key=GOOGLE_API_KEY,
                    skip_sheets=SKIP_SHEETS,
                    batch_size=MAPPING_CONFIG["batch_size"],
                    fuzzy_threshold=MAPPING_CONFIG["fuzzy_threshold"]
                )

            # Update last sync time on success
            if result.get("success"):
                self.__class__._last_sync_time = datetime.now()
                
                # Update the appropriate timestamp based on operation
                if operation == 'update_no_match_uidi':
                    self.__class__._last_update_no_match_uidi_time = datetime.now()
                elif operation == 'update_all':
                    self.__class__._last_update_all_time = datetime.now()

            return {
                **result,
                "timestamp": self.__class__._last_sync_time,
                "operation": operation
            }

        except Exception as e:
            logger.error(f"Failed to sync mappings during {operation}: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to sync mappings during {operation}: {str(e)}",
                "timestamp": datetime.now(),
                "operation": operation
            }

        finally:
            self.__class__._sync_task_running = False
            self.__class__._current_operation = None
            self.__class__._current_sub_operation = None

    def sync_sheet_mappings(
        self,
        sheet_id: str,
        output_file: str,
        dry_run: bool = False,
        api_key: str = None,
        skip_sheets: List[str] = None,
        batch_size: int = 100,
        fuzzy_threshold: int = 75
    ) -> Dict[str, Any]:
        """
        Synchronize mappings from Google Sheets to the application database.
        
        Args:
            sheet_id: Google Sheet ID to extract data from
            output_file: Path to save the extracted JSON data
            dry_run: If True, performs extraction but doesn't update the database
            api_key: Google API key
            skip_sheets: List of sheet names to skip
            batch_size: Number of items to process at once
            fuzzy_threshold: Threshold for fuzzy matching
            
        Returns:
            Dict with sync operation details
        """
        # Create temp file for new extracted data
        temp_output_file = f"{output_file}.temp"
        
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # Extract data from Google Sheets to temp file
            extractor = GoogleSheetDataExtractor(
                sheet_id=sheet_id,
                output_file=temp_output_file,
                api_key=api_key,
                skip_sheets=skip_sheets,
                batch_size=batch_size,
                fuzzy_threshold=fuzzy_threshold
            )
            
            # Process and extract data from all sheets
            extractor.process_all_sheets()
            
            # Compare with existing mappings and update database
            sync_stats = self._process_and_sync_mappings(
                temp_output_file, 
                output_file, 
                dry_run
            )
            
            return sync_stats
            
        except Exception as e:
            logger.error(f"Failed to sync mappings: {str(e)}")
            raise
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_output_file):
                os.remove(temp_output_file)

    def _process_and_sync_mappings(
        self, 
        temp_output_file: str, 
        output_file: str, 
        dry_run: bool
    ) -> Dict[str, Any]:
        """
        Process extracted data, compare with existing mappings, and update the database.
        
        Args:
            temp_output_file: Path to the temporary file with newly extracted data
            output_file: Path to save the combined JSON data
            dry_run: If True, don't update the database
            
        Returns:
            Dict with success status and mapping counts
        """
        # Get existing mappings from database
        existing_mappings_df = self.mapping_controller.get_items_mappings()
        
        # Create a unique key for each mapping for comparison
        if not existing_mappings_df.empty:
            existing_mappings_df['unique_key'] = (
                existing_mappings_df['mpi_code'] + 
                existing_mappings_df['supplier_id'].astype(str) + 
                existing_mappings_df['supplier_item_ids']
            )
            existing_keys = set(existing_mappings_df['unique_key'])
        else:
            existing_keys = set()
        
        # Load the newly extracted data from temp file
        with open(temp_output_file, 'r') as f:
            newly_extracted_data = json.load(f)
        
        # Load existing JSON file if it exists and merge with new data
        existing_json_data = self._load_existing_json(output_file)
                
        # Create a set of unique keys from existing JSON data
        existing_json_keys = self._get_unique_keys_from_json(existing_json_data)
        
        # Filter to only new mappings from the newly extracted data
        new_mappings, existing_mappings, new_json_entries = self._categorize_mappings(
            newly_extracted_data, 
            existing_keys, 
            existing_json_keys
        )
                
        # Save updated JSON data and update database
        self._update_json_and_database(
            existing_json_data,
            new_json_entries,
            new_mappings,
            output_file,
            dry_run
        )
        
        # Return only the essential information
        return {
            "success": True,
            "new_mappings_count": len(new_mappings),
            "existing_mappings_count": len(existing_mappings)
        }
        
    def _load_existing_json(self, output_file: str) -> List[Dict[str, Any]]:
        """
        Load existing JSON file if it exists.
        
        Args:
            output_file: Path to the existing JSON file
            
        Returns:
            List of mappings from the existing JSON file
        """
        existing_json_data = []
        if os.path.exists(output_file):
            try:
                with open(output_file, 'r') as f:
                    existing_json_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                # If file cannot be read or invalid JSON, use empty list
                logger.warning(f"Could not read existing JSON file {output_file}")
        return existing_json_data
        
    def _get_unique_keys_from_json(
        self, 
        json_data: List[Dict[str, Any]]
    ) -> Set[str]:
        """
        Create a set of unique keys from JSON data.
        
        Args:
            json_data: List of mappings
            
        Returns:
            Set of unique keys
        """
        unique_keys = set()
        for item in json_data:
            try:
                unique_key = (
                    item['mpi_code'] + 
                    str(item['supplier_id']) + 
                    item['supplier_item_ids']
                )
                unique_keys.add(unique_key)
            except KeyError:
                # Skip entries with missing keys
                logger.warning(f"Skipping item with missing keys: {item}")
        return unique_keys
        
    def _categorize_mappings(
        self, 
        extracted_data: List[Dict[str, Any]],
        existing_keys: Set[str],
        existing_json_keys: Set[str]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Categorize mappings into new, existing, and new for JSON.
        
        Args:
            extracted_data: List of newly extracted mappings
            existing_keys: Set of unique keys in the database
            existing_json_keys: Set of unique keys in the existing JSON
            
        Returns:
            Tuple of (new_mappings, existing_mappings, new_json_entries)
        """
        new_mappings = []
        existing_mappings = []
        new_json_entries = []
        
        for item in extracted_data:
            unique_key = (
                item['mpi_code'] + 
                str(item['supplier_id']) + 
                item['supplier_item_ids']
            )
            
            # Check against database entries first
            if unique_key in existing_keys:
                existing_mappings.append(item)
            else:
                new_mappings.append(item)
            
            # Also check against existing JSON file entries
            if unique_key not in existing_json_keys:
                new_json_entries.append(item)
                
        return new_mappings, existing_mappings, new_json_entries
        
    def _update_json_and_database(
        self,
        existing_json_data: List[Dict[str, Any]],
        new_json_entries: List[Dict[str, Any]],
        new_mappings: List[Dict[str, Any]],
        output_file: str,
        dry_run: bool
    ) -> None:
        """
        Save updated JSON data and update database with new mappings.
        
        Args:
            existing_json_data: Existing mappings from JSON
            new_json_entries: New mappings to add to JSON
            new_mappings: New mappings to add to database
            output_file: Path to save the JSON file
            dry_run: If True, don't update the database
        """
        # Save updated JSON data (combine existing with new)
        combined_json_data = existing_json_data + new_json_entries
        
        # Save the combined JSON data back to the original file
        if not dry_run:
            with open(output_file, 'w') as f:
                json.dump(combined_json_data, f, indent=2)
        
        # If not a dry run, update the database with new mappings
        if not dry_run and new_mappings:
            for mapping in new_mappings:
                mapping_data = {
                    "mpi_code": mapping["mpi_code"],
                    "description": mapping["description"],
                    "google_sheet_name": mapping["google_sheet_name"],
                    "supplier_item_ids": mapping["supplier_item_ids"]
                }
                
                self.mapping_controller.update_mapping(
                    supplier_id=mapping["supplier_id"],
                    mapping_data=mapping_data
                ) 