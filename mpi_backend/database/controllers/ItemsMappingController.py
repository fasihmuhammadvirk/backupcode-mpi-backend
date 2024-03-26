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

    def get_items_mappings_by_supplier_id(self,supplier_id):
        query_result = self.db_context.query(ItemsMapping).filter_by(supplier_id=supplier_id).all()
        data = [
            {"google_sheet_name": item.google_sheet_name, "description": item.description, "mpi_code": item.mpi_code,
             "supplier_item_ids": item.supplier_item_ids, "supplier_id": item.supplier_id}
            for item in query_result
        ]
        return data

    def get_items_mappings_by_mpi_type(self):
        query_result = self.db_context.query(ItemsMapping).all()

        data = {
            item.mpi_code: {"type": item.google_sheet_name, "mpi_description": item.description}
            for item in query_result
        }
        return data
