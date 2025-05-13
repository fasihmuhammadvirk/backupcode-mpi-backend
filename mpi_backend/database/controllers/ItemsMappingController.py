from mpi_backend.database.models import ItemsMapping, InvoiceItem
import pandas as pd
import logging

# Set up logging
logger = logging.getLogger(__name__)


class ItemsMappingController:
    def __init__(self, db):
        self.db_context = db

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
