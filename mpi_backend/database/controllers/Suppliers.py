from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.config import PROCESSABLE_SUPPLIERS


class SupplierController:
    def __init__(self, db):
        self.db = db

    def get_all_suppliers(self):
        try:
            suppliers = self.db.query(Supplier).all()
            return suppliers
        except Exception as e:
            print(f"Error Getting Suppliers: {e}")
            return None

    def get_supplier_by_id(self,supplier_id):
        try:
            supplier = self.db.query(Supplier).filter(Supplier.id == supplier_id).first()
            return supplier.supplier_name
        except Exception as e:
            print(f"Error Getting Suppliers With ID: {e}")
            return None

    def get_supplier_name(self, supplier_name):
        try:
            with self.db() as db:
                supplier = db.query(Supplier).filter(Supplier.supplier_name == supplier_name).first()
            return supplier.id
        except Exception as e:
            print(f"Error Getting Suppliers With ID: {e}")
            return None

    def populate_suppliers(self):
        try:
            if not self.db.query(Supplier).first():
                # Only Insert if table is empty
                for supplier_name in PROCESSABLE_SUPPLIERS:
                    supplier = Supplier(supplier_name=supplier_name)
                    self.db.add(supplier)
                self.db.commit()
                print("Suppliers inserted successfully.")
            else:
                print("Supplier table is not empty. Skipping insertion.")
        except Exception as e:
            self.db.rollback()
            print(f"Error Populating Supplier Table: {e}")
