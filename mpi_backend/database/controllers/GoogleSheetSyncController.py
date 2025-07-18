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

from mpi_backend.utils.google_sheets.enhanced_sheet_data_extractor import (
    EnhancedGoogleSheetDataExtractor
)
from mpi_backend.utils.google_sheets.temporary_mapping_extractor import (
    TemporaryMappingExtractor
)
from mpi_backend.utils.sync_mapping.temporary_mapping_sync import (
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
        
        Args:
            db: Database session
            operation: Type of operation to perform
        """
        if cls._sync_task_running:
            logger.warning(f"Sync task already running: {cls._current_operation}")
            return
        
        cls._sync_task_running = True
        cls._current_operation = operation
        cls._current_sub_operation = None
        
        try:
            if db is None:
                from mpi_backend.database import SessionLocal
                db = SessionLocal()
            
            controller = cls(db)
            result = controller.perform_sync_task(operation)
            
            logger.info(f"Sync task completed: {operation}")
            return result
            
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

    @classmethod
    def get_sync_status(cls) -> Dict[str, Any]:
        """
        Get the current sync status.
        
        Returns:
            Dictionary with sync status information
        """
        return {
            "is_running": cls._sync_task_running,
            "current_operation": cls._current_operation,
            "current_sub_operation": cls._current_sub_operation,
            "last_sync_time": cls._last_sync_time,
            "last_update_no_match_uidi_time": cls._last_update_no_match_uidi_time,
            "last_update_all_time": cls._last_update_all_time,
            "last_update_invalid_time": cls._last_update_invalid_time
        }

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
            self.logger.error(f"Failed to perform sync task {operation}: {str(e)}")
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
        
        # Step 1: Extract data using enhanced extractor
        extract_result = self._extract_with_enhanced_extractor()
        
        if not extract_result["success"]:
            return extract_result
        
        # Step 2: Process and save mappings with proper categorization
        process_result = self._process_and_save_mappings(extract_result)
        
        # Step 3: Sync temporary mappings
        self.__class__._current_sub_operation = "syncing_temporary_mappings"
        temp_result = self._sync_temporary_mappings()
        
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
        
        # Update last sync time on success
        if final_result["success"]:
            self.__class__._last_sync_time = datetime.now()
        
        # Log comprehensive summary at the end
        self._log_comprehensive_summary(extract_result, process_result, temp_result)
        
        return final_result

    def _perform_uidi_update_operation(self) -> Dict[str, Any]:
        """
        Perform UIDI update operation with enhanced validation.
        
        Returns:
            Dictionary with update results
        """
        # Step 1: Sync from Google Sheets to get latest mappings
        self.__class__._current_sub_operation = "syncing_google_sheets"
        sync_result = self._perform_google_sheets_sync_operation()
        
        if not sync_result["success"]:
            return sync_result
        
        # Step 2: Update No Match / UIDI mappings using the newly synced data
        self.__class__._current_sub_operation = "updating_uidi_items"
        update_result = self.mapping_controller.update_no_match_uidi_mappings()
        
        # Update last UIDI update time
        if update_result.get("status") == "success":
            self.__class__._last_update_no_match_uidi_time = datetime.now()
        
        # Log comprehensive summary for UIDI update operation
        self._log_uidi_update_summary(sync_result, update_result)
        
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
        sync_result = self._perform_google_sheets_sync_operation()
        
        if not sync_result["success"]:
            return sync_result
        
        # Step 2: Update all mappings using the newly synced data
        self.__class__._current_sub_operation = "updating_all_items"
        update_result = self.mapping_controller.update_all_mappings()
        
        # Update last full update time
        if update_result.get("status") == "success":
            self.__class__._last_update_all_time = datetime.now()
        
        # Log comprehensive summary for full update operation
        self._log_full_update_summary(sync_result, update_result)
        
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
            self.logger.info("Starting enhanced data extraction from Google Sheets")
            
            # Create enhanced extractor
            extractor = EnhancedGoogleSheetDataExtractor(
                sheet_id=DEFAULT_SHEET_ID,
                api_key=GOOGLE_API_KEY,
                output_file=DEFAULT_OUTPUT_FILE,
                skip_sheets=SKIP_SHEETS,
                batch_size=MAPPING_CONFIG["batch_size"],
                fuzzy_threshold=MAPPING_CONFIG["fuzzy_threshold"]
            )
            
            # Process all sheets
            result = extractor.process_all_sheets()
            
            if result["success"]:
                self.logger.info(
                    f"Enhanced extraction completed: {result['statistics']['total_extracted']} items extracted"
                )
            else:
                self.logger.error(f"Enhanced extraction failed: {result['message']}")
            
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
            self.logger.info("Processing and saving mappings with proper categorization")
            
            permanent_mappings = extract_result.get("permanent_mappings", [])
            temporary_mappings = extract_result.get("temporary_mappings", [])
            invalid_mappings = extract_result.get("invalid_mappings", [])
            
            # Process permanent mappings
            permanent_saved = 0
            permanent_updated = 0
            permanent_created = 0
            permanent_errors = 0
            
            for mapping in permanent_mappings:
                try:
                    mapping_data = {
                        "mpi_code": mapping["mpi_code"],
                        "description": mapping["description"],
                        "google_sheet_name": mapping["google_sheet_name"],
                        "supplier_item_ids": mapping["supplier_item_ids"]
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
                    else:
                        permanent_errors += 1
                        self.logger.warning(f"Failed to save permanent mapping: {result.get('message')}")
                        
                except Exception as e:
                    permanent_errors += 1
                    self.logger.error(f"Error saving permanent mapping: {str(e)}")
            
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
                    self.logger.error(f"Error saving temporary mapping: {str(e)}")
            
            # Log invalid mappings
            if invalid_mappings:
                self.logger.warning(f"Found {len(invalid_mappings)} invalid mappings that were skipped")
            
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
            self.logger.error(f"Error processing and saving mappings: {str(e)}")
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
            self.logger.info("Syncing temporary mappings and updating invoice items")
            
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
                self.logger.warning(f"Temporary mapping sync failed: {result['message']}")
            
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
            temp_extracted = temp_stats.get("extraction_result", {}).get("total_mappings_extracted", 0)
            temp_updated = temp_stats.get("update_result", {}).get("items_updated", 0)
            
            # Log comprehensive summary
            self.logger.info("=" * 80)
            self.logger.info("COMPREHENSIVE EXTRACTION AND MAPPING UPDATE SUMMARY")
            self.logger.info("=" * 80)
            
            # Extraction Summary
            self.logger.info("📊 EXTRACTION SUMMARY:")
            self.logger.info(f"   • Total Sheets Processed: {sheets_processed}")
            self.logger.info(f"   • Total Items Extracted: {total_extracted}")
            self.logger.info(f"   • Permanent Mappings: {total_permanent}")
            self.logger.info(f"   • Temporary Mappings: {total_temporary}")
            self.logger.info(f"   • Invalid Mappings: {total_invalid}")
            
            # Processing Summary
            self.logger.info("🔄 PROCESSING SUMMARY:")
            self.logger.info(f"   • Permanent Mappings Created: {permanent_created}")
            self.logger.info(f"   • Permanent Mappings Updated: {permanent_updated}")
            self.logger.info(f"   • Permanent Mapping Errors: {permanent_errors}")
            self.logger.info(f"   • Temporary Mappings Saved: {temporary_saved}")
            self.logger.info(f"   • Temporary Mapping Errors: {temporary_errors}")
            
            # Temporary Sync Summary
            self.logger.info("🔄 TEMPORARY MAPPING SYNC SUMMARY:")
            self.logger.info(f"   • Temporary Items Extracted: {temp_extracted}")
            self.logger.info(f"   • Invoice Items Updated: {temp_updated}")
            
            # Success Rates
            if total_permanent > 0:
                permanent_success_rate = ((permanent_created + permanent_updated) / total_permanent) * 100
                self.logger.info(f"   • Permanent Mapping Success Rate: {permanent_success_rate:.1f}%")
            
            if total_temporary > 0:
                temp_success_rate = (temporary_saved / total_temporary) * 100
                self.logger.info(f"   • Temporary Mapping Success Rate: {temp_success_rate:.1f}%")
            
            # Overall Summary
            self.logger.info("📈 OVERALL SUMMARY:")
            self.logger.info(f"   • Total Items Processed: {total_extracted}")
            self.logger.info(f"   • Total Mappings Updated: {permanent_created + permanent_updated + temporary_saved}")
            self.logger.info(f"   • Total Errors: {permanent_errors + temporary_errors}")
            
            # Status
            if extract_result.get("success") and process_result.get("success"):
                self.logger.info("✅ SYNC STATUS: SUCCESSFUL")
            else:
                self.logger.info("❌ SYNC STATUS: FAILED")
            
            self.logger.info("=" * 80)
            
        except Exception as e:
            self.logger.error(f"Error logging comprehensive summary: {str(e)}")

    def _log_full_update_summary(self, sync_result: Dict[str, Any], update_result: Dict[str, Any]) -> None:
        """
        Log comprehensive summary for full update operation.
        
        Args:
            sync_result: Results from Google Sheets sync
            update_result: Results from updating all mappings
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
            
            # Phase 2: All Items Update
            self.logger.info("🔄 PHASE 2 - ALL ITEMS UPDATE:")
            self.logger.info(f"   • Update Status: {update_status}")
            self.logger.info(f"   • Invoice Items Updated: {items_updated}")
            
            # Overall Summary
            self.logger.info("📈 OVERALL FULL UPDATE SUMMARY:")
            self.logger.info(f"   • Total Items Extracted: {total_extracted}")
            self.logger.info(f"   • Total Mappings Processed: {permanent_created + permanent_updated + temporary_saved}")
            self.logger.info(f"   • Total Invoice Items Updated: {items_updated}")
            
            # Success Status
            if sync_result.get("success") and update_result.get("status") == "success":
                self.logger.info("✅ FULL UPDATE STATUS: SUCCESSFUL")
            else:
                self.logger.info("❌ FULL UPDATE STATUS: FAILED")
            
            self.logger.info("=" * 80)
            
        except Exception as e:
            self.logger.error(f"Error logging full update summary: {str(e)}")

    def _log_uidi_update_summary(self, sync_result: Dict[str, Any], update_result: Dict[str, Any]) -> None:
        """
        Log comprehensive summary for UIDI update operation.
        
        Args:
            sync_result: Results from Google Sheets sync
            update_result: Results from updating UIDI mappings
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
            
            # Phase 2: UIDI Items Update
            self.logger.info("🔄 PHASE 2 - UIDI ITEMS UPDATE:")
            self.logger.info(f"   • Update Status: {update_status}")
            self.logger.info(f"   • UIDI Items Updated: {items_updated}")
            
            # Overall Summary
            self.logger.info("📈 OVERALL UIDI UPDATE SUMMARY:")
            self.logger.info(f"   • Total Items Extracted: {total_extracted}")
            self.logger.info(f"   • Total Mappings Processed: {permanent_created + permanent_updated + temporary_saved}")
            self.logger.info(f"   • Total UIDI Items Updated: {items_updated}")
            
            # Success Status
            if sync_result.get("success") and update_result.get("status") == "success":
                self.logger.info("✅ UIDI UPDATE STATUS: SUCCESSFUL")
            else:
                self.logger.info("❌ UIDI UPDATE STATUS: FAILED")
            
            self.logger.info("=" * 80)
            
        except Exception as e:
            self.logger.error(f"Error logging UIDI update summary: {str(e)}") 