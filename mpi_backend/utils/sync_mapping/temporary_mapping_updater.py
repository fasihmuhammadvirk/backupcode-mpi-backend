#!/usr/bin/env python3
"""
Temporary Mapping Updater - Updates invoice items using temporary mappings.

This module provides functionality to update invoice items that have no sheet_name
by matching them against temporary mappings and assigning the appropriate sheet_name.
"""

import logging
from typing import Dict, List, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_

from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping

# Set up logging
logger = logging.getLogger(__name__)


class TemporaryMappingUpdater:
    """Updates invoice items using temporary mappings."""

    def __init__(self, db: Session):
        """
        Initialize the TemporaryMappingUpdater.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.logger = logging.getLogger(f"{__name__}")

    def get_unmapped_invoice_items(self) -> List[InvoiceItem]:
        """
        Get invoice items that need sheet_name assignment.
        
        Criteria:
        - Do not have a sheet_name (empty or None)
        - Have mpi_item_id or mpi_description = "No Match", or
        - Have mpi_item_id or mpi_description starts with "UIDI" (case-insensitive)
        
        Returns:
            List of InvoiceItem objects that need updating
        """
        try:
            # Query for items that need sheet_name assignment
            query = self.db.query(InvoiceItem).filter(
                # No sheet_name or empty sheet_name
                or_(
                    InvoiceItem.sheet_name.is_(None),
                    InvoiceItem.sheet_name == ""
                ),
                # AND one of the following conditions:
                or_(
                    # mpi_item is "No Match"
                    InvoiceItem.mpi_item == "No Match",
                    # mpi_description is "No Match"
                    InvoiceItem.mpi_description == "No Match",
                    # mpi_item starts with "UIDI" (case-insensitive)
                    InvoiceItem.mpi_item.ilike("UIDI%"),
                    # mpi_description starts with "UIDI" (case-insensitive)
                    InvoiceItem.mpi_description.ilike("UIDI%")
                )
            )
            
            items = query.all()
            self.logger.info(f"Found {len(items)} invoice items that need sheet_name assignment")
            return items
            
        except Exception as e:
            self.logger.error(f"Error getting unmapped invoice items: {str(e)}")
            raise

    def get_temporary_mappings(self) -> Dict[str, str]:
        """
        Get all temporary mappings as a lookup dictionary.
        
        Returns:
            Dictionary mapping original_item to sheet_name
        """
        try:
            mappings = self.db.query(TempItemMapping).all()
            
            # Create lookup dictionary: original_item -> sheet_name
            lookup = {}
            for mapping in mappings:
                if mapping.original_item and mapping.sheet_name:
                    lookup[mapping.original_item.strip()] = mapping.sheet_name.strip()
            
            self.logger.info(f"Loaded {len(lookup)} temporary mappings for lookup")
            return lookup
            
        except Exception as e:
            self.logger.error(f"Error getting temporary mappings: {str(e)}")
            raise

    def update_invoice_items_with_temporary_mappings(self) -> Dict[str, Any]:
        """
        Update invoice items using temporary mappings.
        
        Returns:
            Dictionary with update results
        """
        try:
            # Get unmapped invoice items
            unmapped_items = self.get_unmapped_invoice_items()
            
            if not unmapped_items:
                self.logger.info("No unmapped invoice items found")
                return {
                    "success": True,
                    "message": "No unmapped invoice items found",
                    "total_items_checked": 0,
                    "items_updated": 0
                }
            
            # Get temporary mappings lookup
            temp_mappings_lookup = self.get_temporary_mappings()
            
            if not temp_mappings_lookup:
                self.logger.info("No temporary mappings found")
                return {
                    "success": True,
                    "message": "No temporary mappings found",
                    "total_items_checked": len(unmapped_items),
                    "items_updated": 0
                }
            
            # Update items
            updated_count = 0
            
            for item in unmapped_items:
                try:
                    # Try to match using the item field
                    item_value = item.item.strip() if item.item else ""
                    
                    if item_value in temp_mappings_lookup:
                        # Update the sheet_name
                        old_sheet_name = item.sheet_name or "Empty"
                        item.sheet_name = temp_mappings_lookup[item_value]
                        updated_count += 1
                        
                        self.logger.debug(
                            f"Updated invoice item {item.id}: item='{item_value}', "
                            f"sheet_name: '{old_sheet_name}' -> '{item.sheet_name}'"
                        )
                
                except Exception as e:
                    self.logger.error(f"Error updating invoice item {item.id}: {str(e)}")
                    continue
            
            # Commit changes
            self.db.commit()
            
            result = {
                "success": True,
                "message": f"Updated {updated_count} invoice items with temporary mappings",
                "total_items_checked": len(unmapped_items),
                "items_updated": updated_count
            }
            
            self.logger.info(
                f"Successfully updated {updated_count} out of {len(unmapped_items)} invoice items "
                f"using temporary mappings"
            )
            
            return result
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error updating invoice items with temporary mappings: {str(e)}")
            return {
                "success": False,
                "message": f"Error updating invoice items: {str(e)}",
                "total_items_checked": 0,
                "items_updated": 0
            }

    def get_update_stats(self) -> Dict[str, Any]:
        """
        Get statistics about items that could be updated with temporary mappings.
        
        Returns:
            Dictionary with statistics
        """
        try:
            # Get counts
            unmapped_items = self.get_unmapped_invoice_items()
            temp_mappings = self.get_temporary_mappings()
            
            # Calculate potential matches
            potential_matches = 0
            for item in unmapped_items:
                item_value = item.item.strip() if item.item else ""
                if item_value in temp_mappings:
                    potential_matches += 1
            
            return {
                "total_unmapped_items": len(unmapped_items),
                "total_temporary_mappings": len(temp_mappings),
                "potential_matches": potential_matches
            }
            
        except Exception as e:
            self.logger.error(f"Error getting update statistics: {str(e)}")
            return {
                "total_unmapped_items": 0,
                "total_temporary_mappings": 0,
                "potential_matches": 0
            } 