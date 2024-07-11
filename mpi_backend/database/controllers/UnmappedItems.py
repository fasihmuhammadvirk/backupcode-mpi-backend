from mpi_backend.database.models import UnmappedItems
import pandas as pd


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

    def is_item_code_present(self,item_code):
        try:
            with self.db_context() as db:
                is_present = db.query(UnmappedItems).filter_by(supplier_item_ids=item_code).first()
            if is_present:
                return True
            else:
                return False
        except Exception as e:
            print(f'Unmapped item-{item_code} could not be looked up in db ->{e}')
            return False
