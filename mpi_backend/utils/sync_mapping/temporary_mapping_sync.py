#!/usr/bin/env python3
"""
Temporary Mapping Sync - Extends Google Sheets sync to include temporary mappings.

This module provides functionality to extract temporary mappings from Google Sheets
and update invoice items with sheet_name assignments as part of the sync process.
"""

import logging
import pandas as pd
from typing import Dict, List, Any
from sqlalchemy.orm import Session

from mpi_backend.utils.google_sheets.enhanced_sheet_data_extractor import EnhancedGoogleSheetDataExtractor
from mpi_backend.utils.google_sheets.temporary_mapping_extractor import TemporaryMappingExtractor
from mpi_backend.utils.sync_mapping.temporary_mapping_updater import TemporaryMappingUpdater

# Set up logging
logger = logging.getLogger(__name__)


class TemporaryMappingSync:
    """Handles temporary mapping extraction and sync as part of Google Sheets sync."""

    def __init__(self, db: Session):
        """
        Initialize the TemporaryMappingSync.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.temp_extractor = TemporaryMappingExtractor(db)
        self.temp_updater = TemporaryMappingUpdater(db)
        self.logger = logging.getLogger(f"{__name__}")

    def extract_temporary_mappings_from_sheets(
        self, 
        sheet_id: str, 
        api_key: str = None, 
        skip_sheets: List[str] = None
    ) -> Dict[str, Any]:
        """
        Extract temporary mappings from all sheets in Google Sheets.
        
        Args:
            sheet_id: Google Sheet ID
            api_key: Google API key
            skip_sheets: List of sheet names to skip
            
        Returns:
            Dictionary with extraction results
        """
        try:
            # Create a minimal extractor instance just for getting sheet data
            extractor = EnhancedGoogleSheetDataExtractor(
                sheet_id=sheet_id,
                api_key=api_key,
                skip_sheets=skip_sheets or [],
                batch_size=100,
                fuzzy_threshold=75
            )
            
            # Get list of sheets
            sheets = extractor.get_sheet_list()
            
            if not sheets:
                self.logger.warning("No sheets found for temporary mapping extraction")
                return {
                    "success": True,
                    "message": "No sheets found",
                    "total_mappings_extracted": 0,
                    "sheets_processed": 0
                }
            
            total_mappings = 0
            sheets_processed = 0
            
            # Process each sheet for temporary mappings
            for sheet in sheets:
                try:
                    sheet_title = sheet['title']
                    gid = sheet['gid']
                    
                    # Skip sheets that are in the skip list
                    if any(skip_name in sheet_title for skip_name in (skip_sheets or [])):
                        self.logger.debug(f"Skipping sheet {sheet_title} (in skip list)")
                        continue
                    
                    # Get sheet data
                    df = self._get_sheet_dataframe(sheet_id, gid)
                    
                    if df is None or df.empty:
                        self.logger.debug(f"Sheet {sheet_title} is empty or could not be loaded")
                        continue
                    
                    # Extract clean sheet name for classification
                    clean_sheet_name = extractor._extract_clean_sheet_name(sheet_title)
                    
                    # Extract temporary mappings from this sheet
                    mappings_count = self.temp_extractor.extract_and_save_from_dataframe(
                        df, clean_sheet_name
                    )
                    
                    if mappings_count > 0:
                        total_mappings += mappings_count
                        sheets_processed += 1
                        self.logger.info(
                            f"Extracted {mappings_count} temporary mappings from sheet: {sheet_title}"
                        )
                
                except Exception as e:
                    self.logger.error(f"Error processing sheet {sheet['title']}: {str(e)}")
                    continue
            
            result = {
                "success": True,
                "message": f"Extracted {total_mappings} temporary mappings from {sheets_processed} sheets",
                "total_mappings_extracted": total_mappings,
                "sheets_processed": sheets_processed
            }
            
            self.logger.info(
                f"Temporary mapping extraction complete: {total_mappings} mappings from {sheets_processed} sheets"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error extracting temporary mappings: {str(e)}")
            return {
                "success": False,
                "message": f"Error extracting temporary mappings: {str(e)}",
                "total_mappings_extracted": 0,
                "sheets_processed": 0
            }

    def _get_sheet_dataframe(self, sheet_id: str, gid: str) -> pd.DataFrame:
        """
        Get a DataFrame for a specific sheet.
        
        Args:
            sheet_id: Google Sheet ID
            gid: Sheet GID
            
        Returns:
            DataFrame or None if error
        """
        try:
            # Create export URL for the sheet
            export_url = (
                f"https://docs.google.com/spreadsheets/d/{sheet_id}/export"
                f"?format=csv&gid={gid}"
            )
            
            # Try to load the sheet
            try:
                # First attempt with standard URL
                df = pd.read_csv(export_url)
            except Exception:
                # Try alternative URL pattern
                alternate_url = (
                    f"https://docs.google.com/spreadsheets/d/{sheet_id}/"
                    f"gviz/tq?tqx=out:csv&gid={gid}"
                )
                df = pd.read_csv(alternate_url)
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error loading sheet {gid}: {str(e)}")
            return None

    def update_invoice_items_with_temporary_mappings(self) -> Dict[str, Any]:
        """
        Update invoice items using temporary mappings.
        
        Returns:
            Dictionary with update results
        """
        try:
            self.logger.info("Starting invoice item updates using temporary mappings")
            
            result = self.temp_updater.update_invoice_items_with_temporary_mappings()
            
            if result["success"]:
                self.logger.info(
                    f"Successfully updated {result['items_updated']} invoice items "
                    f"out of {result['total_items_checked']} checked"
                )
            else:
                self.logger.error(f"Failed to update invoice items: {result['message']}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error updating invoice items: {str(e)}")
            return {
                "success": False,
                "message": f"Error updating invoice items: {str(e)}",
                "total_items_checked": 0,
                "items_updated": 0
            }

    def perform_complete_temporary_mapping_sync(
        self, 
        sheet_id: str, 
        api_key: str = None, 
        skip_sheets: List[str] = None
    ) -> Dict[str, Any]:
        """
        Perform complete temporary mapping sync: extract mappings and update invoice items.
        
        Args:
            sheet_id: Google Sheet ID
            api_key: Google API key
            skip_sheets: List of sheet names to skip
            
        Returns:
            Dictionary with complete sync results
        """
        try:
            self.logger.info("Starting complete temporary mapping sync")
            
            # Step 1: Extract temporary mappings from Google Sheets
            extract_result = self.extract_temporary_mappings_from_sheets(
                sheet_id, api_key, skip_sheets
            )
            
            if not extract_result["success"]:
                return {
                    "success": False,
                    "message": f"Temporary mapping extraction failed: {extract_result['message']}",
                    "extraction_result": extract_result,
                    "update_result": None
                }
            
            # Step 2: Update invoice items using temporary mappings
            update_result = self.update_invoice_items_with_temporary_mappings()
            
            # Combine results
            result = {
                "success": extract_result["success"] and update_result["success"],
                "message": (
                    f"Extracted {extract_result['total_mappings_extracted']} temporary mappings, "
                    f"updated {update_result['items_updated']} invoice items"
                ),
                "extraction_result": extract_result,
                "update_result": update_result
            }
            
            if result["success"]:
                self.logger.info(
                    f"Complete temporary mapping sync successful: "
                    f"{extract_result['total_mappings_extracted']} mappings extracted, "
                    f"{update_result['items_updated']} items updated"
                )
            else:
                self.logger.error("Complete temporary mapping sync failed")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error in complete temporary mapping sync: {str(e)}")
            return {
                "success": False,
                "message": f"Complete sync failed: {str(e)}",
                "extraction_result": None,
                "update_result": None
            }

    def get_temporary_mapping_stats(self) -> Dict[str, Any]:
        """
        Get statistics about temporary mappings and potential updates.
        
        Returns:
            Dictionary with statistics
        """
        try:
            stats = self.temp_updater.get_update_stats()
            self.logger.info(f"Temporary mapping stats: {stats}")
            return stats
            
        except Exception as e:
            self.logger.error(f"Error getting temporary mapping stats: {str(e)}")
            return {
                "total_unmapped_items": 0,
                "total_temporary_mappings": 0,
                "potential_matches": 0
            } 