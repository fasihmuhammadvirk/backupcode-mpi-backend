from datetime import datetime
from sqlalchemy import asc, desc, distinct, case, cast, Float, func
from fastapi import HTTPException, BackgroundTasks
from typing import List, Dict
from datetime import date,datetime, timedelta
from math import ceil
from mpi_backend.database.models import InvoiceItem
from mpi_backend.database.controllers.ItemsMappingController import ItemsMappingController
from mpi_backend.database.controllers.CustomerJobMappingContorller import CustomerJobMappingController
from mpi_backend.database.schemas import InvoiceItems as InvoiceItemsResponse
from mpi_backend.database.schemas import PriceHistoryResponse
from mpi_backend.utils.export_utils import extract_supplier_id


class InvoiceItemController:
    def __init__(self, db):
        self.db_context = db

    def insert_invoice_items(self, row, filename, invoice_id):
        new_item = InvoiceItem(
            filename=filename,
            sheet_name=row['Sheet Name'],
            invoice_id=invoice_id,
            mpi_item=row['MpiItem'],
            mpi_description=row['MpiDescription'],
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
            buyer=row['Buyer'],
            date_added= row['email_date'],
            export_status="Pending"
        )
        with self.db_context() as db:
            db.add(new_item)
            db.commit()

    def invoice_exists(self, reference_no, vendor):
        with self.db_context() as db:
            matched_invoice = db.query(InvoiceItem).filter_by(ref_no=reference_no, vendor= vendor).first()
            return matched_invoice is not None

    def get_invoice_items(self, invoice_id= None):
        query = self.db_context.query(InvoiceItem)
        if invoice_id:
            query = query.filter(InvoiceItem.invoice_id == invoice_id)
        query = query.order_by(InvoiceItem.id.desc())
        items = query.all()

        invoices_items = [InvoiceItemsResponse(**item.__dict__) for item in items]

        return invoices_items

    def get_invoice_items_by_filters(self, supplier=None, from_date=None, to_date=None, job_location=None, export_status=None,
                                     page: int = 1,page_size: int = 10):
        query = self.db_context.query(InvoiceItem)

        if supplier is not None and 'All' not in supplier:  # only apply supplier filter if it's provided.
            query = query.filter(InvoiceItem.vendor.in_(supplier))

        if job_location:
            query = query.filter(InvoiceItem.customer_job == job_location)

        if export_status:
            query = query.filter(InvoiceItem.export_status == export_status)

        query = query.filter(InvoiceItem.date >= from_date)
        query = query.filter(InvoiceItem.date <= to_date)
        query = query.order_by(InvoiceItem.id.desc())
        total = query.count()
        if page_size == 0:
            items = query.all()
            page_size = 1
            total = len(items)
        else:
            query = query.limit(page_size).offset((page - 1) * page_size)
            items = query.all()

        invoices_items = [InvoiceItemsResponse(**item.__dict__) for item in items]

        return {
            "items": invoices_items,
            "total": total,
            "page": page,
            "size": page_size,
            "pages": ceil(total / page_size)
        }

    def count_line_items(self):
        query = self.db_context.query(InvoiceItem)
        total = query.count()
        return total


    def get_invoice_items_by_ids(self, ids):
        query = self.db_context.query(InvoiceItem)

        # if ids:
        #     case_statement = case({id_: idx for idx, id_ in enumerate(ids)}, value=InvoiceItem.id) #order the results based on the order of the IDs
        #     query = query.filter(InvoiceItem.id.in_(ids)).order_by(case_statement) # commenting out because of slow performance

        if ids:
            query = query.filter(InvoiceItem.id.in_(ids))

        items = query.all()

        invoices_items = [InvoiceItemsResponse(**item.__dict__) for item in items]
        return invoices_items

    def set_export_status_to_sent(self, ids):
        """
        Updates the export_status of the InvoiceItems with the given IDs to 'Sent'.
        Args:
            ids (list): A list of InvoiceItem IDs to update.
        Returns:
            int: The number of records updated.
        """
        query = self.db_context.query(InvoiceItem)

        if ids:
            query = query.filter(InvoiceItem.id.in_(ids))
        else:
            print('Invoice Item Row Ids not provided')
            return 0

        updated_count = query.update({"export_status": "Sent"}, synchronize_session='fetch')
        self.db_context.commit()
        return updated_count

    def is_exported(self, invoice_id):
        """
        Checks if all invoice items for the given invoice_id have export_status as 'Sent'.

        Args:
            invoice_id (str): The ID of the invoice to check.

        Returns:
            bool: True if all items are 'Sent', False if any item is 'Pending'.
        """
        query = self.db_context.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id)
        items = query.all()

        for item in items:
            if item.export_status != "Sent":
                return False
        return True

    def delete_invoice_items(self, invoice_id,db):
        items = db.query(InvoiceItem).filter_by(invoice_id=invoice_id).all()
        for item in items:
            db.delete(item)
        db.commit()

    def update_invoice_items(self, items: List[Dict], background_tasks: BackgroundTasks):
        for item_data in items:
            item_id = item_data.get('id')
            if not item_id:
                raise HTTPException(status_code=400, detail="ID is required for updating invoice item")

            item = self.db_context.query(InvoiceItem).filter(InvoiceItem.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail=f"Invoice item with ID {item_id} not found")

            # Check for updates in mpi_item and mpi_description and customer_job and make updates on whole table
            # item_data -- > coming from request
            # item -- > its associated record in database
            if item_data['mpi_item'] != item.mpi_item:  # mpi_item code is changed
                background_tasks.add_task(self.update_mpi_field, item_data['item'], 'mpi_item',
                                          item_data['mpi_item'])
                background_tasks.add_task(self.update_mappings_table, item_data)

            if item_data['mpi_description'] != item.mpi_description:  # mpi_item description is changed
                background_tasks.add_task(self.update_mpi_field, item_data['item'], 'mpi_description',
                                          item_data['mpi_description'])

            if item_data['customer_job'] != item.customer_job: # customer job was updated
                background_tasks.add_task(self.update_customer_job, item.customer_job, 'customer_job',
                                          item_data['customer_job'])
                CustomerJobMappingController(self.db_context).update_mappings_table(old_customer_job=item.customer_job,new_customer_job=item_data['customer_job'])

            for key, value in item_data.items():  # update items
                setattr(item, key, value)

            self.db_context.add(item)
        self.db_context.commit()

    def update_mpi_field(self, item_value: str, field_name: str, new_value: str):
        self.db_context.query(InvoiceItem).filter(InvoiceItem.item == item_value).update({field_name: new_value})
        self.db_context.commit()

    def update_customer_job(self, item_value: str, field_name: str, new_value: str):
        self.db_context.query(InvoiceItem).filter(InvoiceItem.customer_job == item_value).update({field_name: new_value})
        self.db_context.commit()

    def update_mappings_table(self, updated_values: dict):
        supplier_id, _ = extract_supplier_id(updated_values['vendor'])
        mapping_data = {
            "supplier_item_ids": updated_values['item'],
            "description": updated_values['mpi_description'],
            "mpi_code": updated_values['mpi_item'],
            "google_sheet_name": updated_values['sheet_name']
        }
        ItemsMappingController(self.db_context).update_mapping(supplier_id, mapping_data)

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

    def get_customer_jobs(self, db):
        customer_jobs = db.query(InvoiceItem.customer_job).distinct().all()
        return customer_jobs

    def get_data_by_column_name(self, column_name, filter_context):
        """
        Used to generates drop down filters for data-review table header.
        Args:
        column_name: the column we want the values for.
        filter_context: the previous selected columns / previous applied filters
        """
        column_name = getattr(InvoiceItem, column_name)
        query = self.db_context.query(distinct(column_name))

        if filter_context:  # if there are previous filter selections -> add them in query
            for column in filter_context.keys():
                filter_column = getattr(InvoiceItem, column)
                query = query.filter(filter_column.in_(filter_context[column]))

        distinct_values = query.order_by(column_name.asc()).all()
        return [value[0] for value in distinct_values if value[0] is not None]

    def apply_filters(self, request,page, size, col_param=None):
        query = self.db_context.query(InvoiceItem)

        # applying 'IN' filters dynamically
        for column_name, values in request.filters.items():
            if not hasattr(InvoiceItem, column_name):
                raise HTTPException(status_code=400, detail=f"Invalid column name: {column_name}")

            column = getattr(InvoiceItem, column_name)
            query = query.filter(column.in_(values))

        # applying comparison (>,<= etc) filters
        for comp_filter in request.comparison_filters:
            if not hasattr(InvoiceItem, comp_filter.column):
                raise HTTPException(status_code=400, detail=f"Invalid column name: {comp_filter.column}")

            column = getattr(InvoiceItem, comp_filter.column)

            # Special handling for 'amount' column (string to float conversion)
            if comp_filter.column == "amount":
                column = cast(column, Float)

            # Handle type casting for comparison filters
            try:
                if comp_filter.column == "amount":
                    try:
                        value = float(comp_filter.value)
                    except ValueError:
                        continue # Skip invalid float conversion
                elif column.type.python_type == int:
                    value = int(comp_filter.value)
                elif column.type.python_type == float:
                    value = float(comp_filter.value)
                elif column.type.python_type == date:
                    value = date.fromisoformat(comp_filter.value)
                else:
                    value = comp_filter.value
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail=f"Invalid value type for column: {comp_filter.column}")

            if comp_filter.operator == "gt":
                query = query.filter(column > value)
            elif comp_filter.operator == "lt":
                query = query.filter(column < value)
            elif comp_filter.operator == "gte":
                query = query.filter(column >= value)
            elif comp_filter.operator == "lte":
                query = query.filter(column <= value)
            elif comp_filter.operator == "eq":
                query = query.filter(column == value)
            else:
                raise HTTPException(status_code=400, detail=f"Invalid operator: {comp_filter.operator}")

        if request.order_by: # applying sorting
            for order_filter in request.order_by:
                if not hasattr(InvoiceItem, order_filter.column):
                    raise HTTPException(status_code=400,
                                        detail=f"Invalid column name for ordering: {order_filter.column}")

                column = getattr(InvoiceItem, order_filter.column)

                if order_filter.order == "asc":
                    query = query.order_by(column.asc())
                elif order_filter.order == "desc":
                    query = query.order_by(column.desc())
                else:
                    raise HTTPException(status_code=400, detail=f"Invalid order direction: {order_filter.order}")
        if size == 0:
            if col_param: # select distinct values of certain column
                column = getattr(InvoiceItem, col_param, None)
                return list(set(row[0] for row in query.with_entities(column).distinct()))

            results = query.all()
            size=1
            total = len(results)
        else:
            total = query.count()
            query = query.limit(size).offset((page - 1) * size)
            results = query.all()

        invoices_items = [InvoiceItemsResponse(**item.__dict__) for item in results]

        return {
            "items": invoices_items,
            "total": total,
            "page": page,
            "size": size,
            "pages": ceil(total / size)
        }

    def get_price_history(self, request):
        query = self.db_context.query(InvoiceItem)
        query = query.filter(InvoiceItem.item == request.item_number)
        query = query.filter(InvoiceItem.vendor == request.vendor)

        matched_items = query.all()

        response = [
            PriceHistoryResponse(
                ref_no=item.ref_no, date=item.date.strftime("%m-%d-%Y"),
                cost=item.cost, qty=item.qty, invoice_id= str(item.invoice_id))
            for item in matched_items]
        return response


    def get_aggregates(self, request):
        query = self.db_context.query(InvoiceItem)

        # applying 'IN' filters dynamically
        for column_name, values in request.filters.items():
            if not hasattr(InvoiceItem, column_name):
                raise HTTPException(status_code=400, detail=f"Invalid column name: {column_name}")

            column = getattr(InvoiceItem, column_name)
            query = query.filter(column.in_(values))

        # applying comparison (>,<= etc) filters
        for comp_filter in request.comparison_filters:
            if not hasattr(InvoiceItem, comp_filter.column):
                raise HTTPException(status_code=400, detail=f"Invalid column name: {comp_filter.column}")

            column = getattr(InvoiceItem, comp_filter.column)

            # Special handling for 'amount' column (string to float conversion)
            if comp_filter.column == "amount":
                column = cast(column, Float)

            # Handle type casting for comparison filters
            try:
                if comp_filter.column == "amount":
                    try:
                        value = float(comp_filter.value)
                    except ValueError:
                        continue  # Skip invalid float conversion
                elif column.type.python_type == int:
                    value = int(comp_filter.value)
                elif column.type.python_type == float:
                    value = float(comp_filter.value)
                elif column.type.python_type == date:
                    value = date.fromisoformat(comp_filter.value)
                else:
                    value = comp_filter.value
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail=f"Invalid value type for column: {comp_filter.column}")

            if comp_filter.operator == "gt":
                query = query.filter(column > value)
            elif comp_filter.operator == "lt":
                query = query.filter(column < value)
            elif comp_filter.operator == "gte":
                query = query.filter(column >= value)
            elif comp_filter.operator == "lte":
                query = query.filter(column <= value)
            elif comp_filter.operator == "eq":
                query = query.filter(column == value)
            else:
                raise HTTPException(status_code=400, detail=f"Invalid operator: {comp_filter.operator}")

        # Cast amount to float for calculations
        amount_column = cast(InvoiceItem.amount, Float)

        aggregates = query.with_entities(
            func.sum(InvoiceItem.qty).label('total_qty'),
            func.sum(amount_column).label('total_amount'),
            func.avg(InvoiceItem.cost).label('average_cost')
        ).first()

        total_qty = aggregates.total_qty or 0
        total_amount = float(aggregates.total_amount or 0)
        average_cost = float(aggregates.average_cost or 0)

        return {
            "total_qty": total_qty,
            "total_amount": round(total_amount, 2),
            "average_cost": round(average_cost, 2)
        }

    def calculate_price_increase(self, item_numbers):
        """
        Calculate percentage price increase by comparing current price with price from ~1 year ago.
        Optimized for minimal latency.
        Preserves duplicates and maintains original order of item numbers.

        Args:
            item_numbers: List containing item_numbers

        Returns:
            List of tuples with item numbers and their percentage increases, preserving original order
        """
        current_date = datetime.now()
        target_date = current_date - timedelta(days=365)  # Date 1 year ago
        result = []

        if not item_numbers: # No items to process
            return result

        base_query = self.db_context.query(InvoiceItem)
        items_filter = InvoiceItem.item.in_(set(item_numbers))  # using set to avoid duplicate queries
        all_items = base_query.filter(items_filter).all()

        # Group same item numbers together
        grouped_items = {}
        for item in all_items:
            if item.item not in grouped_items:
                grouped_items[item.item] = []
            grouped_items[item.item].append(item)

        # Process each item number in the original order- to preserve duplicates
        for item_number in item_numbers:
            percentage_increase = "∞%"  # Default value

            if item_number in grouped_items:
                items = grouped_items[item_number]
                if items:
                    # Sort by date descending (most recent first)
                    items.sort(key=lambda x: x.date, reverse=True)

                    # Get most recent price
                    current_item = items[0]
                    current_price = current_item.cost

                    # Find items purchased before target date (1 year ago)
                    past_items = []
                    for item in items:
                        # Safely compare dates by ensuring both are datetime objects
                        item_date = item.date
                        compare_date = target_date

                        # Convert date to datetime if needed
                        if isinstance(item_date, date) and not isinstance(item_date, datetime):
                            item_date = datetime.combine(item_date, datetime.min.time())

                        if isinstance(compare_date, date) and not isinstance(compare_date, datetime):
                            compare_date = datetime.combine(compare_date, datetime.min.time())

                        if item_date < compare_date:
                            past_items.append(item)

                    if past_items:
                        # Find the item with date closest to target date
                        def date_difference(item):
                            item_date = item.date
                            compare_date = target_date

                            # Convert date to datetime if needed
                            if isinstance(item_date, date) and not isinstance(item_date, datetime):
                                item_date = datetime.combine(item_date, datetime.min.time())

                            if isinstance(compare_date, date) and not isinstance(compare_date, datetime):
                                compare_date = datetime.combine(compare_date, datetime.min.time())

                            # Return absolute difference in seconds
                            return abs((item_date - compare_date).total_seconds())

                        past_item = min(past_items, key=date_difference)
                        previous_price = past_item.cost

                        # Calculate percentage increase
                        if previous_price == 0:
                            percentage_increase = "∞%"
                        else:
                            percentage_value = ((current_price - previous_price) / previous_price) * 100
                            percentage_increase = f"{round(percentage_value, 1)}%"

            result.append((item_number, percentage_increase))

        return result