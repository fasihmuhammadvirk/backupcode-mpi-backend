from mpi_backend.database.models import TempItemMapping
import pandas as pd


class TempItemsMappingController:
    def __init__(self, db):
        self.db_context = db

    def get_temp_items_mappings(self):
        with self.db_context() as db:
            query_result = db.query(TempItemMapping).all()

            data = [(item.original_item_number, item.description, item.temporary_item_number) for item in query_result]
            columns = ['original_item_number', 'description', 'temporary_item_number']
            temp_items_mappings = pd.DataFrame(data,columns=columns)
            return temp_items_mappings
