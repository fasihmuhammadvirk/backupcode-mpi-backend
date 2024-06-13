from datetime import datetime
from sqlalchemy import asc, desc
from fastapi import HTTPException
from mpi_backend.database.models import InvoiceItem
from mpi_backend.database.schemas import InvoiceItems as InvoiceItemsResponse


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
        query = query.order_by(InvoiceItem.id.desc())
        items = query.all()

        invoices_items = [InvoiceItemsResponse(**item.__dict__) for item in items]

        return invoices_items

    def get_invoice_items_by_filters(self, supplier=None, from_date=None, to_date=None):
        query = self.db_context.query(InvoiceItem)

        if supplier is not None:  # only apply supplier filter if it's provided.
            query = query.filter(InvoiceItem.vendor == supplier)

        query = query.filter(InvoiceItem.date >= from_date)
        query = query.filter(InvoiceItem.date <= to_date)
        query = query.order_by(InvoiceItem.id.desc())
        items = query.all()

        invoices_items = [InvoiceItemsResponse(**item.__dict__) for item in items]
        return invoices_items

    def delete_invoice_items(self, invoice_id,db):
        items = db.query(InvoiceItem).filter_by(invoice_id=invoice_id).all()
        for item in items:
            db.delete(item)
        db.commit()

    def update_invoice_items(self, items: list):
        updated_items = set()  # Track updated items to avoid overwriting
        update_request_data = set()
        ref_no_set = set(item.get('ref_no') for item in items)

        if None in ref_no_set:
            raise HTTPException(status_code=400, detail="ref_no is required for each item.")

        for ref_no in ref_no_set:
            matched_items = self.db_context.query(InvoiceItem).filter_by(ref_no=ref_no).all()

            if not matched_items:
                raise HTTPException(status_code=404, detail=f"Invoice items with ref_no {ref_no} not found.")

            for matched_item in matched_items:
                if matched_item.id in updated_items:
                    continue  # Skip if already updated

                for index,item_data in enumerate(items):
                    if item_data['ref_no'] == ref_no and not (index in update_request_data):
                        for key, value in item_data.items():
                            if key != 'ref_no' and hasattr(matched_item, key):
                                setattr(matched_item, key, value)
                        update_request_data.add(index)

                updated_items.add(matched_item.id)  # Mark as updated
        self.db_context.commit()

    def sort(self, db, column, sort_order):
        if sort_order == 'ascending':
            order = asc(column)
        elif sort_order == 'descending':
            order = desc(column)
        else:
            raise HTTPException(status_code=400, detail="Invalid sort order")

        invoice_items = self.db_context.query(InvoiceItem).order_by(order).all()
        invoices_items = [InvoiceItemsResponse(**item.__dict__) for item in invoice_items]
        return invoices_items

