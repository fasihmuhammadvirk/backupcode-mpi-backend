from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import joinedload, aliased
from datetime import date

from fastapi import HTTPException
from sqlalchemy import or_, asc, desc
from mpi_backend.database.models import Invoice, InvoiceItem
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
            supplier_ids: Optional[List[int]] = None,
            from_date: date = None,
            to_date: date = None,
            status: str = 'all',
            page: int = 1,
            page_size: int = 10,
    ):
        InvoiceItemAlias = aliased(InvoiceItem)
        query = db.query(
            Invoice,
            InvoiceItemAlias.ref_no,
            InvoiceItemAlias.customer_job
        ).outerjoin(InvoiceItemAlias, Invoice.id == InvoiceItemAlias.invoice_id)

        if supplier_ids is not None and supplier_ids:
            query = query.filter(Invoice.supplier_id.in_(supplier_ids))

        if from_date:
            query = query.filter(Invoice.date >= from_date)
        if to_date:
            query = query.filter(Invoice.date <= to_date)

        if status == 'processed':
            query = query.filter(Invoice.status == 'PROCESSED')
        elif status == 'unprocessed':
            query = query.filter(or_(Invoice.status == 'PROCESSING', Invoice.status == 'FAILED'))

        invoices = query.all()

        invoices_list = []
        for invoice, ref_no, customer_job in invoices:
            invoice_item = InvoiceResponse(
                date=invoice.date,
                filename=invoice.filename,
                supplier_id=invoice.supplier_id,
                status=invoice.status,
                invoice_id=str(invoice.id),
                ref_no=ref_no if ref_no is not None else '',
                customer_job=customer_job if customer_job is not None else ''
            )
            invoices_list.append(invoice_item)
        return invoices_list

    def get_all_invoices(self, db, status: str = 'all',):

        InvoiceItemAlias = aliased(InvoiceItem)
        query = db.query(
            Invoice,
            InvoiceItemAlias.ref_no,
            InvoiceItemAlias.customer_job
        ).outerjoin(InvoiceItemAlias, Invoice.id == InvoiceItemAlias.invoice_id)

        if status == 'processed':
            query = query.filter(Invoice.status == 'PROCESSED')
        elif status == 'unprocessed':
            query = query.filter(or_(Invoice.status == 'PROCESSING', Invoice.status == 'FAILED'))

        invoices = query.all()

        invoices_list = []
        for invoice, ref_no, customer_job in invoices:
            invoice_item = InvoiceResponse(
                date=invoice.date,
                filename=invoice.filename,
                supplier_id=invoice.supplier_id,
                status=invoice.status,
                invoice_id=str(invoice.id),
                ref_no=ref_no if ref_no is not None else '',
                customer_job=customer_job if customer_job is not None else ''
            )
            invoices_list.append(invoice_item)

        return invoices_list

    def set_status_to_processed(self, inserted_id, db_ref= None):
        if db_ref:
            invoice = db_ref.query(Invoice).filter(Invoice.id == inserted_id).first() # source -> endpoint
            invoice.status = 'PROCESSED'
            db_ref.commit()
        else:
            with self.db_context() as db:
                invoice = db.query(Invoice).filter(Invoice.id == inserted_id).first() # source -> background task
                invoice.status = 'PROCESSED'
                db.commit()

    def delete_invoice(self,invoice_id,db):
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).all()
        for record in invoice:
            db.delete(record)
        db.commit()

    def get_invoice_by_invoiceID(self, invoice_id,db):
        return db.query(Invoice).filter(Invoice.id == invoice_id).first()

    def is_invoice_present(self,filename):
        try:
            with self.db_context() as db:
                invoice = db.query(Invoice).filter_by(filename=filename).first()
            if invoice:
                return True
            else:
                return False
        except Exception as e:
            print(f'Failed invoice could not be inserted ->{e}')
            return False

    def sort(self, db, column, sort_order):
        if sort_order == 'ascending':
            order = asc(column)
        elif sort_order == 'descending':
            order = desc(column)
        else:
            raise HTTPException(status_code=400, detail="Invalid sort order")

        invoices = db.query(Invoice).order_by(order).all()

        invoices_list = []
        for invoice in invoices:
            invoice_item = InvoiceResponse(
                date=invoice.date,
                filename=invoice.filename,
                supplier_id=invoice.supplier_id,
                status=invoice.status,
                invoice_id=str(invoice.id)
            )
            invoices_list.append(invoice_item)

        return invoices_list

