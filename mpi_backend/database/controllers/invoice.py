from datetime import datetime
from typing import List, Optional
from datetime import date
from mpi_backend.database.models import Invoice
from mpi_backend.database.schemas import Invoice as InvoiceResponse


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

    def get_invoices(
            self, db,
            supplier_name: str = None,
            from_date: date = None,
            to_date: date = None,
            status: str = 'all',
            page: int = 1,
            page_size: int = 10,
    ):
        query = db.query(Invoice)

        if supplier_name is not None:  # only apply supplier filter if it's provided.
            query = query.filter(Invoice.supplier == supplier_name)

        query = query.filter(Invoice.date >= from_date)

        query = query.filter(Invoice.date <= to_date)

        if status == 'processed':
            query = query.filter(Invoice.status == 'PROCESSED')
        elif status == 'unprocessed':
            # TODO:Add implementation for 'PROCESSING'
            query = query.filter(Invoice.status == 'FAILED')

        invoices = query.all()

        invoices_list = []
        for invoice in invoices:
            invoice_item = InvoiceResponse(
                date=invoice.date,
                filename=invoice.filename,
                supplier=invoice.supplier,
                status=invoice.status
            )
            invoices_list.append(invoice_item)

        return invoices_list
