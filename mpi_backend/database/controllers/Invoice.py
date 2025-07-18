from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import joinedload, aliased
from datetime import date
from math import ceil
import os
import logging

from fastapi import HTTPException
from sqlalchemy import or_, asc, desc
from mpi_backend.database.models import Invoice, InvoiceItem
from mpi_backend.database.schemas import Invoice as InvoiceResponse
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER

logger = logging.getLogger(__name__)

class InvoiceController:
    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self):
        """Get a database session object, whether db_context is a factory or session."""
        # Check if it's already a session instance (has query, add, commit methods)
        if hasattr(self.db_context, 'query') and hasattr(self.db_context, 'commit'):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

    def add_invoice(self, invoice):
        db = self._get_db_session()
        db.add(invoice)
        db.commit()
        db.refresh(invoice)
        return invoice

    def insert_invoice(self, date, filename, supplier_id, status, storage_path, 
                       existing_invoice_id=None):
        """
        Insert a new invoice record (maintains compatibility with old code).
        
        Args:
            date: Invoice date
            filename: Invoice filename
            supplier_id: Supplier ID
            status: Invoice status
            storage_path: File storage path
            existing_invoice_id: Optional existing invoice ID for reprocessing
            
        Returns:
            Invoice object
        """
        db = self._get_db_session()
        
        if existing_invoice_id:
            # For reprocessing, use the existing invoice ID
            invoice = Invoice(
                id=existing_invoice_id,
                date=date,
                filename=filename,
                supplier_id=supplier_id,
                status=status,
                storage_path=storage_path,
                is_exported='Pending'
            )
        else:
            # For new uploads, let the database generate a new ID
            invoice = Invoice(
                date=date,
                filename=filename,
                supplier_id=supplier_id,
                status=status,
                storage_path=storage_path,
                is_exported='Pending'
            )
        
        db.add(invoice)
        db.commit()
        db.refresh(invoice)
        return invoice

    def get_invoices(
            self, db,
            supplier_ids: Optional[List[int]] = None,
            from_date: date = None,
            to_date: date = None,
            status: str = 'all',
            job_location:str = None,
            export_status:str = None,
            page: int = 1,
            page_size: int = 10,
    ):
        InvoiceItemAlias = aliased(InvoiceItem)
        query = db.query(
            Invoice,
            InvoiceItemAlias.ref_no,
            InvoiceItemAlias.customer_job
        ).outerjoin(InvoiceItemAlias, Invoice.id == InvoiceItemAlias.invoice_id).distinct()

        if supplier_ids is not None and supplier_ids and 0 not in supplier_ids:
            query = query.filter(Invoice.supplier_id.in_(supplier_ids))

        if from_date:
            query = query.filter(Invoice.date >= from_date)
        if to_date:
            query = query.filter(Invoice.date <= to_date)

        if job_location:
            query = query.filter(InvoiceItemAlias.customer_job == job_location)

        if status == 'processed':
            query = query.filter(Invoice.status == 'PROCESSED')
        elif status == 'unprocessed':
            query = query.filter(or_(Invoice.status == 'PROCESSING', Invoice.status == 'FAILED'))

        if export_status == 'Pending':
            query = query.filter(Invoice.is_exported == 'Pending')
        elif export_status == 'Sent':
            query =  query.filter(Invoice.is_exported == 'Sent')

        query = query.order_by(Invoice.date.desc()) # show latest data first
        total = query.count()
        query = query.limit(page_size).offset((page - 1) * page_size) # database level pagination
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
                customer_job=customer_job if customer_job is not None else '',
                is_exported=invoice.is_exported
            )
            invoices_list.append(invoice_item)
        return {
            "items": invoices_list,
            "total": total,
            "page": page,
            "size": page_size,
            "pages": ceil(total / page_size)
        }

    def get_all_invoices(self, db, status: str = 'all',): # deprecated

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
                customer_job=customer_job if customer_job is not None else '',
                is_exported=invoice.is_exported
            )
            invoices_list.append(invoice_item)

        return invoices_list

    def set_status_to_processed(self, inserted_id, db_ref= None):
        if db_ref:
            invoice = db_ref.query(Invoice).filter(Invoice.id == inserted_id).first() # source -> endpoint
            if invoice:
                invoice.status = 'PROCESSED'
                db_ref.commit()
        else:
            db = self._get_db_session()
            invoice = db.query(Invoice).filter(Invoice.id == inserted_id).first() # source -> background task
            if invoice:
                invoice.status = 'PROCESSED'
                db.commit()

    def set_invoice_is_exported(self, invoice_id):
        """
        Updates the is_exported column of the Invoice with the given ID to 'Sent'.

        Args:
            invoice_id (str): The ID of the invoice to update.

        Returns:
            bool: True if the update was successful, False otherwise.
        """
        db = self._get_db_session()
        query = db.query(Invoice).filter(Invoice.id == invoice_id)

        invoice = query.first()
        if not invoice:
            return False  # Invoice not found
        query.update({"is_exported": "Sent"}, synchronize_session='fetch')

        db.commit()

        return True

    def delete_invoice(self, invoice_id,db):

        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        # Construct the file path
        file_path = os.path.join(INVOICE_DOWNLOAD_FOLDER, invoice.filename)

        # Delete file if exists
        if os.path.exists(file_path):
            os.remove(file_path)

        try:
            db.delete(invoice)
            db.commit()
        except Exception as e:
            return print(f"Failed to delete Invoice: Error {e}")

        return invoice_id


    def get_invoice_by_invoiceID(self, invoice_id,db):
        return db.query(Invoice).filter(Invoice.id == invoice_id).first()

    def get_invoices_by_ids(self, invoice_ids):
        """
        Get invoices by a list of invoice IDs for QuickBooks export.
        
        Args:
            invoice_ids: List of invoice IDs (can be UUID objects or strings)
            
        Returns:
            List of Invoice objects
        """
        if not invoice_ids:
            return []
        
        # Convert UUID objects to strings if needed for database query
        processed_invoice_ids = []
        for invoice_id in invoice_ids:
            if hasattr(invoice_id, '__str__'):
                processed_invoice_ids.append(str(invoice_id))
            else:
                processed_invoice_ids.append(invoice_id)
        
        invoices = self._get_db_session().query(Invoice).filter(
            Invoice.id.in_(processed_invoice_ids)
        ).all()
        
        logger.debug(f"Retrieved {len(invoices)} invoices for {len(processed_invoice_ids)} invoice IDs")
        return invoices

    def is_invoice_present(self,filename):
        try:
            with self._get_db_session() as db:
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

        InvoiceItemAlias = aliased(InvoiceItem)
        query = db.query(
            Invoice,
            InvoiceItemAlias.ref_no,
            InvoiceItemAlias.customer_job
        ).outerjoin(InvoiceItemAlias, Invoice.id == InvoiceItemAlias.invoice_id)

        invoices = query.order_by(order).all()

        invoices_list = []
        for invoice, ref_no, customer_job in invoices:
            invoice_item = InvoiceResponse(
                date=invoice.date,
                filename=invoice.filename,
                supplier_id=invoice.supplier_id,
                status=invoice.status,
                invoice_id=str(invoice.id),
                ref_no=ref_no if ref_no is not None else '',
                customer_job=customer_job if customer_job is not None else '',
                is_exported=invoice.is_exported
            )
            invoices_list.append(invoice_item)
        return invoices_list
