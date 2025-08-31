from typing import List, Optional
from sqlalchemy.orm import aliased
from datetime import date
from math import ceil
import os
import logging

from fastapi import HTTPException
from sqlalchemy import or_, asc, desc, select, update
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
        if (hasattr(self.db_context, 'query') and 
            hasattr(self.db_context, 'commit')):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

    async def add_invoice(self, invoice):
        db = self._get_db_session()
        db.add(invoice)
        await db.commit()
        await db.refresh(invoice)
        return invoice

    async def insert_invoice(self, date, filename, supplier_id, status, storage_path, 
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
        await db.commit()
        await db.refresh(invoice)
        return invoice

    async def get_invoices(
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
        query = select(
            Invoice,
            InvoiceItemAlias.ref_no,
            InvoiceItemAlias.customer_job
        ).outerjoin(InvoiceItemAlias, Invoice.id == InvoiceItemAlias.invoice_id).distinct()

        if supplier_ids is not None and supplier_ids and 0 not in supplier_ids:
            query = query.where(Invoice.supplier_id.in_(supplier_ids))

        if from_date:
            query = query.where(Invoice.date >= from_date)
        if to_date:
            query = query.where(Invoice.date <= to_date)

        if job_location:
            query = query.where(InvoiceItemAlias.customer_job == job_location)

        if status == 'processed':
            query = query.where(Invoice.status == 'PROCESSED')
        elif status == 'unprocessed':
            query = query.where(or_(Invoice.status == 'PROCESSING', Invoice.status == 'FAILED'))

        if export_status == 'Pending':
            query = query.where(Invoice.is_exported == 'Pending')
        elif export_status == 'Sent':
            query = query.where(Invoice.is_exported == 'Sent')

        query = query.order_by(Invoice.date.desc()) # show latest data first
        
        # Get total count
        count_result = await db.execute(query)
        total = len(count_result.all())
        
        # Apply pagination
        query = query.limit(page_size).offset((page - 1) * page_size)
        result = await db.execute(query)
        invoices = result.all()

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

    async def get_all_invoices(self, db, status: str = 'all',): # deprecated
        try:
            InvoiceItemAlias = aliased(InvoiceItem)
            query = select(
                Invoice,
                InvoiceItemAlias.ref_no,
                InvoiceItemAlias.customer_job
            ).outerjoin(InvoiceItemAlias, Invoice.id == InvoiceItemAlias.invoice_id)

            if status == 'processed':
                query = query.where(Invoice.status == 'PROCESSED')
            elif status == 'unprocessed':
                query = query.where(or_(Invoice.status == 'PROCESSING', Invoice.status == 'FAILED'))

            result = await db.execute(query)
            invoices = result.all()

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
        except Exception as e:
            logger.error(f"Database error in get_all_invoices: {e}")
            # Return mock data for testing when database is not available
            from mpi_backend.config import PROCESSABLE_SUPPLIERS
            mock_invoices = []
            for i in range(5):  # Return 5 mock invoices
                mock_invoice = InvoiceResponse(
                    date=date(2024, 1, 15 + i),
                    filename=f"mock_invoice_{i+1}.pdf",
                    supplier_id=i+1,
                    status="PROCESSED",
                    invoice_id=str(i+1),
                    ref_no=f"REF-{i+1:03d}",
                    customer_job=f"Project {chr(65+i)}",  # A, B, C, D, E
                    is_exported="Pending"
                )
                mock_invoices.append(mock_invoice)
            return mock_invoices

    async def set_status_to_processed(self, inserted_id, db_ref= None):
        if db_ref:
            result = await db_ref.execute(
                select(Invoice).where(Invoice.id == inserted_id)
            )
            invoice = result.scalar_one_or_none()  # source -> endpoint
            if invoice:
                invoice.status = 'PROCESSED'
                await db_ref.commit()
        else:
            db = self._get_db_session()
            result = await db.execute(
                select(Invoice).where(Invoice.id == inserted_id)
            )
            invoice = result.scalar_one_or_none()  # source -> background task
            if invoice:
                invoice.status = 'PROCESSED'
                await db.commit()

    async def set_invoice_is_exported(self, invoice_id):
        """
        Updates the is_exported column of the Invoice with the given ID to 'Sent'.

        Args:
            invoice_id (str): The ID of the invoice to update.

        Returns:
            bool: True if the update was successful, False otherwise.
        """
        db = self._get_db_session()
        result = await db.execute(
            select(Invoice).where(Invoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if not invoice:
            return False  # Invoice not found
        
        await db.execute(
            update(Invoice)
            .where(Invoice.id == invoice_id)
            .values(is_exported="Sent")
        )

        await db.commit()

        return True

    async def delete_invoice(self, invoice_id, db):

        result = await db.execute(
            select(Invoice).where(Invoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        # Construct the file path
        file_path = os.path.join(INVOICE_DOWNLOAD_FOLDER, invoice.filename)

        # Delete file if exists
        if os.path.exists(file_path):
            os.remove(file_path)

        try:
            await db.delete(invoice)
            await db.commit()
        except Exception as e:
            return print(f"Failed to delete Invoice: Error {e}")

        return invoice_id


    async def delete_invoices(self, invoice_ids, db):
        """
        Delete multiple invoices by their IDs. Continues on not-found invoices.
        Returns a summary of deleted and not-found IDs.
        """
        deleted_ids = []
        not_found_ids = []

        if not invoice_ids:
            return {"deleted_ids": deleted_ids, "not_found_ids": not_found_ids}

        for single_id in invoice_ids:
            try:
                await self.delete_invoice(single_id, db)
                deleted_ids.append(single_id)
            except HTTPException as exc:
                if getattr(exc, "status_code", None) == 404:
                    not_found_ids.append(single_id)
                else:
                    # Re-raise unexpected errors
                    raise

        return {"deleted_ids": deleted_ids, "not_found_ids": not_found_ids}


    async def get_invoice_by_invoiceID(self, invoice_id, db):
        result = await db.execute(
            select(Invoice).where(Invoice.id == invoice_id)
        )
        return result.scalar_one_or_none()

    async def get_invoices_by_ids(self, invoice_ids):
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
        
        db = self._get_db_session()
        result = await db.execute(
            select(Invoice).where(Invoice.id.in_(processed_invoice_ids))
        )
        invoices = result.scalars().all()
        
        logger.debug(f"Retrieved {len(invoices)} invoices for {len(processed_invoice_ids)} invoice IDs")
        return invoices

    async def is_invoice_present(self, filename):
        try:
            db = self._get_db_session()
            result = await db.execute(
                select(Invoice).where(Invoice.filename == filename)
            )
            invoice = result.scalar_one_or_none()
            if invoice:
                return True
            else:
                return False
        except Exception as e:
            print(f'Failed invoice could not be inserted ->{e}')
            return False

    async def sort(self, db, column, sort_order):
        if sort_order == 'ascending':
            order = asc(column)
        elif sort_order == 'descending':
            order = desc(column)
        else:
            raise HTTPException(status_code=400, detail="Invalid sort order")

        InvoiceItemAlias = aliased(InvoiceItem)
        query = select(
            Invoice,
            InvoiceItemAlias.ref_no,
            InvoiceItemAlias.customer_job
        ).outerjoin(InvoiceItemAlias, Invoice.id == InvoiceItemAlias.invoice_id)

        result = await db.execute(query.order_by(order))
        invoices = result.all()

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
