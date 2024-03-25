from mpi_backend.database.models import ItemsMapping
import pandas as pd


class ItemsMappingController:
    def __init__(self, db):
        self.db_context = db

    def get_items_mappings(self):
        with self.db_context() as db:
            query_result = db.query(ItemsMapping).all()
            data = [(item.google_sheet_name, item.mpi_code, item.description, item.supplier_item_ids, item.supplier_id) for item in query_result]
            columns = ['google_sheet_name', 'mpi_code', 'description','supplier_item_ids','supplier_id']
            items_mappings = pd.DataFrame(data,columns= columns)
            return items_mappings
