from datetime import datetime
from mpi_backend.database.models import InvoiceItem


class InvoiceItemController:
    def __init__(self, db):
        self.db_context = db

    def insert_invoice_items(self, row, filename, invoice_id):
        new_item = InvoiceItem(
            filename=filename,
            sheet_name=row['Sheet Name'],
            invoice_id=invoice_id,
            item=row['Item'],
            description=row['Description'],
            qty=row['Qty'],
            cost=row['Cost'],
            amount=row['Amount'],
            date=datetime.strptime(row['Date'], '%m/%d/%Y'),
            ref_no=row['Ref NO'],
            po_number=row['PO #'],
            customer_job=row['Customer Job'],
            bill=row['Bill'],
            vendor=row['Vendor'],
            class_=row['Class'],
            memo=row['Memo'],
            buyer=row['Buyer']
        )
        with self.db_context() as db:
            db.add(new_item)
            db.commit()

    def invoice_exists(self, reference_no):
        with self.db_context() as db:
            matched_invoice = db.query(InvoiceItem).filter_by(ref_no=reference_no).first()
            return matched_invoice is not None
