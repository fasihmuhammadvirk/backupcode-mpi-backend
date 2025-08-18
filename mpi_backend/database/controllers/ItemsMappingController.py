from mpi_backend.database.models import ItemsMapping, InvoiceItem, TempItemMapping
import pandas as pd
import logging
import re
from typing import Dict, Any, List, Optional
from sqlalchemy import or_, and_
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
from mpi_backend.utils.mapping_stats_manager import MappingStatsManager

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

            logger.info(
                f"Cannot start Update All Mappings: A {operation_display} operation is already running")
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
                logger.info(
                    "Created new database session for mapping update task")

            controller = cls(db)
            logger.info("Starting update all mappings task execution")
            result = controller.update_all_mappings()

            # Ensure we commit the session if we created it
            if created_new_session:
                db.commit()
                logger.info("Database session committed successfully")

            return result

        except Exception as e:
            logger.error(
                f"Error in execute_update_all_mappings_task: {str(e)}")

            # Rollback if we created the session
            if created_new_session and db:
                try:
                    db.rollback()
                    logger.info("Database session rolled back due to error")
                except Exception as rollback_error:
                    logger.error(
                        f"Error during rollback: {str(rollback_error)}")

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
                    logger.error(
                        f"Error closing database session: {str(close_error)}")

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
                    logger.warning(
                        f"Skipping temporary mapping in search: {mapping.mpi_code}")
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
                        logger.warning(
                            f"Skipping temporary mapping in search: {mapping.mpi_code}")
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
            logger.error(
                f"Error searching clean item across suppliers: {str(e)}")
            raise Exception(
                f"Failed to search clean item across suppliers: {str(e)}")

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
            logger.warning(
                f"Could not fetch supplier name for ID {supplier_id}: {str(e)}")
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
                logger.warning(
                    f"Filtered out temporary mapping: {item.mpi_code}")

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
                logger.warning(
                    f"Filtered out temporary mapping for supplier {supplier_id}: {item.mpi_code}")

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
            # Include valid mappings and also UIDI items (temporary placeholders)
            # Exclude only true invalids and explicit "No Match" variants
            query_result = db.query(ItemsMapping).filter(
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != "",
                ItemsMapping.mpi_code != "No Match",
            ).all()

            # Additional validation to filter out any temporary mappings
            data = {}
            for item in query_result:
                # If UIDI item (case-insensitive, ignore surrounding whitespace),
                # include with type forcibly set to "UDI" and keep any description present
                mpi_code_clean = str(item.mpi_code).strip()
                if mpi_code_clean.upper().startswith("UIDI"):
                    data[mpi_code_clean] = {
                        "type": "UDI",
                        "mpi_description": item.description or ""
                    }
                # For non-UIDI, keep excluding other temporary placeholders
                elif not is_temporary_mapping(mpi_code_clean, item.description):
                    data[mpi_code_clean] = {
                        "type": item.google_sheet_name,
                        "mpi_description": item.description
                    }
                else:
                    logger.warning(
                        f"Filtered out temporary mapping from MPI type data: {item.mpi_code}")

            # Also include UIDI entries that are not present in supplier_item_mappings but appear
            # in invoice items as mpi_item values (e.g., No Match / UIDI or UIDI*** codes).
            # For these, we set type to "UDI" and use any available description.
            try:
                invoice_uidi_items = (
                    db.query(InvoiceItem.mpi_item, InvoiceItem.mpi_description, InvoiceItem.description)
                    .filter(
                        InvoiceItem.mpi_item.isnot(None),
                        InvoiceItem.mpi_item != "",
                        # Include both explicit UIDI codes and the combined label
                        or_(
                            InvoiceItem.mpi_item.ilike("UIDI%"),
                            InvoiceItem.mpi_item == "No Match / UIDI"
                        )
                    )
                    .all()
                )

                for mpi_item_value, mpi_desc, item_desc in invoice_uidi_items:
                    key = str(mpi_item_value).strip()
                    if not key:
                        continue
                    # Skip if already present from the permanent mappings
                    if key in data:
                        continue
                    # Use mpi_description if present, else fallback to item description, else empty
                    desc = (mpi_desc or item_desc or "").strip()
                    data[key] = {
                        "type": "UDI",
                        "mpi_description": desc
                    }
            except Exception as inv_err:
                logger.warning(f"Failed to enrich UIDI types from invoice items: {inv_err}")

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

        # Validate supplier_id exists in database
        if not self._validate_supplier_id(db, supplier_id):
            logger.error(
                f"Supplier ID {supplier_id} does not exist in database. Available suppliers: {self._get_available_supplier_ids(db)}")
            return {
                "status": "error",
                "message": f"Supplier ID {supplier_id} does not exist in database"
            }

        return self._perform_update_mapping(db, supplier_id, mapping_data)

    def _perform_update_mapping(self, db, supplier_id: str, mapping_data: dict):
        try:
            # Clean and validate the mapping data
            cleaned_data = clean_mapping_data(mapping_data)

            # Guard against empty/whitespace-only supplier_item_ids for both update and create paths
            supplier_item_ids_clean = cleaned_data.get("supplier_item_ids", "")
            if isinstance(supplier_item_ids_clean, str):
                supplier_item_ids_clean = supplier_item_ids_clean.strip()
            if not supplier_item_ids_clean:
                logger.info("Skipping mapping update/create due to empty supplier_item_ids")
                return {
                    "status": "skipped_empty_item",
                    "message": "supplier_item_ids cannot be empty or whitespace",
                    "action": "no_change"
                }
            # Persist trimmed value
            cleaned_data["supplier_item_ids"] = supplier_item_ids_clean
            is_valid, validation_errors = validate_mapping_for_permanent_storage(
                cleaned_data)

            # If this is a temporary mapping, redirect to temporary storage
            if not is_valid:
                logger.warning(
                    f"Blocking temporary mapping from permanent storage: {cleaned_data.get('mpi_code')} - {validation_errors}")

                # Save to temporary storage instead
                try:
                    # In the new schema, temporary mappings store original_item -> sheet_name
                    # Extract sheet name from the mapping data
                    sheet_name = cleaned_data.get("google_sheet_name", "")
                    if not sheet_name:
                        # If no sheet name is provided, we'll skip creating a temporary mapping
                        # since it's not useful without a sheet assignment
                        logger.warning(
                            f"No sheet name provided for temporary mapping {cleaned_data.get('supplier_item_ids')}, skipping temporary storage")
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
                    logger.error(
                        f"Failed to save to temporary storage: {temp_error}")
                    raise Exception(
                        f"Cannot save temporary mapping: {validation_errors[0] if validation_errors else 'Invalid mapping data'}")

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
                logger.debug(
                    f"Mapping already exists (no change): {cleaned_data['supplier_item_ids']} -> {cleaned_data['mpi_code']}")
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

                # Update existing mapping (exclude supplier_id to avoid conflicts)
                # Do NOT overwrite fields with None or empty strings
                updated_fields = []
                for key, value in cleaned_data.items():
                    if key == 'supplier_id':
                        continue
                    if value is None:
                        continue
                    if isinstance(value, str) and value.strip() == "":
                        continue
                    setattr(conflicting_mapping, key, value)
                    updated_fields.append(key)

                if not updated_fields:
                    logger.info(
                        f"Skipped updating mapping due to only empty/None values provided: {cleaned_data.get('supplier_item_ids', '')}")
                    return {
                        "status": "skipped_empty_update",
                        "message": "No non-empty fields provided to update",
                        "action": "no_change",
                        "mapping_id": conflicting_mapping.id
                    }

                logger.info(
                    f"Updated existing mapping fields {updated_fields}: {cleaned_data['supplier_item_ids']} | {old_mpi_code} -> {cleaned_data['mpi_code']}")
            else:
                # Create new mapping (append)
                is_update = False
                # Remove supplier_id from cleaned_data to avoid conflict with keyword argument
                mapping_data_for_db = {
                    k: v for k, v in cleaned_data.items() if k != 'supplier_id'}
                db_mapping = ItemsMapping(
                    **mapping_data_for_db, supplier_id=supplier_id)
                db.add(db_mapping)
                logger.info(
                    f"Created new mapping (append): {cleaned_data['supplier_item_ids']} -> {cleaned_data['mpi_code']}")

            # Commit the changes to the mapping
            try:
                db.commit()
            except Exception as commit_error:
                # Handle duplicate key constraint violations
                if "duplicate key value violates unique constraint" in str(commit_error):
                    logger.warning(
                        f"Duplicate key constraint violation for mapping {cleaned_data['supplier_item_ids']} -> {cleaned_data['mpi_code']}. Skipping this mapping.")
                    db.rollback()
                    return {
                        "status": "skipped_duplicate",
                        "message": f"Mapping skipped due to duplicate key constraint",
                        "action": "skipped"
                    }
                else:
                    # Re-raise other commit errors
                    raise commit_error

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
                    logger.error(
                        f"Failed to propagate mapping changes: {str(e)}")

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
                logger.info(
                    f"Updated temporary mapping: {original_item} -> sheet: {sheet_name}")
            else:
                # Create new temporary mapping
                new_temp_mapping = TempItemMapping(
                    original_item=original_item,
                    original_description="",  # We don't have description in this context
                    sheet_name=sheet_name
                )
                db.add(new_temp_mapping)
                logger.info(
                    f"Created temporary mapping: {original_item} -> sheet: {sheet_name}")

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

            logger.info(
                f"Cannot start operation: {operation_display} is already in progress")
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

            logger.info(
                f"Found {len(no_match_items)} items with No Match / UIDI for update")

            # Get valid permanent mappings for UIDI update (including those without sheet names)
            # We want real mappings, not temporary placeholders
            valid_mappings = db.query(ItemsMapping).filter(
                ~ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.mpi_code != "No Match",
                ItemsMapping.mpi_code != "No Match / UIDI",
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != ""
            ).all()

            if not valid_mappings:
                logger.info(
                    "No valid permanent mappings available for UIDI update")
                return {
                    "status": "error",
                    "message": "No valid permanent mappings available"
                }

            logger.info(
                f"Found {len(valid_mappings)} valid permanent mappings for matching")

            # Get temporary mappings for additional matching
            from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
            temp_mappings = db.query(TempItemMapping).all()
            logger.info(
                f"Found {len(temp_mappings)} temporary mappings for additional matching")

            # Create lookup dictionary for faster matching - PERMANENT MAPPINGS FIRST
            mappings_lookup = {}
            mappings_without_sheet = {}  # Track mappings without sheet names

            for mapping in valid_mappings:
                # Validate this is truly a permanent mapping
                if is_temporary_mapping(mapping.mpi_code, mapping.description):
                    logger.warning(
                        f"Skipping temporary mapping in permanent table: {mapping.mpi_code}")
                    continue

                clean_mapping_item = mapping.supplier_item_ids.strip()
                if clean_mapping_item:
                    # Store the mapping with the clean item as key - exact match only
                    mappings_lookup[clean_mapping_item] = mapping

                    # Track mappings without sheet names for special handling
                    if not mapping.google_sheet_name or mapping.google_sheet_name.strip() == "":
                        mappings_without_sheet[clean_mapping_item] = mapping

            # Add temporary mappings to lookup (lower priority than permanent)
            temp_lookup = {}
            for temp_mapping in temp_mappings:
                # Handle None values safely
                if temp_mapping.original_item is None:
                    continue

                clean_temp_item = temp_mapping.original_item.strip()
                if clean_temp_item and clean_temp_item not in mappings_lookup:  # Don't override permanent mappings
                    temp_lookup[clean_temp_item] = temp_mapping

            logger.info(
                f"Created lookup with {len(mappings_lookup)} permanent mappings and {len(temp_lookup)} temporary mappings")
            logger.info(
                f"Found {len(mappings_without_sheet)} permanent mappings without sheet names")

            # Update No Match / UIDI items if valid mappings are found
            updated_count = 0
            no_match_found_count = 0
            updated_from_permanent = 0
            updated_from_temp = 0
            updated_from_no_sheet = 0

            for item in no_match_items:
                # Clean the invoice item for comparison
                clean_invoice_item = str(item.item).strip()

                if not clean_invoice_item:
                    continue

                # Log the item we're trying to match
                logger.debug(
                    f"Attempting to match item: '{clean_invoice_item}'")

                # Try to find a match - PRIORITY ORDER:
                # 1. Permanent mappings (with or without sheet names)
                # 2. Temporary mappings (only if no permanent mapping exists)
                matched_mapping = None
                match_source = None

                # First: Check permanent mappings (exact match only)
                if clean_invoice_item in mappings_lookup:
                    matched_mapping = mappings_lookup[clean_invoice_item]
                    match_source = "permanent"

                    # Check if this is a mapping without sheet name
                    if clean_invoice_item in mappings_without_sheet:
                        match_source = "permanent_no_sheet"

                # Second: If no permanent mapping, check temporary mappings (exact match only)
                elif clean_invoice_item in temp_lookup:
                    matched_mapping = temp_lookup[clean_invoice_item]
                    match_source = "temporary"

                if matched_mapping:
                    old_status = item.mpi_item or "Empty"

                    if match_source == "permanent" or match_source == "permanent_no_sheet":
                        # Apply permanent mapping
                        item.mpi_item = matched_mapping.mpi_code
                        item.mpi_description = matched_mapping.description
                        item.sheet_name = matched_mapping.google_sheet_name or ""

                        if match_source == "permanent_no_sheet":
                            updated_from_no_sheet += 1
                            logger.info(
                                f"UIDI override (no sheet): {clean_invoice_item} -> {matched_mapping.mpi_code}")
                        else:
                            updated_from_permanent += 1
                            logger.info(
                                f"UIDI override: {clean_invoice_item} -> {matched_mapping.mpi_code}")

                    elif match_source == "temporary":
                        # Temporary mappings must ONLY assign sheet_name.
                        # Never touch mpi_item or mpi_description to avoid inconsistent states.
                        item.sheet_name = matched_mapping.sheet_name or ""
                        updated_from_temp += 1
                        logger.info(
                            f"UIDI override (temp): {clean_invoice_item} -> sheet: {matched_mapping.sheet_name} (mpi fields unchanged)")

                    updated_count += 1

                    # Log the update based on mapping type
                    if match_source == "temporary":
                        if old_status.startswith("UIDI"):
                            logger.info(
                                f"UIDI override (temp): {clean_invoice_item} -> sheet: {matched_mapping.sheet_name}")
                        elif old_status == "No Match":
                            logger.info(
                                f"No Match override (temp): {clean_invoice_item} -> sheet: {matched_mapping.sheet_name}")
                        else:
                            logger.info(
                                f"Item update (temp): {clean_invoice_item} -> sheet: {matched_mapping.sheet_name}")
                    else:
                        # Permanent mapping
                        if old_status.startswith("UIDI"):
                            logger.info(
                                f"UIDI override: {clean_invoice_item} -> {matched_mapping.mpi_code}")
                        elif old_status == "No Match":
                            logger.info(
                                f"No Match override: {clean_invoice_item} -> {matched_mapping.mpi_code}")
                        else:
                            logger.info(
                                f"Item update: {clean_invoice_item} -> {matched_mapping.mpi_code}")
                else:
                    no_match_found_count += 1
                    logger.debug(
                        f"No mapping found for item: '{clean_invoice_item}'")

            db.commit()

            logger.info(
                f"UIDI update completed: {updated_count} items updated, {no_match_found_count} items remain unmatched")
            logger.info(
                f"Breakdown: {updated_from_permanent} from permanent mappings, {updated_from_temp} from temporary mappings, {updated_from_no_sheet} from mappings without sheet names")

            return {
                "status": "success",
                "message": f"Updated {updated_count} items with No Match / UIDI mappings",
                "updated_count": updated_count,
                "unmatched_count": no_match_found_count,
                "total_processed": len(no_match_items),
                "updated_from_permanent": updated_from_permanent,
                "updated_from_temp": updated_from_temp,
                "updated_from_no_sheet": updated_from_no_sheet
            }

        except Exception as e:
            logger.error(f"Error in UIDI update: {str(e)}")
            db.rollback()
            return {
                "status": "error",
                "message": f"Error in UIDI update: {str(e)}"
            }

    def update_all_unmapped_items(self) -> Dict[str, Any]:
        """
        Comprehensive update for ALL unmapped items.

        This method will:
        1. Find ALL items that are unmapped (regardless of their current status)
        2. First try to match with permanent mappings (exact match)
        3. Then try to match with temporary mappings (exact match)
        4. Update items with the best available mapping

        Returns:
            Dict with comprehensive update operation details
        """
        from mpi_backend.database.controllers import GoogleSheetSyncController

        # Check if a sync task is already running
        status = GoogleSheetSyncController.get_sync_status()
        if status["is_running"] and status["current_operation"] != "update_all_unmapped":
            operation_display = {
                "sync": "Synchronization",
                "update_no_match_uidi": "No Match / UIDI Update",
                "update_all": "Full Update",
                "update_all_unmapped": "All Unmapped Items Update"
            }.get(status['current_operation'], status['current_operation'])

            logger.info(
                f"Cannot start operation: {operation_display} is already in progress")
            return {
                "status": "error",
                "message": f"Cannot start operation: {operation_display} is already in progress"
            }

        db = self._get_db_session()
        return self._perform_comprehensive_unmapped_update(db)

    def _perform_comprehensive_unmapped_update(self, db):
        """Helper method to perform comprehensive unmapped items update"""
        try:
            # Get ALL items that are unmapped - comprehensive query
            unmapped_items = db.query(InvoiceItem).filter(
                or_(
                    # Items with no MPI item assigned
                    InvoiceItem.mpi_item.is_(None),
                    InvoiceItem.mpi_item == "",
                    InvoiceItem.mpi_item == "No Match",
                    InvoiceItem.mpi_item.like("UIDI%"),
                    # Items with no sheet name (even if they have MPI item)
                    InvoiceItem.sheet_name.is_(None),
                    InvoiceItem.sheet_name == "",
                    # Items that might have sheet name but no proper MPI mapping
                    and_(
                        InvoiceItem.sheet_name.isnot(None),
                        InvoiceItem.sheet_name != "",
                        or_(
                            InvoiceItem.mpi_item.is_(None),
                            InvoiceItem.mpi_item == "",
                            InvoiceItem.mpi_item == "No Match",
                            InvoiceItem.mpi_item.like("UIDI%")
                        )
                    )
                )
            ).all()

            if not unmapped_items:
                logger.info("No unmapped items found for comprehensive update")
                return {
                    "status": "success",
                    "message": "No unmapped items found"
                }

            logger.info(
                f"Found {len(unmapped_items)} unmapped items for comprehensive update")

            # Get valid permanent mappings
            valid_mappings = db.query(ItemsMapping).filter(
                ~ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.mpi_code != "No Match",
                ItemsMapping.mpi_code != "No Match / UIDI",
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != ""
            ).all()

            if not valid_mappings:
                logger.info(
                    "No valid permanent mappings available for comprehensive update")
                return {
                    "status": "error",
                    "message": "No valid permanent mappings available"
                }

            logger.info(
                f"Found {len(valid_mappings)} valid permanent mappings for matching")

            # Get temporary mappings
            from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
            temp_mappings = db.query(TempItemMapping).all()
            logger.info(
                f"Found {len(temp_mappings)} temporary mappings for additional matching")

            # Create comprehensive lookup dictionaries
            permanent_lookup = {}
            temp_lookup = {}
            mappings_without_sheet = {}

            # Build permanent mappings lookup
            for mapping in valid_mappings:
                # Validate this is truly a permanent mapping
                if is_temporary_mapping(mapping.mpi_code, mapping.description):
                    logger.warning(
                        f"Skipping temporary mapping in permanent table: {mapping.mpi_code}")
                    continue

                clean_mapping_item = mapping.supplier_item_ids.strip()
                if clean_mapping_item:
                    permanent_lookup[clean_mapping_item] = mapping

                    # Track mappings without sheet names
                    if not mapping.google_sheet_name or mapping.google_sheet_name.strip() == "":
                        mappings_without_sheet[clean_mapping_item] = mapping

            # Build temporary mappings lookup (don't override permanent)
            for temp_mapping in temp_mappings:
                if temp_mapping.original_item is None:
                    continue

                clean_temp_item = temp_mapping.original_item.strip()
                if clean_temp_item and clean_temp_item not in permanent_lookup:
                    temp_lookup[clean_temp_item] = temp_mapping

            logger.info(
                f"Created comprehensive lookup: {len(permanent_lookup)} permanent, {len(temp_lookup)} temporary mappings")
            logger.info(
                f"Found {len(mappings_without_sheet)} permanent mappings without sheet names")

            # Process ALL unmapped items
            updated_count = 0
            updated_from_permanent = 0
            updated_from_temp = 0
            updated_from_no_sheet = 0
            no_match_found_count = 0
            items_with_sheet_but_no_mpi = 0

            for item in unmapped_items:
                # Clean the invoice item for comparison
                clean_invoice_item = str(item.item).strip()

                if not clean_invoice_item:
                    continue

                # Track original state for logging
                original_mpi = item.mpi_item or "Empty"
                original_sheet = item.sheet_name or "Empty"
                had_sheet_but_no_mpi = (original_sheet != "Empty" and
                                        (original_mpi == "Empty" or original_mpi == "No Match" or original_mpi.startswith("UIDI")))

                # Try to find a match - PRIORITY ORDER:
                # 1. Permanent mappings (with or without sheet names)
                # 2. Temporary mappings (only if no permanent mapping exists)
                matched_mapping = None
                match_source = None

                # First: Check permanent mappings (exact match only)
                if clean_invoice_item in permanent_lookup:
                    matched_mapping = permanent_lookup[clean_invoice_item]
                    match_source = "permanent"

                    # Check if this is a mapping without sheet name
                    if clean_invoice_item in mappings_without_sheet:
                        match_source = "permanent_no_sheet"

                # Second: If no permanent mapping, check temporary mappings (exact match only)
                elif clean_invoice_item in temp_lookup:
                    matched_mapping = temp_lookup[clean_invoice_item]
                    match_source = "temporary"

                if matched_mapping:
                    # Apply the mapping based on source
                    if match_source == "permanent" or match_source == "permanent_no_sheet":
                        # Apply permanent mapping
                        item.mpi_item = matched_mapping.mpi_code
                        item.mpi_description = matched_mapping.description
                        item.sheet_name = matched_mapping.google_sheet_name or ""

                        if match_source == "permanent_no_sheet":
                            updated_from_no_sheet += 1
                            logger.info(
                                f"Comprehensive update (no sheet): {clean_invoice_item} -> {matched_mapping.mpi_code}")
                        else:
                            updated_from_permanent += 1
                            logger.info(
                                f"Comprehensive update (permanent): {clean_invoice_item} -> {matched_mapping.mpi_code}")

                    elif match_source == "temporary":
                        # Temporary mappings must ONLY assign sheet_name.
                        # Never modify mpi_item or mpi_description.
                        item.sheet_name = matched_mapping.sheet_name or ""
                        updated_from_temp += 1
                        logger.info(
                            f"Comprehensive update (temp): {clean_invoice_item} -> sheet: {matched_mapping.sheet_name} (mpi fields unchanged)")

                    updated_count += 1

                    # Special logging for items that had sheet but no MPI
                    if had_sheet_but_no_mpi:
                        items_with_sheet_but_no_mpi += 1
                        logger.info(
                            f"Fixed item with sheet but no MPI: {clean_invoice_item} (had sheet: {original_sheet})")

                else:
                    no_match_found_count += 1
                    if had_sheet_but_no_mpi:
                        items_with_sheet_but_no_mpi += 1
                        logger.debug(
                            f"No mapping found for item with sheet but no MPI: {clean_invoice_item} (sheet: {original_sheet})")

            # Commit all changes
            try:
                db.commit()
                logger.info(
                    f"Comprehensive update completed: {updated_count} items updated, {no_match_found_count} items remain unmatched")
                logger.info(
                    f"Breakdown: {updated_from_permanent} from permanent mappings, {updated_from_temp} from temporary mappings, {updated_from_no_sheet} from mappings without sheet names")
                logger.info(
                    f"Items with sheet but no MPI: {items_with_sheet_but_no_mpi}")

                return {
                    "status": "success",
                    "message": f"Comprehensive update completed: {updated_count} items updated, {no_match_found_count} items remain unmatched",
                    "updated_count": updated_count,
                    "no_match_found_count": no_match_found_count,
                    "updated_from_permanent": updated_from_permanent,
                    "updated_from_temp": updated_from_temp,
                    "updated_from_no_sheet": updated_from_no_sheet,
                    "items_with_sheet_but_no_mpi": items_with_sheet_but_no_mpi
                }

            except Exception as commit_error:
                db.rollback()
                logger.error(
                    f"Failed to commit comprehensive update: {str(commit_error)}")
                raise

        except Exception as e:
            db.rollback()
            logger.error(
                f"Failed to perform comprehensive unmapped update: {str(e)}")
            raise

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

            logger.info(
                f"Cannot start Update All Mappings: A {operation_display} operation is already running")
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
            # Fetch ALL mappings from supplier table - this should apply everything in the mapping table
            # But when a mapping is temporary (UIDI/No Match/etc.), we will only assign sheet_name
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
                    logger.warning(
                        f"Skipping mapping with empty MPI code: {mapping.supplier_item_ids}")
                    continue

                # Keep all mappings, but handle temporary ones safely during application below
                valid_mappings.append(mapping)

            if not valid_mappings:
                logger.info("No valid mappings found to apply after filtering")
                return {
                    "status": "success",
                    "message": "No valid mappings found to apply after filtering"
                }

            # Get all invoice items for efficient processing
            all_invoice_items = db.query(InvoiceItem).all()
            logger.info(
                f"Processing {len(valid_mappings)} mappings against {len(all_invoice_items)} invoice items")

            # Process each mapping to update related invoice items
            total_updated_count = 0
            total_mappings_processed = 0

            for mapping in valid_mappings:
                total_mappings_processed += 1
                try:
                    # Strip whitespace from mapping item
                    clean_mapping_item = mapping.supplier_item_ids.strip()

                    if not clean_mapping_item:
                        logger.warning(
                            f"Skipping mapping with empty supplier_item_ids: {mapping.mpi_code}")
                        continue

                    # Find matches using exact comparison
                    matching_items = []

                    for invoice_item in all_invoice_items:
                        # Clean the invoice item by stripping whitespace
                        clean_invoice_item = invoice_item.item.strip()

                        if not clean_invoice_item:
                            continue

                        # Exact match only - no suffix variations to avoid business logic issues
                        if clean_invoice_item == clean_mapping_item:
                            matching_items.append(invoice_item)

                    if not matching_items:
                        logger.debug(
                            f"No matching items found for mapping: {clean_mapping_item}")
                        continue

                    # Update all matching items
                    item_updated_count = 0
                    for item in matching_items:
                        # Apply the mapping from supplier table
                        old_mpi_item = item.mpi_item or "Empty"
                        old_sheet_name = item.sheet_name or "Empty"

                        if is_temporary_mapping(mapping.mpi_code, mapping.description):
                            # Temporary mapping: only update sheet_name, keep MPI fields unchanged
                            item.sheet_name = mapping.google_sheet_name or ""
                            item_updated_count += 1
                            logger.debug(
                                f"Applied TEMP mapping to item {item.id}: item='{item.item}', "
                                f"mpi_item preserved='{old_mpi_item}', sheet_name: '{old_sheet_name}' -> '{mapping.google_sheet_name}'"
                            )
                        else:
                            # Permanent mapping: update MPI fields and sheet_name
                            item.mpi_item = mapping.mpi_code
                            item.mpi_description = mapping.description
                            item.sheet_name = mapping.google_sheet_name or ""
                            item_updated_count += 1
                            logger.debug(
                                f"Updated item {item.id}: item='{item.item}', "
                                f"mpi_item: '{old_mpi_item}' -> '{mapping.mpi_code}', "
                                f"sheet_name: '{old_sheet_name}' -> '{mapping.google_sheet_name}'"
                            )

                    total_updated_count += item_updated_count
                    logger.info(
                        f"Updated {item_updated_count} items for mapping "
                        f"{mapping.supplier_item_ids} -> {mapping.mpi_code}"
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
        Propagate mapping changes to all matching InvoiceItems with exact matching.
        Now includes validation to ensure we don't propagate temporary mappings.

        Updates all InvoiceItem records that:
        1. Have the same item number (item field) - with exact comparison
        2. Only if the new mapping is NOT a temporary placeholder

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
                logger.warning(
                    f"Skipping propagation of temporary mapping: {new_mpi_code}")
                return

            # Get all invoice items for matching
            all_invoice_items = db.query(InvoiceItem).all()

            # Clean the mapping item
            clean_mapping_item = item_number.strip()

            if not clean_mapping_item:
                logger.warning(
                    f"Cannot propagate mapping changes: empty item_number")
                return

            # Find matching items using exact comparison
            matching_items = []

            for invoice_item in all_invoice_items:
                # Clean the invoice item by stripping whitespace
                clean_invoice_item = invoice_item.item.strip()

                if not clean_invoice_item:
                    continue

                # Exact match only - no suffix variations to avoid business logic issues
                if clean_invoice_item == clean_mapping_item:
                    matching_items.append(invoice_item)

            if not matching_items:
                logger.info(
                    f"No matching invoice items found for {item_number}")
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

                # Assign account based on new mapping/sheet if applicable
                try:
                    self._assign_account_for_item(
                        db=db,
                        item_obj=item,
                        sheet_name=sheet_name,
                        mpi_item=new_mpi_code,
                    )
                except Exception:
                    pass
                updated_count += 1

                if was_uidi:
                    uidi_override_count += 1
                    logger.info(
                        f"Overrode UIDI item {item.item} with permanent mapping {new_mpi_code}")

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

    def _determine_account_letter(self, db: Session, sheet_name: Optional[str], current_account: Optional[str], mpi_item: Optional[str]) -> str:
        """
        Determine account letter (M/E) from sheet_name and mpi_item.
        - Preserve 'A'
        - UIDI categories → M/E
        - Exact ItemClassification by sheet_name → M/E; skip 'L'
        - Fuzzy fallback via ItemClassificationController.get_classification → map to M/E
        """
        try:
            current = (current_account or '').strip()
            if current.upper() == 'A':
                return current

            # UIDI mapping based on mpi_item
            key = (mpi_item or '').strip().upper()
            if key:
                uidi_map = {
                    'UIDI-JOB MATERIALS PURCHASED': 'M',
                    'UIDI JOB MATERIAL': 'M',
                    'UIDI-JOB EQUIPMENT': 'E',
                    'UIDI-SPRINKLER SPECIALTY ITEM': 'M',
                    'UIDI-DRAINAGE MATERIAL': 'M',
                }
                if key in uidi_map:
                    return uidi_map[key]

            # Exact classification by sheet_name
            sheet = (sheet_name or '').strip()
            if sheet:
                try:
                    from mpi_backend.database.models.ItemClassification import ItemClassification as IC
                    row = db.query(IC).filter(IC.item == sheet).first()
                    if row:
                        cat = (row.category or '').strip().upper()
                        if cat in ('M', 'E'):
                            return cat
                except Exception:
                    pass

                # Fuzzy fallback using controller
                try:
                    from mpi_backend.database.controllers.ItemClassification import ItemClassificationController
                    icc = ItemClassificationController(db)
                    qb_account = icc.get_classification(sheet)
                    qb_lower = (qb_account or '').lower()
                    if 'job materials purchased' in qb_lower:
                        return 'M'
                    if 'job equipment' in qb_lower:
                        return 'E'
                except Exception:
                    pass

            return current
        except Exception:
            return (current_account or '').strip()

    def _assign_account_for_item(self, db: Session, item_obj, sheet_name: Optional[str], mpi_item: Optional[str]) -> None:
        """
        Assign account letter to a single invoice item if missing or if it's a long QB path.
        Never overwrite explicit 'A'.
        """
        current = (getattr(item_obj, 'account', '') or '').strip()
        if current.upper() == 'A':
            return
        # Normalize long QB paths to letters
        low = current.lower()
        if current and low:
            if 'job materials purchased' in low:
                if current != 'M':
                    item_obj.account = 'M'
                return
            if 'job equipment' in low:
                if current != 'E':
                    item_obj.account = 'E'
                return

        # If empty or not mapped, determine from classification
        if not current or current not in ('M', 'E'):
            letter = self._determine_account_letter(db, sheet_name, current, mpi_item)
            if letter in ('M', 'E') and letter != current:
                item_obj.account = letter

    def _get_db_session(self):
        """Get a database session object, whether db_context is a factory or session."""
        if callable(self.db_context):
            # This is a session factory, return a new session
            return self.db_context()
        else:
            # This is already a session object
            return self.db_context

    def _validate_supplier_id(self, db: Session, supplier_id: str) -> bool:
        """
        Validate that a supplier ID exists in the database.

        Args:
            db: Database session
            supplier_id: Supplier ID to validate

        Returns:
            True if supplier exists, False otherwise
        """
        try:
            from mpi_backend.database.models.Suppliers import Supplier
            supplier = db.query(Supplier).filter_by(
                id=int(supplier_id)).first()
            return supplier is not None
        except Exception as e:
            logger.error(
                f"Error validating supplier ID {supplier_id}: {str(e)}")
            return False

    def _get_available_supplier_ids(self, db: Session) -> List[int]:
        """
        Get list of available supplier IDs in the database.

        Args:
            db: Database session

        Returns:
            List of available supplier IDs
        """
        try:
            from mpi_backend.database.models.Suppliers import Supplier
            suppliers = db.query(Supplier).all()
            return [supplier.id for supplier in suppliers]
        except Exception as e:
            logger.error(f"Error getting available supplier IDs: {str(e)}")
            return []

    def get_mapping_stats(self) -> Dict[str, Any]:
        """
        Get statistics about item mappings.

        Returns:
            Dictionary with mapping statistics
        """
        db = self._get_db_session()
        total_mappings = db.query(ItemsMapping).count()

        # Get unique sheet names
        sheet_names = db.query(ItemsMapping.google_sheet_name).distinct().all()
        unique_sheets = [name[0] for name in sheet_names if name[0]]

        # Get mappings per sheet
        sheet_counts = {}
        for sheet_name in unique_sheets:
            count = db.query(ItemsMapping).filter(
                ItemsMapping.google_sheet_name == sheet_name
            ).count()
            sheet_counts[sheet_name] = count

        # Get mapping types
        permanent_mappings = db.query(ItemsMapping).filter(
            ItemsMapping.mpi_code.isnot(None)
        ).count()

        # Count temporary mappings (those without mpi_code)
        temporary_mappings = db.query(ItemsMapping).filter(
            ItemsMapping.mpi_code.is_(None)
        ).count()

        # Count invalid mappings (those without supplier_item_ids)
        invalid_mappings = db.query(ItemsMapping).filter(
            ItemsMapping.supplier_item_ids.is_(None)
        ).count()

        stats = {
            "total_mappings": total_mappings,
            "unique_sheets": len(unique_sheets),
            "sheet_names": unique_sheets,
            "mappings_per_sheet": sheet_counts,
            "permanent_mappings": permanent_mappings,
            "temporary_mappings": temporary_mappings,
            "invalid_mappings": invalid_mappings
        }

        # Update stats in the JSON file
        stats_manager = MappingStatsManager()
        stats_manager.update_item_mapping_stats(stats)

        return stats
