from datetime import date, datetime, timedelta
from sqlalchemy import asc, desc, case, cast, Float, func, and_, or_
from fastapi import HTTPException, BackgroundTasks
from typing import List, Dict
from math import ceil
from mpi_backend.database.models import InvoiceItem
# Import moved inside methods to avoid circular imports
from mpi_backend.database.controllers.CustomerJobMappingContorller import (
    CustomerJobMappingController
)
from mpi_backend.database.schemas import InvoiceItems as InvoiceItemsResponse
from mpi_backend.database.schemas import PriceHistoryResponse
from mpi_backend.utils.export_utils import extract_supplier_id
import math
import logging
import sqlalchemy.orm
from sqlalchemy.orm import load_only
import time
from functools import lru_cache
import hashlib
import json

logger = logging.getLogger(__name__)


class InvoiceItemController:
    def __init__(self, db):
        self.db_context = db

    def _calculate_item_with_suffix(self, item, vendor):
        """
        Calculate item code with suffix based on vendor.
        Replicates the logic from InvoiceItem.item_code_with_suffix property.
        """
        if not item:
            return item
        
        # Import here to avoid circular imports
        from mpi_backend.database.models.InvoiceItems import InvoiceItem
        
        # Exclude tax and administrative items from getting suffixes
        item_str = str(item).strip()
        excluded_items = [
            "tax", "freight", "shipping", "handling", "subtotal", "total"
        ]
        if (item_str.startswith("10 Materials") or 
                item_str.lower() in excluded_items):
            return item
        
        # Get suffix for the supplier
        suffix = ""
        if vendor:
            # Check for exact supplier name matches and partial matches
            for supplier_name, supplier_suffix in InvoiceItem.SUPPLIER_SUFFIX_MAP.items():
                if supplier_name in vendor:
                    suffix = supplier_suffix
                    break
        
        if not suffix:
            return item
        
        # Remove ALL existing suffixes first (including double suffixes)
        all_suffixes = set(InvoiceItem.SUPPLIER_SUFFIX_MAP.values())
        all_suffixes.discard("")  # Remove empty suffix
        
        clean_item = item_str
        # Keep removing suffixes until none are found
        while True:
            found_suffix = False
            for existing_suffix in all_suffixes:
                if existing_suffix and clean_item.endswith(existing_suffix):
                    clean_item = clean_item[:-len(existing_suffix)]
                    found_suffix = True
                    break
            if not found_suffix:
                break
        
        # Return item code with suffix
        return f"{clean_item}{suffix}"

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
        
        # Apply empty item filter
        query = self._apply_empty_item_filter(query)
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
        Optimized for large batches by processing in chunks.

        Args:
            ids (list): A list of InvoiceItem IDs to update.

        Returns:
            int: The number of records updated.
        """
        if not ids:
            logger.warning('Invoice Item Row IDs not provided')
            return 0

        # Process in batches to avoid memory issues and improve performance
        batch_size = 1000
        total_updated = 0

        try:
            # Process IDs in batches
            for i in range(0, len(ids), batch_size):
                batch_ids = ids[i:i+batch_size]
                logger.debug(f"Processing batch {i//batch_size + 1} with {len(batch_ids)} items")

                # Use direct SQL for better performance with large batches
                query = self.db_context.query(InvoiceItem).filter(InvoiceItem.id.in_(batch_ids))
                updated_count = query.update({"export_status": "Sent"}, synchronize_session='fetch')
                total_updated += updated_count

                # Commit after each batch to avoid large transactions
                self.db_context.commit()

            logger.info(f"Updated export status for {total_updated} invoice items")
            return total_updated

        except Exception as e:
            self.db_context.rollback()
            logger.error(f"Error updating export status: {str(e)}")
            raise


    def is_exported(self, invoice_id):
        """
        Checks if all invoice items for the given invoice_id have export_status as 'Sent'.
        Optimized to use a count query instead of loading all items into memory.

        Args:
            invoice_id (str): The ID of the invoice to check.

        Returns:
            bool: True if all items are 'Sent', False if any item is 'Pending'.
        """
        try:
            # Count total items for this invoice
            total_count = self.db_context.query(func.count(InvoiceItem.id))\
                .filter(InvoiceItem.invoice_id == invoice_id)\
                .scalar()
                
            if total_count == 0:
                return False
                
            # Count items with 'Sent' status
            sent_count = self.db_context.query(func.count(InvoiceItem.id))\
                .filter(InvoiceItem.invoice_id == invoice_id)\
                .filter(InvoiceItem.export_status == "Sent")\
                .scalar()
                
            # All items are exported if counts match
            return sent_count == total_count
            
        except Exception as e:
            logger.error(f"Error checking export status for invoice {invoice_id}: {str(e)}")
            return False

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
                # Lazy import to avoid circular imports
                from mpi_backend.database.controllers.ItemsMappingController import ItemsMappingController
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

    @lru_cache(maxsize=128)
    def _get_cached_distinct_values(self, column_name: str, filter_context_hash: str, comparison_filters_hash: str):
        """
        Cached version of distinct value fetching for better performance.
        Uses hashed filter context to enable caching while maintaining filter functionality.
        """
        # Parse the hashes back to original data (in production, you might want a more sophisticated cache)
        # For now, we'll implement the core optimization without relying on the hash parsing
        return self._get_distinct_values_optimized(column_name, None, [])
    
    def _create_filter_hash(self, filter_context: Dict, comparison_filters: List) -> tuple:
        """Create a hash from filter context and comparison filters for caching."""
        filter_str = json.dumps(filter_context or {}, sort_keys=True)
        comparison_str = json.dumps([
            {k: v for k, v in f.items() if k in ['column', 'operator', 'value']} 
            for f in (comparison_filters or [])
        ], sort_keys=True)
        
        filter_hash = hashlib.md5(filter_str.encode()).hexdigest()
        comparison_hash = hashlib.md5(comparison_str.encode()).hexdigest()
        return filter_hash, comparison_hash
    
    def _get_distinct_values_optimized(self, column_name: str, filter_context: Dict, comparison_filters: List):
        """
        Optimized version of distinct value fetching with better query performance.
        """
        start_time = time.time()
        
        # Special handling for 'item' column to return suffixed values efficiently
        if column_name == "item":
            # Use a more efficient query that only selects needed columns
            query = self.db_context.query(InvoiceItem.item, InvoiceItem.vendor)
            
            # Apply filters more efficiently
            query = self._apply_comparison_filters_optimized(query, comparison_filters)
            query = self._apply_context_filters_optimized(query, filter_context)
            
            # Execute query and process results in batches to reduce memory usage
            batch_size = 5000
            all_suffixed_items = set()
            offset = 0
            
            while True:
                batch_query = query.limit(batch_size).offset(offset)
                batch_results = batch_query.all()
                
                if not batch_results:
                    break
                    
                # Process batch to get suffixed items
                for item, vendor in batch_results:
                    if item:
                        # Use the suffix calculation logic directly
                        suffixed_item = self._calculate_item_with_suffix(item, vendor)
                        if suffixed_item:
                            all_suffixed_items.add(suffixed_item)
                
                offset += batch_size
                
                # Break if we got fewer results than batch size (last batch)
                if len(batch_results) < batch_size:
                    break
            
            result = sorted(list(all_suffixed_items))
            logging.info(f"Item column distinct values query took {time.time() - start_time:.2f}s, returned {len(result)} items")
            return result
        
        # Optimized query for other columns
        column_attr = getattr(InvoiceItem, column_name)
        
        # Use a more efficient distinct query with only the required column
        query = self.db_context.query(column_attr).distinct()
        
        # Apply filters efficiently
        query = self._apply_comparison_filters_optimized(query, comparison_filters)
        query = self._apply_context_filters_optimized(query, filter_context)
        
        # Use database-level ordering for better performance
        query = query.order_by(column_attr.asc())
        
        # Execute query
        distinct_values = query.all()
        result = [value[0] for value in distinct_values if value[0] is not None]
        
        logging.info(f"Column '{column_name}' distinct values query took {time.time() - start_time:.2f}s, returned {len(result)} values")
        return result
    
    def _apply_comparison_filters_optimized(self, query, comparison_filters: List):
        """
        Optimized version of comparison filter application.
        """
        if not comparison_filters:
            return query
            
        for comp_filter in comparison_filters:
            if not hasattr(InvoiceItem, comp_filter['column']):
                continue  # Skip invalid columns instead of raising exception for better performance
                
            column = getattr(InvoiceItem, comp_filter['column'])
            
            # Special handling for 'amount' column (string to float conversion)
            if comp_filter['column'] == "amount":
                column = cast(column, Float)
            
            # Handle type casting for comparison filters with better error handling
            try:
                value = self._convert_filter_value(comp_filter, column)
                query = self._apply_operator_filter(query, column, comp_filter['operator'], value)
            except (ValueError, TypeError):
                continue  # Skip invalid values instead of raising exception
                
        return query
    
    def _apply_context_filters_optimized(self, query, filter_context: Dict):
        """
        Optimized version of context filter application.
        """
        if not filter_context:
            return query
            
        for filter_col_name, values in filter_context.items():
            if not hasattr(InvoiceItem, filter_col_name):
                continue  # Skip invalid columns
                
            filter_column = getattr(InvoiceItem, filter_col_name)
            
            # Use more efficient IN clause with batch processing for large value lists
            if len(values) > 1000:  # For very large filter lists, use batch processing
                # Split into smaller batches to avoid SQL query limits
                batch_conditions = []
                batch_size = 1000
                for i in range(0, len(values), batch_size):
                    batch_values = values[i:i + batch_size]
                    batch_conditions.append(filter_column.in_(batch_values))
                query = query.filter(or_(*batch_conditions))
            else:
                query = query.filter(filter_column.in_(values))
                
        return query
    
    def _convert_filter_value(self, comp_filter: Dict, column):
        """
        Optimized value conversion with better error handling.
        """
        if comp_filter['column'] == "amount":
            return float(comp_filter['value'])
        elif hasattr(column.type, 'python_type'):
            if column.type.python_type == int:
                return int(comp_filter['value'])
            elif column.type.python_type == float:
                return float(comp_filter['value'])
            elif column.type.python_type == date:
                return date.fromisoformat(comp_filter['value'])
        return comp_filter['value']
    
    def _apply_operator_filter(self, query, column, operator: str, value):
        """
        Optimized operator filter application.
        """
        operator_map = {
            "gt": column > value,
            "lt": column < value,
            "gte": column >= value,
            "lte": column <= value,
            "eq": column == value
        }
        
        if operator in operator_map:
            return query.filter(operator_map[operator])
        return query

    def get_data_by_column_name(self, column_name, filter_context, comparison_filters):
        """
        Optimized version of get_data_by_column_name with caching and better performance.
        Now handles 10,000+ records efficiently.
        """
        start_time = time.time()
        
        # Create cache keys for filter context and comparison filters
        filter_hash, comparison_hash = self._create_filter_hash(filter_context, comparison_filters or [])
        
        # For frequently accessed columns, use caching
        cacheable_columns = ['vendor', 'customer_job', 'class_', 'export_status']
        if column_name in cacheable_columns and not filter_context and not comparison_filters:
            try:
                return self._get_cached_distinct_values(column_name, filter_hash, comparison_hash)
            except:
                pass  # Fall back to non-cached version if caching fails
        
        # Use the optimized implementation
        result = self._get_distinct_values_optimized(column_name, filter_context, comparison_filters or [])
        
        logging.info(f"get_data_by_column_name for '{column_name}' took {time.time() - start_time:.2f}s")
        return result

    def apply_filters(self, request, page, size, col_param=None):
        """
        Heavily optimized version of apply_filters for handling 10,000+ records efficiently.
        Implements streaming, batch processing, and memory optimization.
        """
        start_time = time.time()
        
        # Use optimized query building
        query = self._build_optimized_filter_query(request)
        
        # Handle special case for column parameter (used for distinct values)
        if size == 0 and col_param:
            return self._handle_column_param_optimized(query, request, col_param)
        
        # For large datasets, optimize the query execution
        if size == 0:  # Get all results
            return self._execute_large_dataset_query(query, request)
        else:  # Paginated results
            return self._execute_paginated_query(query, request, page, size)
    
    def _build_optimized_filter_query(self, request):
        """
        Build an optimized query with all filters applied.
        """
        # Start with base query - only select columns we need for better performance
        query = self.db_context.query(InvoiceItem).options(
            # Load only the columns we actually use to reduce memory usage
            load_only(
                InvoiceItem.id,
                InvoiceItem.filename,
                InvoiceItem.sheet_name,
                InvoiceItem.mpi_item,
                InvoiceItem.mpi_description,
                InvoiceItem.item,
                InvoiceItem.description,
                InvoiceItem.qty,
                InvoiceItem.cost,
                InvoiceItem.amount,
                InvoiceItem.date,
                InvoiceItem.ref_no,
                InvoiceItem.po_number,
                InvoiceItem.customer_job,
                InvoiceItem.bill,
                InvoiceItem.vendor,
                InvoiceItem.class_,
                InvoiceItem.memo,
                InvoiceItem.buyer,
                InvoiceItem.date_added,
                InvoiceItem.export_status,
                InvoiceItem.invoice_id,
                InvoiceItem.is_active
            )
        )
        
        # Apply empty item filter
        query = self._apply_empty_item_filter(query)
        
        # Apply 'IN' filters with optimization for large value lists
        for column_name, values in request.filters.items():
            if not hasattr(InvoiceItem, column_name):
                continue  # Skip invalid columns
                
            column = getattr(InvoiceItem, column_name)
            
            # Special handling for 'item' column - convert suffixed values back to original values
            if column_name == "item":
                original_values = []
                for value in values:
                    original_value = self._remove_suffix_from_item_code(value)
                    original_values.append(original_value)
                values = original_values
            
            # Optimize large IN clauses
            if len(values) > 1000:
                # Split into smaller batches for better database performance
                batch_conditions = []
                batch_size = 1000
                for i in range(0, len(values), batch_size):
                    batch_values = values[i:i + batch_size]
                    batch_conditions.append(column.in_(batch_values))
                query = query.filter(or_(*batch_conditions))
            else:
                query = query.filter(column.in_(values))
        
        # Apply comparison filters efficiently
        for comp_filter in request.comparison_filters:
            if not hasattr(InvoiceItem, comp_filter.column):
                continue  # Skip invalid columns
                
            column = getattr(InvoiceItem, comp_filter.column)
            
            # Special handling for 'amount' column (string to float conversion)
            if comp_filter.column == "amount":
                column = cast(column, Float)
            
            try:
                value = self._convert_filter_value(comp_filter.__dict__, column)
                query = self._apply_operator_filter(query, column, comp_filter.operator, value)
            except (ValueError, TypeError):
                continue  # Skip invalid values
        
        # Apply sorting efficiently
        if request.order_by:
            for order_filter in request.order_by:
                if not hasattr(InvoiceItem, order_filter.column):
                    continue
                    
                column = getattr(InvoiceItem, order_filter.column)
                if order_filter.order == "asc":
                    query = query.order_by(column.asc())
                elif order_filter.order == "desc":
                    query = query.order_by(column.desc())
        
        return query
    
    def _handle_column_param_optimized(self, query, request, col_param):
        """
        Optimized handling of column parameter for distinct value extraction.
        """
        column = getattr(InvoiceItem, col_param, None)
        if column is None:
            raise HTTPException(status_code=400, detail=f"Invalid column name: {col_param}")
        
        # Use efficient distinct query
        if request.order_by:
            # For ordered results, we need to include order columns in the selection
            select_columns = [column]
            
            for order_filter in request.order_by:
                if hasattr(InvoiceItem, order_filter.column):
                    order_col = getattr(InvoiceItem, order_filter.column)
                    if order_col not in select_columns:
                        select_columns.append(order_col)
            
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
            return [row[0] for row in results if row[0] is not None]
        else:
            # Optimized query for non-ordered results
            results = query.with_entities(column).distinct().order_by(column).all()
            return [row[0] for row in results if row[0] is not None]
    
    def _execute_large_dataset_query(self, query, request):
        """
        Execute query for large datasets (size=0) with memory optimization.
        """
        start_time = time.time()
        
        # Get total count efficiently
        total = query.count()
        
        # For very large results, use streaming/batching
        if total > 5000:
            results = self._stream_large_results(query, batch_size=2000)
        else:
            results = query.all()
        
        # Process results efficiently
        invoices_items = self._process_results_batch(results)
        
        logging.info(f"Large dataset query (total: {total}) took {time.time() - start_time:.2f}s")
        
        return {
            "items": invoices_items,
            "total": total,
            "page": 1,
            "size": 1,
            "pages": 1
        }
    
    def _execute_paginated_query(self, query, request, page, size):
        """
        Execute paginated query with optimization.
        """
        start_time = time.time()
        
        # Get total count efficiently
        total = query.count()
        
        # Apply pagination
        query = query.limit(size).offset((page - 1) * size)
        results = query.all()
        
        # Process results
        invoices_items = self._process_results_batch(results)
        
        logging.info(f"Paginated query (page {page}, size {size}) took {time.time() - start_time:.2f}s")
        
        return {
            "items": invoices_items,
            "total": total,
            "page": page,
            "size": size,
            "pages": ceil(total / size)
        }
    
    def _stream_large_results(self, query, batch_size=2000):
        """
        Stream large result sets in batches to reduce memory usage.
        """
        offset = 0
        all_results = []
        
        while True:
            batch_query = query.limit(batch_size).offset(offset)
            batch_results = batch_query.all()
            
            if not batch_results:
                break
                
            all_results.extend(batch_results)
            offset += batch_size
            
            # Break if we got fewer results than batch size (last batch)
            if len(batch_results) < batch_size:
                break
        
        return all_results
    
    def _process_results_batch(self, results):
        """
        Process results in an optimized way with minimal memory overhead.
        """
        invoices_items = []
        
        for item in results:
            # Use a more efficient approach to create the response object
            item_dict = {
                'id': item.id,
                'filename': item.filename,
                'sheet_name': item.sheet_name,
                'mpi_item': item.mpi_item,
                'mpi_description': item.mpi_description,
                'item': item.item_code_with_suffix,  # Use the property directly
                'description': item.description,
                'qty': item.qty,
                'cost': item.cost,
                'amount': item.amount,
                'date': item.date,
                'ref_no': item.ref_no,
                'po_number': item.po_number,
                'customer_job': item.customer_job,
                'bill': item.bill,
                'vendor': item.vendor,
                'class_': item.class_,
                'memo': item.memo,
                'buyer': item.buyer,
                'date_added': item.date_added,
                'export_status': item.export_status,
                'invoice_id': item.invoice_id,
                'is_active': item.is_active
            }
            
            invoices_items.append(InvoiceItemsResponse(**item_dict))
        
        return invoices_items

    def get_price_history(self, request):
        """
        Get price history for a specific item and vendor.
        
        Args:
            request: PriceHistoryRequest with item_number, vendor, and description
            
        Returns:
            List[PriceHistoryResponse]: Price history records sorted by date (newest first)
        """
        try:
            logger.info(f"Getting price history for item: {request.item_number}, "
                       f"vendor: {request.vendor}")
            
            # Clean and prepare search terms
            original_item = request.item_number.strip()
            original_vendor = request.vendor.strip()
            
            # Handle potential suffix issues - create multiple search variations
            from mpi_backend.utils.item_utils import clean_supplier_suffix
            
            # Prepare item code variations for search
            item_variations = [original_item]
            
            # Add cleaned version (without suffix)
            cleaned_item = clean_supplier_suffix(original_item)
            if cleaned_item != original_item:
                item_variations.append(cleaned_item)
            
            # Add common suffix variations for this vendor
            from mpi_backend.database.models.Suppliers import Supplier
            vendor_query = self.db_context.query(Supplier).filter(
                Supplier.supplier_name.ilike(f"%{original_vendor}%")
            ).first()
            
            if vendor_query:
                from mpi_backend.utils.item_utils import get_supplier_suffix
                suffix = get_supplier_suffix(vendor_query.id)
                if suffix:
                    # Add suffixed version if it doesn't already exist
                    suffixed_item = f"{cleaned_item}-{suffix}"
                    if suffixed_item not in item_variations:
                        item_variations.append(suffixed_item)
            
            logger.info(f"Searching for item variations: {item_variations}")
            
            # Build query with multiple item code variations
            query = self.db_context.query(InvoiceItem)
            
            # More flexible item matching - search for any of the variations
            item_filter = or_(*[InvoiceItem.item.ilike(item_var) 
                               for item_var in item_variations])
            query = query.filter(item_filter)
            
            # More flexible vendor matching - case insensitive and partial
            vendor_filter = or_(
                InvoiceItem.vendor.ilike(f"%{original_vendor}%"),
                InvoiceItem.vendor.ilike(original_vendor),
                InvoiceItem.vendor == original_vendor
            )
            query = query.filter(vendor_filter)
            
            # Apply basic filters (not the restrictive empty item filter)
            query = query.filter(
                InvoiceItem.item.isnot(None),
                InvoiceItem.item != "",
                InvoiceItem.vendor.isnot(None),
                InvoiceItem.vendor != ""
            )
            
            # Filter out items with invalid costs
            query = query.filter(
                InvoiceItem.cost.isnot(None),
                InvoiceItem.cost > 0
            )
            
            # Order by date descending (newest first)
            query = query.order_by(InvoiceItem.date.desc())
            
            matched_items = query.all()
            
            logger.info(f"Found {len(matched_items)} price history records")
            
            if not matched_items:
                logger.warning(f"No price history found for item: "
                              f"{request.item_number}, vendor: {request.vendor}")
                
                # Additional debugging - try to find similar items
                debug_query = self.db_context.query(
                    InvoiceItem.item, 
                    InvoiceItem.vendor, 
                    func.count().label('count')
                ).filter(
                    or_(
                        InvoiceItem.item.ilike(f"%{cleaned_item}%"),
                        InvoiceItem.vendor.ilike(f"%{original_vendor}%")
                    )
                ).group_by(InvoiceItem.item, InvoiceItem.vendor).limit(5).all()
                
                logger.info(f"Similar items found in database: "
                           f"{[(item, vendor, count) for item, vendor, count in debug_query]}")
                return []
            
            response = []
            for item in matched_items:
                try:
                    # Validate required fields
                    if not item.ref_no or not item.date:
                        logger.warning(f"Skipping item with missing ref_no or "
                                      f"date: {item.id}")
                        continue
                        
                    price_record = PriceHistoryResponse(
                        ref_no=item.ref_no,
                        date=item.date.strftime("%m-%d-%Y"),
                        cost=float(item.cost) if item.cost else 0.0,
                        qty=int(item.qty) if item.qty else 0,
                        invoice_id=str(item.invoice_id) if item.invoice_id else ""
                    )
                    response.append(price_record)
                except Exception as e:
                    logger.error(f"Error processing price history item "
                                f"{item.id}: {str(e)}")
                    continue
            
            logger.info(f"Successfully processed {len(response)} "
                       f"price history records")
            return response
            
        except Exception as e:
            logger.error(f"Error in get_price_history: {str(e)}")
            # Return empty list instead of raising exception
            return []

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

        # CRITICAL BUG FIX: Safe casting with validation for amount column
        # This prevents database errors from concatenated text data
        
        # Use CASE statement to handle invalid amounts gracefully
        # Convert only valid numeric amounts, set invalid ones to 0
        safe_amount_case = case(
            (
                and_(
                    InvoiceItem.amount.isnot(None),
                    InvoiceItem.amount != '',
                    # Simple length check - valid amounts should be < 50 chars
                    func.length(InvoiceItem.amount) < 50
                ),
                cast(func.replace(InvoiceItem.amount, ',', ''), Float)
            ),
            else_=0.0
        )

        # Execute query with additional error handling for database issues
        try:
            aggregates = query.with_entities(
                func.sum(InvoiceItem.qty).label('total_qty'),
                func.sum(safe_amount_case).label('total_amount'),
                func.avg(InvoiceItem.cost).label('average_cost')
            ).first()
        except Exception as e:
            logger.error(f"Database error in get_aggregates: {str(e)}")
            # Return default values if query fails
            return {
                "total_qty": 0,
                "total_amount": 0.0,
                "average_cost": 0.0
            }

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

    def get_invoice_items_raw(self, invoice_id=None, batch_size=1000):
        """
        Get invoice items as raw SQLAlchemy objects for QuickBooks export.
        This avoids Pydantic conversion issues that can cause missing fields in DataFrames.
        
        Args:
            invoice_id: Optional invoice ID to filter by
            batch_size: Number of records to fetch in each batch
            
        Returns:
            List of SQLAlchemy objects
        """
        logger.debug(f"Getting raw invoice items for invoice_id: {invoice_id}")
        
        # Explicitly query all columns to avoid any lazy loading issues
        query = self.db_context.query(InvoiceItem)
        
        if invoice_id:
            query = query.filter(InvoiceItem.invoice_id == invoice_id)
            
        # Apply empty item filter
        query = self._apply_empty_item_filter(query)
            
        # Use only the columns we need for better performance
        query = query.options(
            # Load only the columns we need for QuickBooks export
            # This reduces memory usage and improves performance
            sqlalchemy.orm.load_only(
                InvoiceItem.id, 
                InvoiceItem.invoice_id,
                InvoiceItem.sheet_name, 
                InvoiceItem.mpi_item,
                InvoiceItem.item, 
                InvoiceItem.description,
                InvoiceItem.qty, 
                InvoiceItem.cost, 
                InvoiceItem.amount,
                InvoiceItem.date,
                InvoiceItem.ref_no,
                InvoiceItem.customer_job,
                InvoiceItem.vendor,
                InvoiceItem.class_,
                InvoiceItem.memo
            )
        )
        
        # Order by ID for consistent results
        query = query.order_by(InvoiceItem.id.desc())
        
        # For large datasets, use batched loading to reduce memory usage
        if batch_size and batch_size > 0:
            items = []
            offset = 0
            while True:
                batch = query.limit(batch_size).offset(offset).all()
                if not batch:
                    break
                items.extend(batch)
                offset += batch_size
                if len(batch) < batch_size:  # Last batch
                    break
        else:
            items = query.all()
            
        logger.debug(f"Retrieved {len(items)} items for invoice_id: {invoice_id}")
        
        return items

    def get_invoice_items_by_invoice_ids(self, invoice_ids, batch_size=1000):
        """
        Get invoice items by a list of invoice IDs for QuickBooks export.
        This method gets all invoice items that belong to the specified invoices.
        
        Args:
            invoice_ids: List of invoice IDs (can be UUID objects or strings)
            batch_size: Number of records to fetch in each batch for large datasets
            
        Returns:
            List of InvoiceItem objects with necessary attributes loaded
        """
        logger.debug(f"Getting invoice items for {len(invoice_ids) if invoice_ids else 0} invoices")
        
        if not invoice_ids:
            return []
        
        # Convert UUID objects to strings if needed for database query
        processed_invoice_ids = []
        for invoice_id in invoice_ids:
            if hasattr(invoice_id, '__str__'):
                processed_invoice_ids.append(str(invoice_id))
            else:
                processed_invoice_ids.append(invoice_id)
        
        # Build query to get all invoice items for the specified invoices
        query = self.db_context.query(InvoiceItem).filter(
            InvoiceItem.invoice_id.in_(processed_invoice_ids)
        )
        
        # Apply empty item filter
        query = self._apply_empty_item_filter(query)
        
        # Use optimized loading for QuickBooks export - only load necessary columns
        query = query.options(
            sqlalchemy.orm.load_only(
                InvoiceItem.id,
                InvoiceItem.invoice_id,
                InvoiceItem.sheet_name,  # CRITICAL: Added for QuickBooks business logic
                InvoiceItem.mpi_item,    # CRITICAL: Added for QuickBooks business logic
                InvoiceItem.item,
                InvoiceItem.description,
                InvoiceItem.qty,
                InvoiceItem.cost,
                InvoiceItem.amount,
                InvoiceItem.date,
                InvoiceItem.ref_no,
                InvoiceItem.customer_job,
                InvoiceItem.vendor,
                InvoiceItem.class_,
                InvoiceItem.memo,
                InvoiceItem.export_status
            )
        )
        
        # Order by invoice_id and then by id for consistent results
        query = query.order_by(InvoiceItem.invoice_id, InvoiceItem.id)
        
        # For large datasets, use batched loading to reduce memory usage
        if batch_size and batch_size > 0 and len(processed_invoice_ids) > 10:
            items = []
            offset = 0
            while True:
                batch = query.limit(batch_size).offset(offset).all()
                if not batch:
                    break
                items.extend(batch)
                offset += batch_size
                if len(batch) < batch_size:  # Last batch
                    break
        else:
            items = query.all()
        
        logger.debug(f"Retrieved {len(items)} invoice items for {len(processed_invoice_ids)} invoices")
        return items

    def get_suppliers_by_ids(self, supplier_ids):
        """
        Get suppliers by a list of supplier IDs for QuickBooks export.
        
        Args:
            supplier_ids: List of supplier IDs
            
        Returns:
            List of Supplier objects
        """
        if not supplier_ids:
            return []
        
        from mpi_backend.database.models.Suppliers import Supplier
        
        suppliers = self.db_context.query(Supplier).filter(
            Supplier.id.in_(supplier_ids)
        ).all()
        
        logger.debug(f"Retrieved {len(suppliers)} suppliers for {len(supplier_ids)} supplier IDs")
        return suppliers

    def _apply_empty_item_filter(self, query):
        """
        Apply filter to exclude items with empty or invalid item codes.
        Items with empty item codes, dots, or whitespace-only codes are excluded.
        """
        from mpi_backend.database.models.InvoiceItems import InvoiceItem
        
        # Filter out empty, null, or just dot item codes
        query = query.filter(
            InvoiceItem.item.isnot(None),
            InvoiceItem.item != "",
            InvoiceItem.item != ".",
            func.trim(InvoiceItem.item) != "",
            func.trim(InvoiceItem.item) != "."
        )
        
        return query
