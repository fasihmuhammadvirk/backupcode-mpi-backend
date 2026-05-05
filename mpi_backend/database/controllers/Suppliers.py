from sqlalchemy import exists, or_, select

from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.database.models.SupplierEmailPattern import SupplierEmailPattern
from mpi_backend.utils.supplier_suffix_manager import (
    get_processable_supplier_names,
    get_unknown_supplier,
)

# The Unknown Supplier is used as a default placeholder where needed while the pipeline determines the supplier but if
# we are still unable to determine the supplier, we should expect to have the invoice to reference the "Unknown supplier".
# Previously, we had BMW as the default supplier but that caused inconsistencies in the system so we have introduced
# the "Unknown Supplier" to fix that.
# In dbt we also have a fallback to "Unknown Supplier"
UNKNOWN_SUPPLIER_ID = 0

class SupplierResult:
    """Simple class to hold supplier data without requiring full ORM model"""
    def __init__(self, id, supplier_name):
        self.id = id
        self.supplier_name = supplier_name


class SupplierController:
    def __init__(self, db):
        self.db = db

    def get_all_suppliers(self):
        try:
            has_no_patterns = ~exists(
                select(SupplierEmailPattern.id)
                .where(SupplierEmailPattern.supplier_id == Supplier.id)
                .correlate(Supplier)
            )
            has_active_pattern = exists(
                select(SupplierEmailPattern.id)
                .where(
                    SupplierEmailPattern.supplier_id == Supplier.id,
                    SupplierEmailPattern.is_active.is_(True),
                )
                .correlate(Supplier)
            )

            suppliers = (
                self.db.query(Supplier.id, Supplier.supplier_name)
                .where(Supplier.id != UNKNOWN_SUPPLIER_ID)
                .where(Supplier.is_subject_resolved.is_(False))
                .where(or_(has_no_patterns, has_active_pattern))
                .all()
            )
            return [SupplierResult(id=supplier_id, supplier_name=supplier_name)
                    for supplier_id, supplier_name in suppliers]
        except Exception as e:
            print(f"Error Getting Suppliers: {e}")
            return None

    def get_supplier_by_id(self,supplier_id):
        try:
            # Query only supplier_name column to avoid suffix column error
            result = self.db.query(Supplier.supplier_name).filter(Supplier.id == supplier_id).first()
            return result[0] if result else None
        except Exception as e:
            print(f"Error Getting Suppliers With ID: {e}")
            return None

    def get_supplier_name(self, supplier_name):
        try:
            # Query only id column to avoid suffix column error
            result = self.db.query(Supplier.id).filter(Supplier.supplier_name == supplier_name).first()
            return result[0] if result else None
        except Exception as e:
            print(f"Error Getting Suppliers With ID: {e}")
            return None

    def populate_suppliers(self):
        try:
            existing_names = {
                name for (name,) in self.db.query(Supplier.supplier_name).all()
            }

            unknown_id, unknown_name = get_unknown_supplier()
            if unknown_name not in existing_names:
                self.db.add(Supplier(id=unknown_id, supplier_name=unknown_name))

            for supplier_name in get_processable_supplier_names():
                if supplier_name not in existing_names:
                    self.db.add(Supplier(supplier_name=supplier_name))

            self.db.commit()
            print("Suppliers populated successfully.")
        except Exception as e:
            self.db.rollback()
            print(f"Error Populating Supplier Table: {e}")
