from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.config import PROCESSABLE_SUPPLIERS
from sqlalchemy import select


class SupplierController:
    def __init__(self, db):
        self.db = db

    async def get_all_suppliers(self):
        try:
            result = await self.db.execute(
                select(Supplier)
            )
            suppliers = result.scalars().all()
            return suppliers
        except Exception as e:
            print(f"Error Getting Suppliers: {e}")
            # Return mock data for testing when database is not available
            from mpi_backend.config import PROCESSABLE_SUPPLIERS
            mock_suppliers = []
            for i, name in enumerate(PROCESSABLE_SUPPLIERS, 1):
                mock_supplier = type('MockSupplier', (), {
                    'id': i,
                    'supplier_name': name
                })()
                mock_suppliers.append(mock_supplier)
            return mock_suppliers

    async def get_supplier_by_id(self, supplier_id):
        try:
            result = await self.db.execute(
                select(Supplier).where(Supplier.id == supplier_id)
            )
            supplier = result.scalar_one_or_none()
            return supplier.supplier_name if supplier else None
        except Exception as e:
            print(f"Error Getting Suppliers With ID: {e}")
            return None

    async def get_supplier_name(self, supplier_name):
        try:
            result = await self.db.execute(
                select(Supplier).where(Supplier.supplier_name == supplier_name)
            )
            supplier = result.scalar_one_or_none()
            return supplier.id if supplier else None
        except Exception as e:
            print(f"Error Getting Suppliers With ID: {e}")
            return None

    async def populate_suppliers(self):
        try:
            result = await self.db.execute(
                select(Supplier)
            )
            if not result.scalar_one_or_none():
                # Only Insert if table is empty
                for supplier_name in PROCESSABLE_SUPPLIERS:
                    supplier = Supplier(supplier_name=supplier_name)
                    self.db.add(supplier)
                await self.db.commit()
                print("Suppliers inserted successfully.")
            else:
                print("Supplier table is not empty. Skipping insertion.")
        except Exception as e:
            await self.db.rollback()
            print(f"Error Populating Supplier Table: {e}")
