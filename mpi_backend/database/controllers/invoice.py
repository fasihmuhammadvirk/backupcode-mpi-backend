from datetime import datetime
from typing import List, Optional
from datetime import date
from sqlalchemy import or_
from mpi_backend.database.models import Invoice
from mpi_backend.database.schemas import Invoice as InvoiceResponse


class InvoiceController:
    def __init__(self, db):
        self.db_context = db

    def insert_invoice(self, date, filename, supplier_id, status, storage_path):
        date = datetime.strptime(date, '%m/%d/%Y')
        new_invoice = Invoice(date=date, filename=filename, supplier_id=supplier_id, status=status, storage_path=storage_path)
        with self.db_context() as db:
            db.add(new_invoice)
            db.commit()
            db.refresh(new_invoice)  # to get the newly generated UUID
        return new_invoice

    def get_invoices(
            self, db,
            supplier_id: int = None,
            from_date: date = None,
            to_date: date = None,
            status: str = 'all',
            page: int = 1,
            page_size: int = 10,
    ):
        query = db.query(Invoice)

        if supplier_id is not None:  # only apply supplier filter if it's provided.
            query = query.filter(Invoice.supplier_id == supplier_id)

        query = query.filter(Invoice.date >= from_date)

        query = query.filter(Invoice.date <= to_date)

        if status == 'processed':
            query = query.filter(Invoice.status == 'PROCESSED')
        elif status == 'unprocessed':
            query = query.filter(or_(Invoice.status == 'PROCESSING', Invoice.status == 'FAILED'))

        invoices = query.all()

        invoices_list = []
        for invoice in invoices:
            invoice_item = InvoiceResponse(
                date=invoice.date,
                filename=invoice.filename,
                supplier_id=invoice.supplier_id,
                status=invoice.status,
                invoice_id= str(invoice.id)
            )
            invoices_list.append(invoice_item)

        return invoices_list

    def set_status_to_processed(self, inserted_id, db_ref= None):
        if db_ref:
            db_ref.query(Invoice).filter(Invoice.id == inserted_id).update({"status": "PROCESSED"}) # source -> endpoint
        else:
            with self.db_context() as db:
                db.query(Invoice).filter(Invoice.id == inserted_id).update({"status": "PROCESSED"}) # source -> background task

    def delete_invoice(self,invoice_id,db):
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).all()
        for record in invoice:
            db.delete(record)
        db.commit()

    def get_invoice_by_invoiceID(self, invoice_id,db):
        return db.query(Invoice).filter(Invoice.id == invoice_id).first()
