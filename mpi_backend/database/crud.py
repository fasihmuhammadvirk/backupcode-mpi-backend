from datetime import datetime
from sqlalchemy import Date
from sqlalchemy.orm import Session
from contextlib import contextmanager

from mpi_backend.database import get_db
from mpi_backend.database.models import Invoice
from mpi_backend.database.models import InvoiceItem

db_context = contextmanager(get_db)


def insert_invoice(date, filename,supplier,status,storage_path):
    with db_context() as db:
        date = datetime.strptime(date, '%m/%d/%Y')
        new_invoice = Invoice(date=date, filename=filename, supplier=supplier, status=status, storage_path=storage_path)
        db.add(new_invoice)
        db.commit()
        db.refresh(new_invoice)  # to get the newly generated UUID

    return new_invoice


def insert_invoice_items(row, filename, invoice_id):
    new_item = InvoiceItem(
        filename=filename,
        sheet_name = row['Sheet Name'],
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
        bill = row['Bill'],
        vendor=row['Vendor'],
        class_=row['Class'],
        memo=row['Memo'],
        buyer=row['Buyer'])

    with db_context() as db:
        db.add(new_item)
        db.commit()
