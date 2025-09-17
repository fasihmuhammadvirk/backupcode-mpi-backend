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

    def get_temporary_mappings_with_supplier_context(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Get temporary mappings organized by item with supplier context awareness.
        
        Returns:
            Dictionary mapping original_item to list of {sheet_name, context_info}
        """
        try:
            mappings = self.db.query(TempItemMapping).all()
            
            # Create lookup dictionary: original_item -> [{sheet_name, sheet_info}, ...]
            lookup = {}
            for mapping in mappings:
                if mapping.original_item and mapping.sheet_name:
                    item_key = mapping.original_item.strip()
                    if item_key not in lookup:
                        lookup[item_key] = []
                    
                    lookup[item_key].append({
                        'sheet_name': mapping.sheet_name.strip(),
                        'description': mapping.original_description or ''
                    })
            
            self.logger.info(f"Loaded {len(lookup)} temporary mappings with supplier context")
            return lookup
            
        except Exception as e:
            self.logger.error(f"Error getting temporary mappings with context: {str(e)}")
            raise

    def _extract_supplier_id(self, vendor_name: str) -> tuple:
        """Extract supplier ID and name from vendor name."""
        supplier_mapping = {
            "BMW Plumbing Supplies": 1,
            "World Wide Plumbing": 2,
            "Y & S Plumbing Supply": 3,
            "Supreme Plumbing Supply": 4,
            "Pyramid Plumbing": 5,
            "ABC Opus Services": 6,
            "Park Plumbing Supply": 7,
            "Gotham Plumbing Supply": 8,
            "FW Webb Plumbing Supply": 9,
            "Flow Mark Plumbing Supply": 10,
            "Plumbing Exchange": 11,
            "AF Supply": 12,
            "Lion Hvac Supplies": 13,
            "Bruce Ferguson": 14
        }
        
        for supplier, supplier_id in supplier_mapping.items():
            if supplier in vendor_name:
                return supplier_id, supplier
        
        return 1, "BMW Plumbing Supplies"  # Default fallback

    def _is_safe_to_update(self, item: InvoiceItem) -> bool:
        """
        Check if it's safe to update this item with temporary mappings.
        
        Safe cases:
        1. Item has "No Match" - needs assignment anyway
        2. Item has "UIDI" - temporary assignment is better than placeholder
        3. Item has no existing sheet_name assignment
        
        Args:
            item: InvoiceItem to check
            
        Returns:
            bool: True if safe to update
        """
        # Check mpi_item and mpi_description for No Match or UIDI
        mpi_item = item.mpi_item or ""
        mpi_description = item.mpi_description or ""
        
        is_no_match = (
            mpi_item == "No Match" or 
            mpi_description == "No Match"
        )
        
        is_uidi = (
            mpi_item.startswith("UIDI") or 
            mpi_description.startswith("UIDI")
        )
        
        has_no_sheet_name = not item.sheet_name or item.sheet_name.strip() == ""
        
        return is_no_match or is_uidi or has_no_sheet_name

    def update_invoice_items_with_temporary_mappings(self) -> Dict[str, Any]:
        """
        Update invoice items using temporary mappings with supplier-aware logic.
        
        This method now includes safety checks to prevent cross-supplier mapping conflicts:
        1. Only updates items that are safe to update (No Match/UIDI)
        2. Logs warnings when multiple sheet options exist for the same item
        3. Uses consistent selection logic when multiple mappings exist
        
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
            
            # Get temporary mappings with supplier context
            temp_mappings_lookup = self.get_temporary_mappings_with_supplier_context()
            
            if not temp_mappings_lookup:
                self.logger.info("No temporary mappings found")
                return {
                    "success": True,
                    "message": "No temporary mappings found",
                    "total_items_checked": len(unmapped_items),
                    "items_updated": 0
                }
            
            # Update items with safety checks
            updated_count = 0
            warnings_count = 0
            skipped_count = 0
            
            for item in unmapped_items:
                try:
                    # Safety check: only update if it's safe to do so
                    if not self._is_safe_to_update(item):
                        self.logger.debug(f"Skipping item {item.id} - not safe to update")
                        skipped_count += 1
                        continue
                    
                    # Try to match using the item field
                    item_value = item.item.strip() if item.item else ""
                    
                    if item_value in temp_mappings_lookup:
                        sheet_options = temp_mappings_lookup[item_value]
                        
                        # If multiple sheet options exist, log warning and use first one
                        if len(sheet_options) > 1:
                            sheet_names = [opt['sheet_name'] for opt in sheet_options]
                            supplier_id, supplier_name = self._extract_supplier_id(item.vendor)
                            
                            self.logger.warning(
                                f"Item '{item_value}' from {supplier_name} has multiple sheet options: {sheet_names}. "
                                f"Using first option: '{sheet_options[0]['sheet_name']}'. "
                                f"This may indicate a cross-supplier mapping conflict."
                            )
                            warnings_count += 1
                        
                        # Update the sheet_name (use first option if multiple)
                        old_sheet_name = item.sheet_name or "Empty"
                        new_sheet_name = sheet_options[0]['sheet_name']
                        item.sheet_name = new_sheet_name
                        updated_count += 1
                        
                        self.logger.debug(
                            f"Updated invoice item {item.id}: item='{item_value}', "
                            f"sheet_name: '{old_sheet_name}' -> '{new_sheet_name}'"
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
                "items_updated": updated_count,
                "warnings_count": warnings_count,
                "skipped_count": skipped_count
            }
            
            # Log summary with warnings if any
            log_message = (
                f"Successfully updated {updated_count} out of {len(unmapped_items)} invoice items "
                f"using temporary mappings"
            )
            
            if warnings_count > 0:
                log_message += f" (with {warnings_count} mapping conflict warnings)"
            
            if skipped_count > 0:
                log_message += f" (skipped {skipped_count} items for safety)"
            
            self.logger.info(log_message)
            
            return result
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error updating invoice items with temporary mappings: {str(e)}")
            return {
                "success": False,
                "message": f"Error updating invoice items: {str(e)}",
                "total_items_checked": 0,
                "items_updated": 0,
                "warnings_count": 0,
                "skipped_count": 0
            }

    def get_update_stats(self) -> Dict[str, Any]:
        """
        Get statistics about items that could be updated with temporary mappings.
        
        Returns:
            Dictionary with statistics including conflict analysis
        """
        try:
            # Get counts
            unmapped_items = self.get_unmapped_invoice_items()
            temp_mappings = self.get_temporary_mappings_with_supplier_context()
            
            # Calculate potential matches and conflicts
            potential_matches = 0
            potential_conflicts = 0
            
            for item in unmapped_items:
                if not self._is_safe_to_update(item):
                    continue
                    
                item_value = item.item.strip() if item.item else ""
                if item_value in temp_mappings:
                    potential_matches += 1
                    if len(temp_mappings[item_value]) > 1:
                        potential_conflicts += 1
            
            return {
                "total_unmapped_items": len(unmapped_items),
                "total_temporary_mappings": len(temp_mappings),
                "potential_matches": potential_matches,
                "potential_conflicts": potential_conflicts
            }
            
        except Exception as e:
            self.logger.error(f"Error getting update statistics: {str(e)}")
            return {
                "total_unmapped_items": 0,
                "total_temporary_mappings": 0,
                "potential_matches": 0,
                "potential_conflicts": 0
            } 