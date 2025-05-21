from mpi_backend.database.models import ItemsMapping, InvoiceItem
import pandas as pd
import logging
from typing import Dict, Any
from sqlalchemy import or_

from mpi_backend.utils.export_utils import extract_supplier_id
from mpi_backend.database import SessionLocal

# Set up logging
logger = logging.getLogger(__name__)


class ItemsMappingController:
    def __init__(self, db):
        self.db_context = db

    @classmethod
    def execute_update_all_mappings_task(cls, db=None):
        """
        Execute the update all mappings task with proper session management.
        
        Args:
            db: Database session. If None, a new session is created.
            
        Returns:
            Dict with update operation details
        """
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
            
        # If db is not provided, create a new session
        if db is None:
            db_session = SessionLocal()
            try:
                mapping_controller = cls(db_session)
                return mapping_controller.update_all_mappings()
            finally:
                db_session.close()
        else:
            mapping_controller = cls(db)
            return mapping_controller.update_all_mappings()

    def get_items_mappings(self):
        # Check if db_context is callable (session factory) or a Session object
        if callable(self.db_context):
            with self.db_context() as db:
                query_result = db.query(ItemsMapping).all()
                data = [(item.google_sheet_name, item.mpi_code, item.description, 
                         item.supplier_item_ids, item.supplier_id) 
                        for item in query_result]
                columns = ['google_sheet_name', 'mpi_code', 'description',
                           'supplier_item_ids', 'supplier_id']
                items_mappings = pd.DataFrame(data, columns=columns)
                return items_mappings
        else:
            # Direct session object
            query_result = self.db_context.query(ItemsMapping).all()
            data = [(item.google_sheet_name, item.mpi_code, item.description, 
                     item.supplier_item_ids, item.supplier_id) 
                    for item in query_result]
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
        
        query_result = (
            db.query(ItemsMapping)
            .filter_by(supplier_id=supplier_id)
            .limit(limit)
            .offset(offset)
            .all()  # Fetch as a list instead of yielding
        )

        return [
            {
                "type": item.google_sheet_name,
                "description": item.description,
                "mpi_code": item.mpi_code,
                "supplier_item_ids": item.supplier_item_ids,
                "supplier_id": item.supplier_id
            }
            for item in query_result
        ]

    def get_items_mappings_by_mpi_type(self):
        db = self._get_db_session()
        query_result = db.query(ItemsMapping).all()

        data = {
            item.mpi_code: {
                "type": item.google_sheet_name, 
                "mpi_description": item.description
            }
            for item in query_result
        }
        return data

    def update_mapping(self, supplier_id: str, mapping_data: dict):
        """
        Update or create a mapping entry and propagate changes to related 
        InvoiceItems.
        
        Args:
            supplier_id (str): The supplier ID for the mapping
            mapping_data (dict): Mapping data containing mpi_code, description, etc.
        """
        db = self._get_db_session()
        
        # Keep track of whether this is an update or a new entry
        is_update = False
        old_mpi_code = None
        old_description = None
        
        # Check if mapping already exists
        existing_mapping = db.query(ItemsMapping).filter_by(
            supplier_id=supplier_id,
            supplier_item_ids=mapping_data["supplier_item_ids"]
        ).first()
        
        if existing_mapping:
            is_update = True
            old_mpi_code = existing_mapping.mpi_code
            old_description = existing_mapping.description
            
            # Update existing mapping
            for key, value in mapping_data.items():
                setattr(existing_mapping, key, value)
        else:
            # Create new mapping
            db_mapping = ItemsMapping(**mapping_data, supplier_id=supplier_id)
            db.add(db_mapping)
        
        # Commit the changes to the mapping
        db.commit()
        
        # If this was an update and the mpi_code or description changed,
        # propagate the changes to related InvoiceItems
        if is_update and (
            old_mpi_code != mapping_data.get("mpi_code") or 
            old_description != mapping_data.get("description")
        ):
            try:
                self._propagate_mapping_changes(
                    db, 
                    supplier_id,
                    mapping_data["supplier_item_ids"],
                    mapping_data.get("mpi_code", ""),
                    mapping_data.get("description", ""),
                    mapping_data.get("google_sheet_name", "")
                )
            except Exception as e:
                logger.error(f"Failed to propagate mapping changes: {str(e)}")

    def update_invalid_mappings(self) -> Dict[str, Any]:
        """
        Update all items with No Match / UIDI mappings by finding matches in the 
        ItemsMapping table.
        
        Returns:
            Dict with status and count of updated items
        """
        # Check if a sync task is already running
        from mpi_backend.database.controllers import GoogleSheetSyncController
        status = GoogleSheetSyncController.get_sync_status()
        
        if status["is_running"] and status["current_operation"] != "update_invalid":
            # Convert operation name to user-friendly format
            operation_display = {
                "sync": "Sync",
                "update_invalid": "Update No Match / UIDI Mappings",
                "update_all": "Update All Mappings"
            }.get(status['current_operation'], status['current_operation'])
            
            logger.info(f"Cannot start Update No Match / UIDI Mappings: A {operation_display} operation is already running")
            return {
                "status": "error",
                "message": f"Cannot start Update No Match / UIDI Mappings: A {operation_display} operation is already running"
            }
            
        try:
            db = self._get_db_session()
            
            # Get items with invalid mappings
            invalid_items = db.query(InvoiceItem).filter(
                or_(
                    InvoiceItem.mpi_item.ilike("no match"),
                    InvoiceItem.mpi_item.startswith("UIDI")
                )
            ).all()
            
            if not invalid_items:
                return {
                    "status": "success",
                    "message": "No invalid mappings found"
                }
            
            # Fetch all existing mappings
            mappings = db.query(ItemsMapping).all()
            
            # Create a lookup dictionary for efficient searching
            # Using supplier_item_ids and supplier_id as a compound key
            mapping_lookup = {}
            for mapping in mappings:
                key = (f"{mapping.supplier_item_ids.lower()}-"
                       f"{mapping.supplier_id}")
                mapping_lookup[key] = mapping
            
            # Update invalid items if mappings are found
            updated_count = 0
            
            for item in invalid_items:
                # Try to find match by item number and supplier
                supplier_id, _ = extract_supplier_id(item.vendor)
                
                # Look for a match in the mappings
                key = (f"{item.item.lower()}-{supplier_id}" 
                       if item.item else "")
                mapping = mapping_lookup.get(key)
                
                if mapping:
                    # Update the item with the mapping information
                    item.mpi_item = mapping.mpi_code
                    item.mpi_description = mapping.description
                    item.sheet_name = mapping.google_sheet_name
                    updated_count += 1
            
            # Commit the changes
            db.commit()
            
            return {
                "status": "success",
                "message": f"{updated_count} items updated"
            }
        
        except Exception as e:
            logger.error(f"Failed to update invalid mappings: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to update invalid mappings: {str(e)}"
            }

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
            db = self._get_db_session()
            
            # Fetch all mappings
            mappings = db.query(ItemsMapping).all()
            
            if not mappings:
                logger.info("No mappings found to apply")
                return {
                    "status": "success",
                    "message": "No mappings found to apply"
                }
            
            # Process each mapping to update related invoice items
            total_updated_count = 0
            total_mappings_processed = 0
            
            for mapping in mappings:
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
                    matching_items = db.query(InvoiceItem).filter(
                        InvoiceItem.item == mapping.supplier_item_ids,
                        InvoiceItem.vendor.contains(supplier.supplier_name)
                    ).all()
                    
                    if not matching_items:
                        continue
                        
                    # Update all matching items
                    item_updated_count = 0
                    for item in matching_items:
                        item.mpi_item = mapping.mpi_code
                        item.mpi_description = mapping.description
                        item.sheet_name = mapping.google_sheet_name
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
            if db and db.is_active:
                db.rollback()
            return {
                "status": "error",
                "message": f"Failed to update all mappings: {str(e)}"
            }
    
    def _propagate_mapping_changes(self, db, supplier_id, item_number, 
                                  new_mpi_code, new_description, sheet_name):
        """
        Propagate mapping changes to all matching InvoiceItems.
        
        Updates all InvoiceItem records that:
        1. Have the same item number (item field)
        2. Belong to the same supplier (determined from vendor field)
        
        Args:
            db: Database session
            supplier_id (str): Supplier ID
            item_number (str): Item identifier/number
            new_mpi_code (str): New MPI code to set
            new_description (str): New description to set
            sheet_name (str): Sheet name to set
        """
        try:
            # Get vendor name from supplier_id
            from mpi_backend.database.models import Supplier
            supplier = db.query(Supplier).filter_by(id=supplier_id).first()
            
            if not supplier:
                logger.warning(f"Supplier with ID {supplier_id} not found")
                return
                
            # Find all invoice items that match this item number and supplier
            matching_items = db.query(InvoiceItem).filter(
                InvoiceItem.item == item_number,
                InvoiceItem.vendor.contains(supplier.supplier_name)
            ).all()
            
            if not matching_items:
                logger.info(f"No matching invoice items found for {item_number}")
                return
                
            # Update all matching items
            updated_count = 0
            for item in matching_items:
                item.mpi_item = new_mpi_code
                item.mpi_description = new_description
                item.sheet_name = sheet_name
                updated_count += 1
                
            # Commit the changes
            db.commit()
            logger.info(f"Updated {updated_count} invoice items with new mapping data")
            
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
