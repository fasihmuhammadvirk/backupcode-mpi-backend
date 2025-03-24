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

    def get_items_mappings_by_supplier_id(self, supplier_id: int, limit: int = 100, offset: int = 0):
        """
        Retrieve a list of item mappings for a specific supplier with a limit for large dataset
        to prevent memory overloading.

        Args:
            supplier_id (int): The ID of the supplier to filter item mappings.
            limit (int, optional): The maximum number of records to return. Defaults to 100.
            offset (int, optional): The number of records to skip before starting to return records. Defaults to 0.

        Returns:
            list: A list of dictionaries, each containing item mapping details such as
                  'type', 'description', 'mpi_code', 'supplier_item_ids', and 'supplier_id'.
        """
        query_result = (
            self.db_context.query(ItemsMapping)
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
        query_result = self.db_context.query(ItemsMapping).all()

        data = {
            item.mpi_code: {"type": item.google_sheet_name, "mpi_description": item.description}
            for item in query_result
        }
        return data

    def update_mapping(self, supplier_id: str, mapping_data: dict):
        existing_mapping = self.db_context.query(ItemsMapping).filter_by(supplier_id=supplier_id,
                                                            supplier_item_ids=mapping_data["supplier_item_ids"]).first()
        if existing_mapping:
            for key, value in mapping_data.items():
                setattr(existing_mapping, key, value)
        else:
            db_mapping = ItemsMapping(**mapping_data, supplier_id=supplier_id)
            self.db_context.add(db_mapping)
        self.db_context.commit()
