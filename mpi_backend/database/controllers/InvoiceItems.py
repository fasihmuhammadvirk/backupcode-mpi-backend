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

    def get_invoice_items(self, invoice_id= None):
        query = self.db_context.query(InvoiceItem)
        if invoice_id:
            query = query.filter(InvoiceItem.invoice_id == invoice_id)
        items = query.all()

        invoices_items= []
        for invoice_item in items:
            item= {
                "id": invoice_item.id,
                "filename": invoice_item.filename,
                "sheet_name": invoice_item.sheet_name,
                "item": invoice_item.item,
                "description": invoice_item.description,
                "qty": invoice_item.qty,
                "cost": invoice_item.cost,
                "amount": invoice_item.amount,
                "date": invoice_item.date,
                "ref_no": invoice_item.ref_no,
                "po_number": invoice_item.po_number,
                "customer_job": invoice_item.customer_job,
                "bill": invoice_item.bill,
                "vendor": invoice_item.vendor,
                "class_": invoice_item.class_,  # 'class' is a reserved word in Python, so appending an underscore
                "memo": invoice_item.memo,
                "buyer": invoice_item.buyer,
                "invoice_id": invoice_item.invoice_id
            }
            invoices_items.append(item)

        return invoices_items
