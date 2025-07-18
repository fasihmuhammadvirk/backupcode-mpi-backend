from mpi_backend.database.models import ItemsMapping, InvoiceItem, TempItemMapping
import pandas as pd
import logging
import re
from typing import Dict, Any, List, Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session

from mpi_backend.utils.quickbooks_priority import is_qb_export_active
from mpi_backend.utils.export_utils import extract_supplier_id
from mpi_backend.database import SessionLocal
# Removed clean_supplier_suffix import - no longer needed with suffix standardization
from mpi_backend.utils.mapping_validators import (
    validate_mapping_for_permanent_storage, 
    should_use_temporary_storage,
    is_temporary_mapping,
    clean_mapping_data
)

# Set up logging
logger = logging.getLogger(__name__)


class ItemsMappingController:
    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self) -> Session:
        """Get a database session object, whether db_context is a factory or session."""
        # Check if it's already a session instance (has query, add, commit methods)
        if hasattr(self.db_context, 'query') and hasattr(self.db_context, 'commit'):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

    @classmethod
    def execute_update_all_mappings_task(cls, db=None):
        """
        Execute update all mappings task - runs independently of other operations
        
        Args:
            db: Database session. If None, a new session is created.
            
        Returns:
            Dict with update operation details
        """
        # Mapping updates run independently of all other operations
        logger.debug("Starting mapping updates task")
        
        # Check if a sync task is already running
        from mpi_backend.database.controllers import GoogleSheetSyncController
        status = GoogleSheetSyncController.get_sync_status()
        
        if status["is_running"]:
            # Convert operation name to user-friendly format
            operation_display = {
                "sync": "Sync",
                "update_invalid": "Update Invalid Mappings",
                "update_all": "Update All Mappings"
            }.get(status['current_operation'], status['current_operation'])
            
            logger.info(f"Cannot start Update All Mappings: A {operation_display} operation is already running")
            return {
                "status": "error",
                "message": f"Cannot start Update All Mappings: A {operation_display} operation is already running"
            }
        
        # Create a new session for this task if needed with proper error handling
        created_new_session = False
        try:
            if db is None:
                from mpi_backend.database import SessionLocal
                db = SessionLocal()
                created_new_session = True
                logger.info("Created new database session for mapping update task")
            
            controller = cls(db)
            logger.info("Starting update all mappings task execution")
            result = controller.update_all_mappings()
            
            # Ensure we commit the session if we created it
            if created_new_session:
                db.commit()
                logger.info("Database session committed successfully")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in execute_update_all_mappings_task: {str(e)}")
            
            # Rollback if we created the session
            if created_new_session and db:
                try:
                    db.rollback()
                    logger.info("Database session rolled back due to error")
                except Exception as rollback_error:
                    logger.error(f"Error during rollback: {str(rollback_error)}")
            
            return {
                "status": "error",
                "message": f"Update all mappings task failed: {str(e)}"
            }
        
        finally:
            # Close session if we created it
            if created_new_session and db:
                try:
                    db.close()
                    logger.info("Database session closed successfully")
                except Exception as close_error:
                    logger.error(f"Error closing database session: {str(close_error)}")

    def search_clean_item_across_suppliers(self, clean_item: str) -> Dict[str, Any]:
        """
        Search for item mappings by clean item code across all suppliers.
        
        This method:
        - Takes a clean item code (from invoice)
        - Searches across ALL suppliers  
        - Uses suffix cleaning to compare against database items
        - Returns all matching mappings found
        
        Args:
            clean_item (str): The clean item code from invoice
            
        Returns:
            Dict containing search results
        """
        try:
            matches = []
            
            # Strip spaces from the search term
            clean_item = clean_item.strip()
            
            # Use the new session method instead of checking callable
            db = self._get_db_session()
            # Get only valid permanent mappings from all suppliers (exclude temporary ones)
            all_mappings = db.query(ItemsMapping).filter(
                ~ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.mpi_code != "No Match",
                ItemsMapping.mpi_code != "No Match / UIDI",
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != ""
            ).all()
            
            for mapping in all_mappings:
                # Additional validation to ensure we don't include temporary mappings
                if is_temporary_mapping(mapping.mpi_code, mapping.description):
                    logger.warning(f"Skipping temporary mapping in search: {mapping.mpi_code}")
                    continue
                
                # Clean both items for comparison (strip whitespace)
                clean_mapping_item = mapping.supplier_item_ids.strip()
                clean_search_item = clean_item.strip()
                
                # First try exact match (clean item vs clean database item)
                if clean_mapping_item == clean_search_item:
                    matches.append({
                        "id": mapping.id,
                        "supplier_id": mapping.supplier_id,
                        "supplier_item_ids": mapping.supplier_item_ids,
                        "mpi_code": mapping.mpi_code,
                        "description": mapping.description,
                        "google_sheet_name": mapping.google_sheet_name,
                        "match_type": "exact",
                        "supplier_name": self._get_supplier_name(mapping.supplier_id)
                    })
                # With suffix standardization, we only do exact matches
                # No more suffix cleaning needed
            else:
                # Direct session object
                db = self.db_context
                # Get only valid permanent mappings from all suppliers (exclude temporary ones)
                all_mappings = db.query(ItemsMapping).filter(
                    ~ItemsMapping.mpi_code.like("UIDI%"),
                    ItemsMapping.mpi_code != "No Match",
                    ItemsMapping.mpi_code != "No Match / UIDI",
                    ItemsMapping.mpi_code.isnot(None),
                    ItemsMapping.mpi_code != ""
                ).all()
                
                for mapping in all_mappings:
                    # Additional validation to ensure we don't include temporary mappings
                    if is_temporary_mapping(mapping.mpi_code, mapping.description):
                        logger.warning(f"Skipping temporary mapping in search: {mapping.mpi_code}")
                        continue
                    
                    # Clean both items for comparison (strip whitespace)
                    clean_mapping_item = mapping.supplier_item_ids.strip()
                    clean_search_item = clean_item.strip()
                    
                    # First try exact match (clean item vs clean database item)
                    if clean_mapping_item == clean_search_item:
                        matches.append({
                            "id": mapping.id,
                            "supplier_id": mapping.supplier_id,
                            "supplier_item_ids": mapping.supplier_item_ids,
                            "mpi_code": mapping.mpi_code,
                            "description": mapping.description,
                            "google_sheet_name": mapping.google_sheet_name,
                            "match_type": "exact",
                            "supplier_name": self._get_supplier_name(mapping.supplier_id)
                        })
                    # With suffix standardization, we only do exact matches
                    # No more suffix cleaning needed
            
            total_matches = len(matches)
            
            return {
                "found": total_matches > 0,
                "total_matches": total_matches,
                "matches": matches,
                "item_searched": clean_item
            }
            
        except Exception as e:
            logger.error(f"Error searching clean item across suppliers: {str(e)}")
            raise Exception(f"Failed to search clean item across suppliers: {str(e)}")

    def _get_supplier_name(self, supplier_id: int) -> str:
        """
        Helper method to get supplier name by ID.
        
        Args:
            supplier_id (int): Supplier ID
            
        Returns:
            str: Supplier name or "Unknown Supplier"
        """
        try:
            from mpi_backend.database.models import Supplier
            db = self._get_db_session()
            supplier = db.query(Supplier).filter_by(id=supplier_id).first()
            return supplier.supplier_name if supplier else f"Unknown Supplier (ID: {supplier_id})"
        except Exception as e:
            logger.warning(f"Could not fetch supplier name for ID {supplier_id}: {str(e)}")
            return f"Unknown Supplier (ID: {supplier_id})"

    def get_items_mappings(self, include_temporary: bool = False):
        """
        Get item mappings with option to filter out temporary mappings.
        
        Args:
            include_temporary (bool): If False (default), excludes temporary/UIDI mappings
        """
        db = self._get_db_session()
        query = db.query(ItemsMapping)
        
        # Filter out temporary mappings unless explicitly requested
        if not include_temporary:
            query = query.filter(
                ~ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.mpi_code != "No Match",
                ItemsMapping.mpi_code != "No Match / UIDI",
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != ""
            )
        
        query_result = query.all()
        
        # Additional validation to catch any temporary mappings that slipped through
        filtered_results = []
        for item in query_result:
            if include_temporary or not is_temporary_mapping(item.mpi_code, item.description):
                filtered_results.append(item)
            else:
                logger.warning(f"Filtered out temporary mapping: {item.mpi_code}")
        
        data = [(item.google_sheet_name, item.mpi_code, item.description, 
                 item.supplier_item_ids, item.supplier_id) 
                for item in filtered_results]
        columns = ['google_sheet_name', 'mpi_code', 'description',
                   'supplier_item_ids', 'supplier_id']
        items_mappings = pd.DataFrame(data, columns=columns)
        return items_mappings

    def get_items_mappings_by_supplier_id(self, supplier_id: int, limit: int = 100, 
                                          offset: int = 0):
        """
        Retrieve a list of item mappings for a specific supplier with a limit for 
        large dataset to prevent memory overloading.

        Args:
            supplier_id (int): The ID of the supplier to filter item mappings.
            limit (int, optional): The maximum number of records to return. 
                Defaults to 100.
            offset (int, optional): The number of records to skip before starting 
                to return records. Defaults to 0.

        Returns:
            list: A list of dictionaries, each containing item mapping details such as
                  'type', 'description', 'mpi_code', 'supplier_item_ids', and 
                  'supplier_id'.
        """
        db = self._get_db_session()
        return self._get_mappings_by_supplier_id(db, supplier_id, limit, offset)
    
    def _get_mappings_by_supplier_id(self, db, supplier_id: int, limit: int, offset: int):
        """Helper method to get mappings by supplier ID"""
        query_result = (
            db.query(ItemsMapping)
            .filter_by(supplier_id=supplier_id)
            .filter(
                ~ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.mpi_code != "No Match",
                ItemsMapping.mpi_code != "No Match / UIDI",
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != ""
            )
            .limit(limit)
            .offset(offset)
            .all()  # Fetch as a list instead of yielding
        )

        # Additional validation to filter out any temporary mappings
        filtered_results = []
        for item in query_result:
            if not is_temporary_mapping(item.mpi_code, item.description):
                filtered_results.append(item)
            else:
                logger.warning(f"Filtered out temporary mapping for supplier {supplier_id}: {item.mpi_code}")

        return [
            {
                "type": item.google_sheet_name,
                "description": item.description,
                "mpi_code": item.mpi_code,
                "supplier_item_ids": item.supplier_item_ids,
                "supplier_id": item.supplier_id
            }
            for item in filtered_results
        ]

    def get_items_mappings_by_mpi_type(self):
        db = self._get_db_session()
        return self._get_mappings_by_mpi_type(db)
    
    def _get_mappings_by_mpi_type(self, db):
        """Helper method to get mappings by MPI type"""
        try:
            query_result = db.query(ItemsMapping).filter(
                ~ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.mpi_code != "No Match",
                ItemsMapping.mpi_code != "No Match / UIDI",
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != ""
            ).all()

            # Additional validation to filter out any temporary mappings
            data = {}
            for item in query_result:
                if not is_temporary_mapping(item.mpi_code, item.description):
                    data[item.mpi_code] = {
                        "type": item.google_sheet_name, 
                        "mpi_description": item.description
                    }
                else:
                    logger.warning(f"Filtered out temporary mapping from MPI type data: {item.mpi_code}")
            
            return data
        except Exception as e:
            logger.error(f"Error getting mappings by MPI type: {e}")
            raise

    def update_mapping(self, supplier_id: str, mapping_data: dict):
        """
        Update or create a mapping entry and propagate changes to related 
        InvoiceItems. Now includes validation to prevent temporary mappings 
        from being saved permanently.
        
        Args:
            supplier_id (str): The supplier ID for the mapping
            mapping_data (dict): Mapping data containing mpi_code, description, etc.
        """
        db = self._get_db_session()
        return self._perform_update_mapping(db, supplier_id, mapping_data)

    def _perform_update_mapping(self, db, supplier_id: str, mapping_data: dict):
        try:
            # Clean and validate the mapping data
            cleaned_data = clean_mapping_data(mapping_data)
            is_valid, validation_errors = validate_mapping_for_permanent_storage(cleaned_data)
            
            # If this is a temporary mapping, redirect to temporary storage
            if not is_valid:
                logger.warning(f"Blocking temporary mapping from permanent storage: {cleaned_data.get('mpi_code')} - {validation_errors}")
                
                # Save to temporary storage instead
                try:
                    # In the new schema, temporary mappings store original_item -> sheet_name
                    # Extract sheet name from the mapping data
                    sheet_name = cleaned_data.get("google_sheet_name", "")
                    if not sheet_name:
                        # If no sheet name is provided, we'll skip creating a temporary mapping
                        # since it's not useful without a sheet assignment
                        logger.warning(f"No sheet name provided for temporary mapping {cleaned_data.get('supplier_item_ids')}, skipping temporary storage")
                        return {
                            "status": "skipped_temporary",
                            "message": f"Temporary mapping skipped - no sheet name provided",
                            "validation_errors": validation_errors
                        }
                    
                    self._save_to_temporary_storage(
                        db, 
                        cleaned_data.get("supplier_item_ids", ""),
                        sheet_name,
                        int(supplier_id)
                    )
                    db.commit()
                    return {
                        "status": "redirected_to_temporary",
                        "message": f"Temporary mapping saved to temporary storage for sheet assignment",
                        "validation_errors": validation_errors,
                        "temporary_mapping_created": True,
                        "sheet_name": sheet_name
                    }
                except Exception as temp_error:
                    logger.error(f"Failed to save to temporary storage: {temp_error}")
                    raise Exception(f"Cannot save temporary mapping: {validation_errors[0] if validation_errors else 'Invalid mapping data'}")
            
            # Proceed with permanent mapping (validation passed)
            is_update = False
            old_mpi_code = None
            old_description = None
            
            # Check if mapping already exists (by supplier_id, supplier_item_ids, and mpi_code)
            existing_mapping = db.query(ItemsMapping).filter_by(
                supplier_id=supplier_id,
                supplier_item_ids=cleaned_data["supplier_item_ids"],
                mpi_code=cleaned_data["mpi_code"]
            ).first()
            
            if existing_mapping:
                # Mapping already exists with same data - no need to update
                logger.debug(f"Mapping already exists (no change): {cleaned_data['supplier_item_ids']} -> {cleaned_data['mpi_code']}")
                return {
                    "status": "success",
                    "message": "Mapping already exists with same data",
                    "action": "no_change",
                    "mapping_id": existing_mapping.id
                }
            
            # Check if there's an existing mapping with same supplier_item_ids but different mpi_code
            conflicting_mapping = db.query(ItemsMapping).filter_by(
                supplier_id=supplier_id,
                supplier_item_ids=cleaned_data["supplier_item_ids"]
            ).filter(
                ItemsMapping.mpi_code != cleaned_data["mpi_code"]
            ).first()
            
            if conflicting_mapping:
                # Update existing mapping with new mpi_code
                is_update = True
                old_mpi_code = conflicting_mapping.mpi_code
                old_description = conflicting_mapping.description
                
                # Update existing mapping
                for key, value in cleaned_data.items():
                    setattr(conflicting_mapping, key, value)
                    
                logger.info(f"Updated existing mapping: {cleaned_data['supplier_item_ids']} | {old_mpi_code} -> {cleaned_data['mpi_code']}")
            else:
                # Create new mapping (append)
                is_update = False
                db_mapping = ItemsMapping(**cleaned_data, supplier_id=supplier_id)
                db.add(db_mapping)
                logger.info(f"Created new mapping (append): {cleaned_data['supplier_item_ids']} -> {cleaned_data['mpi_code']}")
            
            # Commit the changes to the mapping
            db.commit()
            
            # If this was an update and the mpi_code or description changed,
            # propagate the changes to related InvoiceItems
            if is_update and (
                old_mpi_code != cleaned_data.get("mpi_code") or 
                old_description != cleaned_data.get("description")
            ):
                try:
                    self._propagate_mapping_changes(
                        db, 
                        supplier_id,
                        cleaned_data["supplier_item_ids"],
                        cleaned_data.get("mpi_code", ""),
                        cleaned_data.get("description", ""),
                        cleaned_data.get("google_sheet_name", "")
                    )
                except Exception as e:
                    logger.error(f"Failed to propagate mapping changes: {str(e)}")
            
            return {
                "status": "success",
                "message": f"{'Updated' if is_update else 'Created'} mapping: {cleaned_data['supplier_item_ids']} -> {cleaned_data['mpi_code']}",
                "mapping_type": "permanent",
                "action": "update" if is_update else "create",
                "is_update": is_update,
                "old_mpi_code": old_mpi_code if is_update else None,
                "old_description": old_description if is_update else None
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update mapping: {str(e)}")
            raise

    def _save_to_temporary_storage(self, db: Session, original_item: str, 
                                  sheet_name: str, supplier_id: int):
        """
        Save mapping to temporary_item_mappings table instead of permanent table.
        In the new schema, temporary mappings store original_item -> sheet_name mappings.
        """
        try:
            # Check if temporary mapping already exists
            existing_temp = db.query(TempItemMapping).filter_by(
                original_item=original_item
            ).first()
            
            if existing_temp:
                # Update existing temporary mapping
                existing_temp.sheet_name = sheet_name
                logger.info(f"Updated temporary mapping: {original_item} -> sheet: {sheet_name}")
            else:
                # Create new temporary mapping
                new_temp_mapping = TempItemMapping(
                    original_item=original_item,
                    original_description="",  # We don't have description in this context
                    sheet_name=sheet_name
                )
                db.add(new_temp_mapping)
                logger.info(f"Created temporary mapping: {original_item} -> sheet: {sheet_name}")
                
        except Exception as e:
            logger.error(f"Error saving to temporary storage: {str(e)}")
            raise

    def update_no_match_uidi_mappings(self) -> Dict[str, Any]:
        """
        Update only items with No Match / UIDI mappings.
        
        Returns:
            Dict with update operation details
        """
        from mpi_backend.database.controllers import GoogleSheetSyncController
        
        # Check if a sync task is already running (except if it's another update_no_match_uidi)
        status = GoogleSheetSyncController.get_sync_status()
        if status["is_running"] and status["current_operation"] != "update_no_match_uidi":
            # Convert operation name to user-friendly format
            operation_display = {
                "sync": "Synchronization",
                "update_no_match_uidi": "No Match / UIDI Update",
                "update_all": "Full Update"
            }.get(status['current_operation'], status['current_operation'])
            
            logger.info(f"Cannot start operation: {operation_display} is already in progress")
            return {
                "status": "error",
                "message": f"Cannot start operation: {operation_display} is already in progress"
            }
            
        db = self._get_db_session()
        return self._perform_uidi_update(db)

    def _perform_uidi_update(self, db):
        """Helper method to perform the actual UIDI update"""
        try:
            # Get items with No Match / UIDI mappings - FIXED: use mpi_item instead of mpi_code
            no_match_items = db.query(InvoiceItem).filter(
                or_(
                    InvoiceItem.mpi_item.is_(None),
                    InvoiceItem.mpi_item == "",
                    InvoiceItem.mpi_item == "No Match",
                    InvoiceItem.mpi_item.like("UIDI%")
                )
            ).all()
            
            if not no_match_items:
                logger.info("No items with No Match / UIDI found for update")
                return {
                    "status": "success",
                    "message": "No items with No Match / UIDI found"
                }
                
            logger.info(f"Found {len(no_match_items)} items with No Match / UIDI for update")
                
            # Get ONLY valid permanent mappings for UIDI update
            # We want real mappings, not temporary placeholders
            valid_mappings = db.query(ItemsMapping).filter(
                ~ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.mpi_code != "No Match",
                ItemsMapping.mpi_code != "No Match / UIDI",
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != ""
            ).all()
            
            if not valid_mappings:
                logger.info("No valid permanent mappings available for UIDI update")
                return {
                    "status": "error",
                    "message": "No valid permanent mappings available"
                }
                
            logger.info(f"Found {len(valid_mappings)} valid permanent mappings for matching")
            
            # Create lookup dictionaries for faster matching
            # Group mappings by supplier for more efficient lookup
            supplier_mappings = {}
            for mapping in valid_mappings:
                # Validate this is truly a permanent mapping
                if is_temporary_mapping(mapping.mpi_code, mapping.description):
                    logger.warning(f"Skipping temporary mapping in permanent table: {mapping.mpi_code}")
                    continue
                
                supplier_id = mapping.supplier_id
                if supplier_id not in supplier_mappings:
                    supplier_mappings[supplier_id] = []
                supplier_mappings[supplier_id].append(mapping)
            
            logger.info(f"Organized mappings across {len(supplier_mappings)} suppliers")
            
            # Update No Match / UIDI items if valid mappings are found
            updated_count = 0
            no_match_found_count = 0
            
            for item in no_match_items:
                # Find matching mapping using supplier-specific suffix cleaning
                matched = False
                
                # Extract supplier_id from the invoice item's supplier/vendor
                supplier_id, supplier_name = self._extract_supplier_id(item.vendor)
                
                # Get mappings for this specific supplier
                mappings_for_supplier = supplier_mappings.get(supplier_id, [])
                
                if not mappings_for_supplier:
                    logger.debug(f"No mappings available for supplier {supplier_name} (ID: {supplier_id})")
                    continue
                
                # Clean the invoice item for comparison
                clean_invoice_item = str(item.item).strip()
                
                # Log the item we're trying to match
                logger.debug(f"Attempting to match item: '{clean_invoice_item}' from supplier {supplier_name}")
                
                for mapping in mappings_for_supplier:
                    supplier_item_ids = mapping.supplier_item_ids
                    if not supplier_item_ids:
                        continue
                    
                    # Clean the mapping item
                    clean_mapping_item = supplier_item_ids.strip()
                    
                    # First try exact match
                    if clean_invoice_item == clean_mapping_item:
                        old_status = item.mpi_item or "Empty"
                        item.mpi_item = mapping.mpi_code
                        item.mpi_description = mapping.description
                        item.sheet_name = mapping.google_sheet_name or ""
                        updated_count += 1
                        matched = True
                        
                        if old_status.startswith("UIDI"):
                            logger.info(f"UIDI override (exact): {clean_invoice_item} | {old_status} -> {mapping.mpi_code}")
                        elif old_status == "No Match":
                            logger.info(f"No Match override (exact): {clean_invoice_item} | No Match -> {mapping.mpi_code}")
                        else:
                            logger.info(f"Item update (exact): {clean_invoice_item} | {old_status} -> {mapping.mpi_code}")
                        break
                    
                    # With suffix standardization, we only do exact matches
                    # No need for suffix cleaning anymore
                    if clean_invoice_item == clean_mapping_item:
                        old_status = item.mpi_item or "Empty"
                        item.mpi_item = mapping.mpi_code
                        item.mpi_description = mapping.description
                        item.sheet_name = mapping.google_sheet_name or ""
                        updated_count += 1
                        matched = True
                        
                        if old_status.startswith("UIDI"):
                            logger.info(f"UIDI override: {clean_invoice_item} == {clean_mapping_item} | {old_status} -> {mapping.mpi_code}")
                        elif old_status == "No Match":
                            logger.info(f"No Match override: {clean_invoice_item} == {clean_mapping_item} | No Match -> {mapping.mpi_code}")
                        else:
                            logger.info(f"Item update: {clean_invoice_item} == {clean_mapping_item} | {old_status} -> {mapping.mpi_code}")
                
                # Log when no match is found for debugging
                if not matched:
                    no_match_found_count += 1
                    logger.debug(f"No mapping found for item: '{clean_invoice_item}' from supplier {supplier_name}")
                    
            db.commit()
            
            logger.info(f"UIDI update completed: {updated_count} items updated, {no_match_found_count} items remain unmatched")
            
            return {
                "status": "success",
                "message": f"Updated {updated_count} items with No Match / UIDI mappings",
                "updated_count": updated_count,
                "unmatched_count": no_match_found_count,
                "total_processed": len(no_match_items)
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update No Match / UIDI mappings: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to update No Match / UIDI mappings: {str(e)}"
            }

    def _extract_supplier_id(self, vendor_name):
        """Helper method to extract supplier ID from vendor name"""
        company_codes = {
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
            "Lion Hvac Supplies": 13
        }
        for company, code in company_codes.items():
            if company in vendor_name:
                return code, company
        return 1, "BMW Plumbing Supplies"  # Default

    def update_all_mappings(self) -> Dict[str, Any]:
        """
        Update all invoice items by applying the latest mappings.
        
        Returns:
            Dict with status and count of updated items
        """
        # Check if a sync task is already running
        from mpi_backend.database.controllers import GoogleSheetSyncController
        status = GoogleSheetSyncController.get_sync_status()
        
        if status["is_running"] and status["current_operation"] != "update_all":
            # Convert operation name to user-friendly format
            operation_display = {
                "sync": "Sync",
                "update_invalid": "Update Invalid Mappings",
                "update_all": "Update All Mappings"
            }.get(status['current_operation'], status['current_operation'])
            
            logger.info(f"Cannot start Update All Mappings: A {operation_display} operation is already running")
            return {
                "status": "error",
                "message": f"Cannot start Update All Mappings: A {operation_display} operation is already running"
            }
            
        try:
            # With suffix standardization, we use direct item code comparisons
            
            db = self._get_db_session()
            return self._perform_all_mappings_update(db)
                
        except Exception as e:
            logger.error(f"Failed to update all mappings: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to update all mappings: {str(e)}"
            }

    def _perform_all_mappings_update(self, db):
        """Helper method to perform the actual all mappings update"""
        try:
            # With suffix standardization, we use direct item code comparisons
            
            # Fetch ALL mappings from supplier table - this should apply everything in the mapping table
            # Note: We include ALL mappings because "Update All" means apply whatever is in the mapping table
            all_mappings = db.query(ItemsMapping).all()
            
            if not all_mappings:
                logger.info("No mappings found in supplier table to apply")
                return {
                    "status": "success",
                    "message": "No mappings found in supplier table to apply"
                }
            
            # Separate valid mappings from invalid ones
            valid_mappings = []
            
            for mapping in all_mappings:
                # Skip only truly invalid mappings (None, empty, etc.) but allow others
                if not mapping.mpi_code or mapping.mpi_code.strip() == "":
                    logger.warning(f"Skipping mapping with empty MPI code: {mapping.supplier_item_ids}")
                    continue
                
                # For "Update All", we want to apply what's in the table, even if it's UIDI
                # The business logic is: if it's in the supplier mapping table, apply it
                valid_mappings.append(mapping)
            
            if not valid_mappings:
                logger.info("No valid mappings found to apply after filtering")
                return {
                    "status": "success", 
                    "message": "No valid mappings found to apply after filtering"
                }
            
            # Process each mapping to update related invoice items
            total_updated_count = 0
            total_mappings_processed = 0
            
            for mapping in valid_mappings:
                total_mappings_processed += 1
                try:
                    # Get vendor name from supplier_id
                    from mpi_backend.database.models import Supplier
                    supplier = db.query(Supplier).filter_by(
                        id=mapping.supplier_id
                    ).first()
                    
                    if not supplier:
                        logger.warning(
                            f"Supplier with ID {mapping.supplier_id} not found"
                        )
                        continue
                        
                    # Find all invoice items that match this item number and supplier
                    # Note: Invoice items are clean, but mapping.supplier_item_ids may have suffixes
                    all_supplier_items = db.query(InvoiceItem).filter(
                        InvoiceItem.vendor.contains(supplier.supplier_name)
                    ).all()
                    
                    # Find matches using direct comparison (no suffix cleaning needed)
                    matching_items = []
                    # Strip whitespace from mapping item
                    clean_mapping_item = mapping.supplier_item_ids.strip()
                    
                    for invoice_item in all_supplier_items:
                        # Clean the invoice item by stripping whitespace
                        clean_invoice_item = invoice_item.item.strip()
                        
                        # With suffix standardization, we only do exact matches
                        if clean_invoice_item == clean_mapping_item:
                            matching_items.append(invoice_item)
                    
                    if not matching_items:
                        continue
                        
                    # Update all matching items
                    item_updated_count = 0
                    for item in matching_items:
                        # Apply the mapping from supplier table
                        item.mpi_item = mapping.mpi_code
                        item.mpi_description = mapping.description
                        item.sheet_name = mapping.google_sheet_name or ""
                        item_updated_count += 1
                    
                    total_updated_count += item_updated_count
                    logger.info(
                        f"Updated {item_updated_count} items for mapping "
                        f"{mapping.supplier_item_ids}"
                    )
                    
                    # Commit after each mapping batch to avoid large transactions
                    db.commit()
                    
                except Exception as e:
                    logger.error(
                        f"Error updating items for mapping "
                        f"{mapping.supplier_item_ids}: {str(e)}"
                    )
                    db.rollback()
            
            logger.info(
                f"Update complete: {total_updated_count} items updated from "
                f"{total_mappings_processed} mappings"
            )
            return {
                "status": "success",
                "message": (f"{total_updated_count} items updated from "
                            f"{total_mappings_processed} mappings")
            }
            
        except Exception as e:
            logger.error(f"Failed to update all mappings: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to update all mappings: {str(e)}"
            }
    
    def _propagate_mapping_changes(self, db, supplier_id, item_number, 
                                  new_mpi_code, new_description, sheet_name):
        """
        Propagate mapping changes to all matching InvoiceItems with suffix cleaning.
        Now includes validation to ensure we don't propagate temporary mappings.
        
        Updates all InvoiceItem records that:
        1. Have the same item number (item field) - with suffix cleaning comparison
        2. Belong to the same supplier (determined from vendor field)
        3. Only if the new mapping is NOT a temporary placeholder
        
        Args:
            db: Database session
            supplier_id (str): Supplier ID
            item_number (str): Item identifier/number (supplier_item_ids)
            new_mpi_code (str): New MPI code to set
            new_description (str): New description to set
            sheet_name (str): Sheet name to set
        """
        try:
            # Validate that we're not propagating temporary mappings
            if is_temporary_mapping(new_mpi_code, new_description):
                logger.warning(f"Skipping propagation of temporary mapping: {new_mpi_code}")
                return
            
            # Get vendor name from supplier_id
            from mpi_backend.database.models import Supplier
            supplier = db.query(Supplier).filter_by(id=supplier_id).first()
            
            if not supplier:
                logger.warning(f"Supplier with ID {supplier_id} not found")
                return
            
            # Find all invoice items that match this item number and supplier
            # Note: Invoice items are clean, but mapping item_number may have suffixes
            all_invoice_items = db.query(InvoiceItem).filter(
                InvoiceItem.vendor.contains(supplier.supplier_name)
            ).all()
            
            matching_items = []
            # Strip whitespace from mapping item
            clean_mapping_item = item_number.strip()
            
            for invoice_item in all_invoice_items:
                # Clean the invoice item by stripping whitespace
                clean_invoice_item = invoice_item.item.strip()
                
                # With suffix standardization, we only do exact matches
                if clean_invoice_item == clean_mapping_item:
                    matching_items.append(invoice_item)
            
            if not matching_items:
                logger.info(f"No matching invoice items found for {item_number}")
                return
                
            # Update all matching items, prioritizing UIDI items for override
            updated_count = 0
            uidi_override_count = 0
            
            for item in matching_items:
                # Track if we're overriding a UIDI item with a valid mapping
                was_uidi = item.mpi_item and item.mpi_item.startswith("UIDI")
                
                item.mpi_item = new_mpi_code
                item.mpi_description = new_description
                item.sheet_name = sheet_name
                updated_count += 1
                
                if was_uidi:
                    uidi_override_count += 1
                    logger.info(f"Overrode UIDI item {item.item} with permanent mapping {new_mpi_code}")
                
            # Commit the changes
            db.commit()
            
            log_message = f"Updated {updated_count} invoice items with new mapping data for {item_number}"
            if uidi_override_count > 0:
                log_message += f" (including {uidi_override_count} UIDI overrides)"
            logger.info(log_message)
            
        except Exception as e:
            logger.error(f"Error propagating mapping changes: {str(e)}")
            db.rollback()
            raise
        
    def _get_db_session(self):
        """Get a database session object, whether db_context is a factory or session."""
        if callable(self.db_context):
            # This is a session factory, return a new session
            return self.db_context()
        else:
            # This is already a session object
            return self.db_context
