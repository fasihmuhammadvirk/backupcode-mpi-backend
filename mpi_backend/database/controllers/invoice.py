from datetime import datetime
from mpi_backend.database.models import Invoice


class InvoiceController:
    def __init__(self, db):
        self.db_context = db

    def insert_invoice(self, date, filename, supplier, status, storage_path):
        date = datetime.strptime(date, '%m/%d/%Y')
        new_invoice = Invoice(date=date, filename=filename, supplier=supplier, status=status, storage_path=storage_path)
        with self.db_context() as db:
            db.add(new_invoice)
            db.commit()
            db.refresh(new_invoice)  # to get the newly generated UUID
        return new_invoice
