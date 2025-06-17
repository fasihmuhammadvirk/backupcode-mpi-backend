from datetime import datetime
from sqlalchemy import asc, desc, distinct, case, cast, Float, func
from fastapi import HTTPException, BackgroundTasks
from typing import List, Dict
from datetime import date, datetime, timedelta
from math import ceil
from mpi_backend.database.models import InvoiceItem
from mpi_backend.database.controllers.ItemsMappingController import ItemsMappingController
from mpi_backend.database.controllers.CustomerJobMappingContorller import CustomerJobMappingController
from mpi_backend.database.schemas import InvoiceItems as InvoiceItemsResponse
from mpi_backend.database.schemas import PriceHistoryResponse
from mpi_backend.utils.export_utils import extract_supplier_id
import math
import logging

logger = logging.getLogger(__name__)

class InvoiceItemController:
    def __init__(self, db):
        self.db_context = db

    def _remove_suffix_from_item_code(self, item_code_with_suffix):
        """
        Remove supplier suffix from item code to get original database value.
        This is used when filtering by suffixed values selected from dropdowns.
        
        Args:
            item_code_with_suffix: Item code that may have a suffix (e.g., "ABC123-B")
            
        Returns:
            str: Original item code without suffix (e.g., "ABC123")
        """
        if not item_code_with_suffix:
            return item_code_with_suffix
        
        # Get all possible suffixes from the model
        from mpi_backend.database.models.InvoiceItems import InvoiceItem
        all_suffixes = set(InvoiceItem.SUPPLIER_SUFFIX_MAP.values())
        all_suffixes.discard("")  # Remove empty suffix
        
        # Check if the item code ends with any known suffix
        for suffix in all_suffixes:
            if item_code_with_suffix.endswith(suffix):
                # Remove the suffix to get original item code
                original_code = item_code_with_suffix[:-len(suffix)]
                return original_code
        
        # If no suffix found, return as-is (might be an item without suffix)
        return item_code_with_suffix

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
            date_added=row['email_date'],
            export_status="Pending"
        )
        with self.db_context() as db:
            db.add(new_item)
            db.commit()

    def invoice_exists(self, reference_no, vendor):
        with self.db_context() as db:
            matched_invoice = db.query(InvoiceItem).filter_by(ref_no=reference_no, vendor=vendor).first()
            return matched_invoice is not None

    def get_invoice_items(self, invoice_id=None):
        query = self.db_context.query(InvoiceItem)
        if invoice_id:
            query = query.filter(InvoiceItem.invoice_id == invoice_id)
        query = query.order_by(InvoiceItem.id.desc())
        items = query.all()

        invoices_items = []
        for item in items:
            item_dict = item.__dict__.copy()
            # Replace the item field with the suffixed version for display
            item_dict['item'] = item.item_code_with_suffix
            invoices_items.append(InvoiceItemsResponse(**item_dict))

        return invoices_items

    def get_invoice_items_by_filters(self, supplier=None, from_date=None, to_date=None, job_location=None,
                                     export_status=None,
                                     page: int = 1, page_size: int = 10):
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

        invoices_items = []
        for item in items:
            item_dict = item.__dict__.copy()
            # Replace the item field with the suffixed version for display
            item_dict['item'] = item.item_code_with_suffix
            invoices_items.append(InvoiceItemsResponse(**item_dict))

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

    def get_invoice_items_by_ids(self, ids, order_by=None):
        query = self.db_context.query(InvoiceItem)

        # if ids:
        #     case_statement = case({id_: idx for idx, id_ in enumerate(ids)}, value=InvoiceItem.id) #order the results based on the order of the IDs
        #     query = query.filter(InvoiceItem.id.in_(ids)).order_by(case_statement) # commenting out because of slow performance

        if ids:
            query = query.filter(InvoiceItem.id.in_(ids))

        # Apply ordering if provided
        if order_by:
            for order_filter in order_by:
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

        items = query.all()

        invoices_items = []
        for item in items:
            item_dict = item.__dict__.copy()
            # Replace the item field with the suffixed version for display
            item_dict['item'] = item.item_code_with_suffix
            invoices_items.append(InvoiceItemsResponse(**item_dict))
        return invoices_items

    def get_invoice_items_for_export_optimized(self, ids, columns=None, order_by=None):
        """
        Optimized method for exporting invoice items with minimal memory overhead.
        Returns raw database tuples instead of full objects for better performance.
        
        Args:
            ids: List of invoice item IDs
            columns: List of column names to include (optional)
            order_by: List of OrderByFilter objects (optional)
            
        Returns:
            List of tuples with selected data
        """
        if not ids:
            return []
        
        # Define columns mapping
        available_columns = {
            'item': InvoiceItem.item,
            'description': InvoiceItem.description,
            'qty': InvoiceItem.qty,
            'cost': InvoiceItem.cost,
            'amount': InvoiceItem.amount,
            'date': InvoiceItem.date,
            'ref_no': InvoiceItem.ref_no,
            'po_number': InvoiceItem.po_number,
            'customer_job': InvoiceItem.customer_job,
            'bill': InvoiceItem.bill,
            'vendor': InvoiceItem.vendor,
            'class_': InvoiceItem.class_,
            'memo': InvoiceItem.memo,
            'buyer': InvoiceItem.buyer,
            'filename': InvoiceItem.filename,
            'sheet_name': InvoiceItem.sheet_name,
            'mpi_item': InvoiceItem.mpi_item,
            'mpi_description': InvoiceItem.mpi_description,
            'date_added': InvoiceItem.date_added
        }
        
        # Determine which columns to select
        if columns:
            # Map display column names back to database columns
            column_mapping = {
                'Item': 'item',
                'Description': 'description',
                'Qty': 'qty',
                'Cost': 'cost',
                'Amount': 'amount',
                'Date': 'date',
                'Ref NO': 'ref_no',
                'PO #': 'po_number',
                'Customer Job': 'customer_job',
                'Bill': 'bill',
                'Vendor': 'vendor',
                'Class': 'class_',
                'Memo': 'memo',
                'Buyer': 'buyer',
                'Filename': 'filename',
                'Sheet Name': 'sheet_name',
                'MPI Item Code': 'mpi_item',
                'MPI Description': 'mpi_description',
                'Date Added': 'date_added'
            }
            
            selected_columns = []
            column_names = []
            for col in columns:
                db_col = column_mapping.get(col, col.lower().replace(' ', '_'))
                if db_col in available_columns:
                    selected_columns.append(available_columns[db_col])
                    column_names.append(db_col)
        else:
            # Default columns for export - match the original convert_items_to_dataframe output
            default_cols = ['item', 'description', 'qty', 'cost', 'amount', 'date', 
                          'ref_no', 'po_number', 'customer_job', 'bill', 'vendor', 'class_', 'memo',
                          'buyer', 'filename', 'sheet_name', 'mpi_item', 'mpi_description', 'date_added']
            selected_columns = [available_columns[col] for col in default_cols]
            column_names = default_cols
        
        # Always include vendor for suffix calculation
        if 'vendor' not in column_names:
            selected_columns.append(InvoiceItem.vendor)
            column_names.append('vendor')
        
        # Build and execute query
        query = self.db_context.query(*selected_columns).filter(InvoiceItem.id.in_(ids))
        
        # Apply ordering if provided
        if order_by:
            for order_filter in order_by:
                if order_filter.column in available_columns:
                    column = available_columns[order_filter.column]
                    if order_filter.order == "asc":
                        query = query.order_by(column.asc())
                    elif order_filter.order == "desc":
                        query = query.order_by(column.desc())
        
        return query.all(), column_names

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

    def delete_invoice_items(self, invoice_id, db):
        items = db.query(InvoiceItem).filter_by(invoice_id=invoice_id).all()
        for item in items:
            db.delete(item)
        db.commit()

    def toggle_visibility(self, ids: List[int], make_visible: bool) -> int:
        """Update visibility for given invoice items."""
        try:
            db = self.db_context
            updated_count = db.query(InvoiceItem).filter(
                InvoiceItem.id.in_(ids)
            ).update({InvoiceItem.is_active: make_visible}, synchronize_session=False)

            db.commit()
            return updated_count
        except Exception as e:
            self.db_context.rollback()
            raise HTTPException(status_code=500, detail=str(e))

    def get_hidden_items(self):
        """Fetch all hidden invoice items."""
        try:
            items = self.db_context.query(InvoiceItem).execution_options(include_all=True) \
                .filter(InvoiceItem.is_active.is_(False)) \
                .all()
            hidden_items = [item for item in items if not item.is_active]
            invoices_items = []
            for item in hidden_items:
                item_dict = item.__dict__.copy()
                # Replace the item field with the suffixed version for display
                item_dict['item'] = item.item_code_with_suffix
                invoices_items.append(InvoiceItemsResponse(**item_dict))
            return invoices_items
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def update_invoice_items(self, items: List[Dict], background_tasks: BackgroundTasks):
        for item_data in items:
            item_id = item_data.get('id')
            if not item_id:
                raise HTTPException(status_code=400, detail="ID is required for updating invoice item")

            item = self.db_context.query(InvoiceItem).filter(InvoiceItem.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail=f"Invoice item with ID {item_id} not found")
            
            # Get the new MPI item value, defaulting to current value if not in request
            new_mpi_item = item_data.get('mpi_item', item.mpi_item)
            
            # Check if it's a valid MPI item (not "No Match" and not starting with "UIDI")
            is_valid_mpi = (new_mpi_item and 
                            new_mpi_item.lower() != "no match" and 
                            not new_mpi_item.startswith("UIDI"))
            
            # Get sheet_name from request, defaulting to current value if not provided
            new_sheet_name = item_data.get('sheet_name', item.sheet_name)
            
            # Only validate sheet_name for valid MPI items
            if is_valid_mpi and not new_sheet_name and new_mpi_item != item.mpi_item:
                # Debug logging to see what's causing the issue
                logger.error(f"Validation failed: mpi_item={new_mpi_item}, sheet_name={new_sheet_name}, data={item_data}")
                raise HTTPException(
                    status_code=400, 
                    detail=f"Sheet name is required when updating to a valid MPI item '{new_mpi_item}'. Please provide a sheet name for item {item_data.get('item')}."
                )

            # Rest of the method remains the same
            # Process MPI item updates if changed
            if 'mpi_item' in item_data and item_data['mpi_item'] != item.mpi_item:
                background_tasks.add_task(self.update_mpi_field, item_data['item'], 'mpi_item',
                                        item_data['mpi_item'])
            
            # Process MPI description updates if changed
            if 'mpi_description' in item_data and item_data['mpi_description'] != item.mpi_description:
                background_tasks.add_task(self.update_mpi_field, item_data['item'], 'mpi_description',
                                        item_data['mpi_description'])

            # Process sheet_name updates if changed
            if 'sheet_name' in item_data and item_data['sheet_name'] != item.sheet_name:
                background_tasks.add_task(self.update_mpi_field, item_data['item'], 'sheet_name',
                                        item_data['sheet_name'])
            
            # Update mappings table with all the data
            if ('mpi_item' in item_data and item_data['mpi_item'] != item.mpi_item) or \
               ('sheet_name' in item_data and item_data['sheet_name'] != item.sheet_name):
                # Ensure item_data has the sheet_name from either the request or the current item
                if 'sheet_name' not in item_data:
                    item_data['sheet_name'] = item.sheet_name
                    
                background_tasks.add_task(self.update_mappings_table, item_data)

            # Process customer job updates
            if 'customer_job' in item_data and item_data['customer_job'] != item.customer_job:
                background_tasks.add_task(self.update_customer_job, item.customer_job, 'customer_job',
                                         item_data['customer_job'])
                CustomerJobMappingController(self.db_context).update_mappings_table(
                    old_customer_job=item.customer_job,
                    new_customer_job=item_data['customer_job']
                )

            # Update the item with all provided fields
            for key, value in item_data.items():
                if hasattr(item, key):  # Only update fields that exist on the model
                    setattr(item, key, value)

            self.db_context.add(item)
        self.db_context.commit()

    def update_mpi_field(self, item_value: str, field_name: str, new_value: str):
        self.db_context.query(InvoiceItem).filter(InvoiceItem.item == item_value).update({field_name: new_value})
        self.db_context.commit()

    def update_customer_job(self, item_value: str, field_name: str, new_value: str):
        self.db_context.query(InvoiceItem).filter(InvoiceItem.customer_job == item_value).update(
            {field_name: new_value})
        self.db_context.commit()

    def update_mappings_table(self, updated_values: dict):
        try:
            supplier_id, _ = extract_supplier_id(updated_values.get('vendor', ''))
            
            # Get the MPI item code
            mpi_item = updated_values.get('mpi_item', '')
            
            # Check if it's a valid MPI item
            is_valid_mpi = (mpi_item and 
                           mpi_item.lower() != "no match" and 
                           not mpi_item.startswith("UIDI"))
            
            # For valid MPI items, ensure sheet_name is provided
            if is_valid_mpi and not updated_values.get('sheet_name'):
                logger.error(f"Cannot update mapping - sheet_name missing for valid MPI item: {updated_values}")
                return  # Skip the mapping update
            
            # Create mapping data with all available fields
            mapping_data = {
                "supplier_item_ids": updated_values.get('item', ''),
                "description": updated_values.get('mpi_description', ''),
                "mpi_code": updated_values.get('mpi_item', ''),
                "google_sheet_name": updated_values.get('sheet_name', '')
            }
            
            # Log what we're about to do
            logger.info(f"Updating mapping with data: {mapping_data}")
            
            # Only update the mapping if we have a supplier_id and supplier_item_ids
            if supplier_id and mapping_data["supplier_item_ids"]:
                ItemsMappingController(self.db_context).update_mapping(supplier_id, mapping_data)
            else:
                logger.error(f"Missing required data for mapping update: supplier_id={supplier_id}, item={mapping_data['supplier_item_ids']}")
        
        except Exception as e:
            # Log any errors that occur
            logger.error(f"Error in update_mappings_table: {str(e)}")

    def sort(self, db, column, sort_order):
        if sort_order == 'ascending':
            order = asc(column)
        elif sort_order == 'descending':
            order = desc(column)
        else:
            raise HTTPException(status_code=400, detail="Invalid sort order")

        invoice_items = self.db_context.query(InvoiceItem).order_by(order).all()
        invoices_items = []
        for item in invoice_items:
            item_dict = item.__dict__.copy()
            # Replace the item field with the suffixed version for display
            item_dict['item'] = item.item_code_with_suffix
            invoices_items.append(InvoiceItemsResponse(**item_dict))
        return invoices_items

    def get_customer_jobs(self, db):
        customer_jobs = db.query(InvoiceItem.customer_job).distinct().all()
        return customer_jobs

    def get_data_by_column_name(self, column_name, filter_context, comparison_filters):
        """
        Used to generates drop down filters for data-review table header.
        Args:
        column_name: the column we want the values for.
        filter_context: the previous selected columns / previous applied filters
        """

        # Special handling for 'item' column to return suffixed values
        if column_name == "item":
            query = self.db_context.query(InvoiceItem)
            
            # applying comparison (>,<= etc) filters
            for comp_filter in comparison_filters:
                if not hasattr(InvoiceItem, comp_filter['column']):
                    raise HTTPException(status_code=400, detail=f"Invalid column name: {comp_filter['column']}")

                column = getattr(InvoiceItem, comp_filter['column'])

                # Special handling for 'amount' column (string to float conversion)
                if comp_filter['column'] == "amount":
                    column = cast(column, Float)

                # Handle type casting for comparison filters
                try:
                    if comp_filter['column'] == "amount":
                        try:
                            value = float(comp_filter['value'])
                        except ValueError:
                            continue  # Skip invalid float conversion
                    elif column.type.python_type == int:
                        value = int(comp_filter['value'])
                    elif column.type.python_type == float:
                        value = float(comp_filter['value'])
                    elif column.type.python_type == date:
                        value = date.fromisoformat(comp_filter['value'])
                    else:
                        value = comp_filter['value']
                except (ValueError, TypeError):
                    raise HTTPException(status_code=400, detail=f"Invalid value type for column: {comp_filter['column']}")

                if comp_filter['operator'] == "gt":
                    query = query.filter(column > value)
                elif comp_filter['operator'] == "lt":
                    query = query.filter(column < value)
                elif comp_filter['operator'] == "gte":
                    query = query.filter(column >= value)
                elif comp_filter['operator'] == "lte":
                    query = query.filter(column <= value)
                elif comp_filter['operator'] == "eq":
                    query = query.filter(column == value)
                else:
                    raise HTTPException(status_code=400, detail=f"Invalid operator: {comp_filter['operator']}")

            if filter_context:  # if there are previous filter selections -> add them in query
                for filter_col_name in filter_context.keys():
                    filter_column = getattr(InvoiceItem, filter_col_name)
                    query = query.filter(filter_column.in_(filter_context[filter_col_name]))

            # Get all matching items and extract suffixed item codes
            items = query.all()
            suffixed_items = [item.item_code_with_suffix for item in items if item.item_code_with_suffix is not None]
            # Return unique sorted values
            return sorted(list(set(suffixed_items)))
        
        # Original logic for other columns
        my_column_name = getattr(InvoiceItem, column_name)
        query = self.db_context.query(distinct(my_column_name))

        # applying comparison (>,<= etc) filters
        for comp_filter in comparison_filters:
            if not hasattr(InvoiceItem, comp_filter['column']):
                raise HTTPException(status_code=400, detail=f"Invalid column name: {comp_filter['column']}")

            column = getattr(InvoiceItem, comp_filter['column'])

            # Special handling for 'amount' column (string to float conversion)
            if comp_filter['column'] == "amount":
                column = cast(column, Float)

            # Handle type casting for comparison filters
            try:
                if comp_filter['column'] == "amount":
                    try:
                        value = float(comp_filter['value'])
                    except ValueError:
                        continue  # Skip invalid float conversion
                elif column.type.python_type == int:
                    value = int(comp_filter['value'])
                elif column.type.python_type == float:
                    value = float(comp_filter['value'])
                elif column.type.python_type == date:
                    value = date.fromisoformat(comp_filter['value'])
                else:
                    value = comp_filter['value']
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail=f"Invalid value type for column: {comp_filter['column']}")

            if comp_filter['operator'] == "gt":
                query = query.filter(column > value)
            elif comp_filter['operator'] == "lt":
                query = query.filter(column < value)
            elif comp_filter['operator'] == "gte":
                query = query.filter(column >= value)
            elif comp_filter['operator'] == "lte":
                query = query.filter(column <= value)
            elif comp_filter['operator'] == "eq":
                query = query.filter(column == value)
            else:
                raise HTTPException(status_code=400, detail=f"Invalid operator: {comp_filter['operator']}")

        if filter_context:  # if there are previous filter selections -> add them in query
            for column in filter_context.keys():
                filter_column = getattr(InvoiceItem, column)
                query = query.filter(filter_column.in_(filter_context[column]))

        distinct_values = query.order_by(my_column_name.asc()).all()
        return [value[0] for value in distinct_values if value[0] is not None]

    def apply_filters(self, request, page, size, col_param=None):
        query = self.db_context.query(InvoiceItem)

        # applying 'IN' filters dynamically
        for column_name, values in request.filters.items():
            if not hasattr(InvoiceItem, column_name):
                raise HTTPException(status_code=400, detail=f"Invalid column name: {column_name}")

            column = getattr(InvoiceItem, column_name)
            
            # Special handling for 'item' column - convert suffixed values back to original values
            if column_name == "item":
                original_values = []
                for value in values:
                    # Remove suffix to get original item code for database filtering
                    original_value = self._remove_suffix_from_item_code(value)
                    original_values.append(original_value)
                query = query.filter(column.in_(original_values))
            else:
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

        if request.order_by:  # applying sorting
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
            if col_param:  # select distinct values of certain column
                column = getattr(InvoiceItem, col_param, None)
                if column is None:
                    raise HTTPException(status_code=400, detail=f"Invalid column name: {col_param}")

                # When using order_by with distinct, we need to include the ordered columns in the selection
                if request.order_by:
                    select_columns = [column]
                    order_columns = []
                    
                    for order_filter in request.order_by:
                        if hasattr(InvoiceItem, order_filter.column):
                            order_col = getattr(InvoiceItem, order_filter.column)
                            order_columns.append(order_col)
                            # Add to select columns if not already there
                            if order_col not in select_columns:
                                select_columns.append(order_col)
                    
                    # Query with both the requested column and the order columns
                    query_with_columns = query.with_entities(*select_columns).distinct()
                    
                    # Apply ordering
                    for order_filter in request.order_by:
                        if hasattr(InvoiceItem, order_filter.column):
                            order_col = getattr(InvoiceItem, order_filter.column)
                            if order_filter.order == "asc":
                                query_with_columns = query_with_columns.order_by(order_col.asc())
                            else:
                                query_with_columns = query_with_columns.order_by(order_col.desc())
                    
                    results = query_with_columns.all()
                    
                    # Extract just the requested column values
                    return [row[0] for row in results]
                else:
                    # Original behavior for queries without order_by
                    return [row[0] for row in query.with_entities(column).distinct().order_by(column).all()]

            results = query.all()
            size = 1
            total = query.count()
        else:
            total = query.count()
            query = query.limit(size).offset((page - 1) * size)
            results = query.all()

        invoices_items = []
        for item in results:
            item_dict = item.__dict__.copy()
            # Replace the item field with the suffixed version for display
            item_dict['item'] = item.item_code_with_suffix
            invoices_items.append(InvoiceItemsResponse(**item_dict))

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
                cost=item.cost, qty=item.qty, invoice_id=str(item.invoice_id))
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
                column = cast(func.replace(column, ',', ''), Float)

            try:
                if comp_filter.column == "amount":
                    try:
                        value = float(comp_filter.value.replace(",", ""))
                    except ValueError:
                        raise HTTPException(status_code=400, detail=f"Invalid amount format: {comp_filter.value}")
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
        amount_column = cast(func.replace(InvoiceItem.amount, ',', ''), Float)

        aggregates = query.with_entities(
            func.sum(InvoiceItem.qty).label('total_qty'),
            func.sum(amount_column).label('total_amount'),
            func.avg(InvoiceItem.cost).label('average_cost')
        ).first()

        total_qty = 0 if aggregates.total_qty is None else int(aggregates.total_qty)

        if aggregates.total_amount is None:
            total_amount = 0.0
        else:
            try:
                total_amount = float(aggregates.total_amount)
            except (TypeError, ValueError):
                total_amount = 0.0

        if aggregates.average_cost is None:
            average_cost = 0.0
        else:
            try:
                average_cost = float(aggregates.average_cost)
            except (TypeError, ValueError):
                average_cost = 0.0

        def sanitize_float(value: float) -> float:
            if math.isinf(value) or math.isnan(value):
                return 0.0
            return round(value, 2)

        return {
            "total_qty": total_qty,
            "total_amount": sanitize_float(total_amount),
            "average_cost": sanitize_float(average_cost)
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

        if not item_numbers:  # No items to process
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

    def get_invoice_items_raw(self, invoice_id=None):
        """
        Get invoice items as raw SQLAlchemy objects for QuickBooks export.
        This avoids Pydantic conversion issues that can cause missing fields in DataFrames.
        """
        query = self.db_context.query(InvoiceItem)
        if invoice_id:
            query = query.filter(InvoiceItem.invoice_id == invoice_id)
        query = query.order_by(InvoiceItem.id.desc())
        items = query.all()
        return items
