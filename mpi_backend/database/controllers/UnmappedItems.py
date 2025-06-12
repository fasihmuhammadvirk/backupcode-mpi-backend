from mpi_backend.database.models import UnmappedItems
import pandas as pd
from mpi_backend.utils.item_utils import clean_supplier_suffix


class UnmappedItemsController:
    def __init__(self, db):
        self.db_context = db

    def get_items_mappings(self):
        with self.db_context() as db:
            query_result = db.query(UnmappedItems).all()
            data = [(item.google_sheet_name, item.mpi_code, item.description, item.supplier_item_ids, item.supplier_id) for item in query_result]
            columns = ['google_sheet_name', 'mpi_code', 'description','supplier_item_ids','supplier_id']
            items_mappings = pd.DataFrame(data,columns= columns)
            return items_mappings

    def insert_unmapped_item(self, item_code, description, supplier_id):
        with self.db_context() as db:
            new_item = UnmappedItems(
                google_sheet_name='',
                mpi_code='',
                description=description,
                supplier_item_ids=item_code,
                supplier_id=supplier_id
            )
            db.add(new_item)
            db.commit()

    def is_item_code_present(self, item_code, supplier_id=None):
        """
        Check if an item code is present in unmapped items with supplier-specific suffix cleaning support.
        
        Args:
            item_code (str): Clean item code from invoice to check
            supplier_id (int, optional): Supplier ID for targeted suffix cleaning
            
        Returns:
            bool: True if item is present (with or without suffix), False otherwise
        """
        try:
            with self.db_context() as db:
                # Get all unmapped items
                all_unmapped = db.query(UnmappedItems).all()
                
                # Check clean invoice item against both original and cleaned DB data
                for unmapped_item in all_unmapped:
                    # First try exact match (clean invoice vs DB item)
                    if unmapped_item.supplier_item_ids == item_code:
                        return True
                    # Then try clean invoice vs cleaned DB item
                    elif supplier_id and clean_supplier_suffix(unmapped_item.supplier_item_ids, supplier_id) == item_code:
                        return True
                        
                return False
                
        except Exception as e:
            print(f'Unmapped item-{item_code} could not be looked up in db ->{e}')
            return False
