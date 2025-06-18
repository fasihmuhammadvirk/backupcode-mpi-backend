from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
import pandas as pd
from mpi_backend.database import get_db, get_qb_db
from mpi_backend.database.controllers import InvoiceItemController,InvoiceController, ItemClassificationController
from mpi_backend.database.schemas import SendtoQBFilterRequest
from mpi_backend.utils.pdf_to_excel.formatting_util import export_batch_entry_to_excel
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
from mpi_backend.config import QB_PRIORITY_MODE, QB_PAUSE_BACKGROUND_JOBS
import os
import threading
import time

router = APIRouter(prefix="/quickbooks",tags=["QuickBooks"])

# Global flag to pause background jobs during QB export
_qb_export_active = False
_qb_export_lock = threading.Lock()

def pause_background_jobs():
    """Signal to pause non-critical background jobs"""
    global _qb_export_active
    if QB_PAUSE_BACKGROUND_JOBS:
        with _qb_export_lock:
            _qb_export_active = True
        try:
            print("🔒 Background jobs paused for QuickBooks priority export")
        except UnicodeEncodeError:
            print("Background jobs paused for QuickBooks priority export")

def resume_background_jobs():
    """Signal to resume background jobs"""
    global _qb_export_active
    if QB_PAUSE_BACKGROUND_JOBS:
        with _qb_export_lock:
            _qb_export_active = False
        try:
            print("🔓 Background jobs resumed after QuickBooks export")
        except UnicodeEncodeError:
            print("Background jobs resumed after QuickBooks export")

def is_qb_export_active():
    """Check if QuickBooks export is currently active"""
    with _qb_export_lock:
        return _qb_export_active

@router.post("/migrate-all")
def migrate_all_invoice_to_QB(request: SendtoQBFilterRequest, 
                             db: Session = Depends(get_qb_db if QB_PRIORITY_MODE else get_db)):
    """
    Migrate all invoices to QuickBooks with optional filters.
    Ultra-high-performance version for massive datasets (20K+ invoices).
    Uses dedicated database connection pool for enterprise performance.
    Returns the download URL for the exported Excel file.
    """
    import time
    start_time = time.time()
    
    # 🏆 ENTERPRISE PRIORITY: Pause background jobs for maximum performance
    pause_background_jobs()
    
    try:
        print(f"🚀 Starting PRIORITY QuickBooks migration with filters: {request}")
        print(f"🔧 Using {'DEDICATED QB' if QB_PRIORITY_MODE else 'SHARED'} database connection")
        
        # Get filtered invoice IDs using the existing filter logic
        filtered_data = InvoiceItemController(db).apply_filters(request, page=1, size=0)
        invoice_ids = [item.invoice_id for item in filtered_data['items']]

        if request.excluded_invoice_ids:  # Handle excluded items from frontend
            invoice_ids = [
                invoice_id for invoice_id in invoice_ids 
                if invoice_id not in request.excluded_invoice_ids
            ]

        invoice_ids = list(set(invoice_ids))  # Make invoice IDs unique
        
        if not invoice_ids:
            raise HTTPException(status_code=400, detail="No invoices found matching the criteria.")
        
        # Extract just the invoice IDs for processing  
        invoice_id_list = [UUID(str(invoice_id)) for invoice_id in invoice_ids]
        
        print(f"📋 Found {len(invoice_id_list)} invoices to process")
        
        # Use the ultra-optimized processing logic from migrate endpoint
        # ULTRA OPTIMIZATION 1: Batch processing for massive datasets
        BATCH_SIZE = 1000  # Process 1000 invoices at a time to manage memory
        total_invoices = len(invoice_id_list)
        
        all_batch_entries = []
        all_invoice_item_ids_to_update = []
        
        # Process invoices in chunks to avoid memory issues
        for batch_start in range(0, total_invoices, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total_invoices)
            batch_invoice_ids = invoice_id_list[batch_start:batch_end]
            
            batch_time = time.time()
            print(f"📦 Processing batch {batch_start//BATCH_SIZE + 1}/{(total_invoices-1)//BATCH_SIZE + 1} ({len(batch_invoice_ids)} invoices)")
            
            # ULTRA OPTIMIZATION 2: Raw SQL query for maximum performance
            from mpi_backend.database.models.InvoiceItems import InvoiceItem
            from sqlalchemy import text
            
            # Use raw SQL for fastest possible data retrieval
            batch_invoice_ids_str = ','.join([f"'{str(id)}'" for id in batch_invoice_ids])
            
            raw_query = text(f"""
                SELECT id, invoice_id, sheet_name, class_, ref_no, mpi_item, customer_job,
                       amount, date, vendor, memo, qty, cost, description, filename, po_number, bill, buyer, mpi_description, date_added
                FROM invoice_items 
                WHERE invoice_id IN ({batch_invoice_ids_str})
                ORDER BY invoice_id
            """)
            
            result = db.execute(raw_query)
            items_data = result.fetchall()
            
            if not items_data:
                continue
            
            # ULTRA OPTIMIZATION 3: Direct DataFrame creation from raw SQL results
            import pandas as pd
            columns = ['id', 'invoice_id', 'sheet_name', 'class_', 'ref_no', 'mpi_item', 'customer_job',
                      'amount', 'date', 'vendor', 'memo', 'qty', 'cost', 'description', 'filename', 'po_number', 'bill', 'buyer', 'mpi_description', 'date_added']
            
            all_items_df = pd.DataFrame(items_data, columns=columns)
            
            # ULTRA OPTIMIZATION 4: Vectorized classification lookup
            unique_sheet_names = all_items_df[
                (all_items_df['sheet_name'].notna()) & 
                (all_items_df['sheet_name'] != '(TAX)')
            ]['sheet_name'].unique()
            
            # Bulk load classifications
            classification_cache = {}
            if len(unique_sheet_names) > 0:
                for sheet_name in unique_sheet_names:
                    classification_cache[sheet_name] = ItemClassificationController(db).get_classification(sheet_name)
            
            # ULTRA OPTIMIZATION 5: Vectorized processing by invoice
            invoice_groups = all_items_df.groupby('invoice_id')
            
            for invoice_id, invoice_items_df in invoice_groups:
                # Calculate tax efficiently
                tax_items = invoice_items_df[invoice_items_df['sheet_name'] == '(TAX)']
                tax = tax_items['amount'].str.replace(',', '').astype(float).sum() if not tax_items.empty else 0
                
                # Filter out TAX items
                line_items_df = invoice_items_df[invoice_items_df['sheet_name'] != '(TAX)'].copy()
                
                if line_items_df.empty:
                    continue
                
                # ULTRA OPTIMIZATION 6: Vectorized account assignment
                line_items_df['account'] = ''
                
                # Class A/L logic - vectorized
                class_a_refs = line_items_df[line_items_df['class_'] == 'A']['ref_no'].unique()
                class_l_refs = line_items_df[line_items_df['class_'] == 'L']['ref_no'].unique()
                
                if len(class_a_refs) > 0:
                    mask = line_items_df['ref_no'].isin(class_a_refs)
                    line_items_df.loc[mask, 'account'] = 'UnInvoiced JIP:Material:Additional Material'
                
                if len(class_l_refs) > 0:
                    mask = line_items_df['ref_no'].isin(class_l_refs) & (line_items_df['account'] == '')
                    line_items_df.loc[mask, 'account'] = 'UnInvoiced JIP:Subcontractors Expense:Labor'
                
                # Apply classifications - vectorized
                unassigned_mask = line_items_df['account'] == ''
                if unassigned_mask.any():
                    line_items_df.loc[unassigned_mask, 'account'] = line_items_df.loc[unassigned_mask, 'sheet_name'].map(
                        lambda x: classification_cache.get(x, '') if x else ''
                    )
                
                # UIDI mappings - vectorized
                uidi_mask = line_items_df['account'] == ''
                uidi_mappings = {
                    'UIDI-Job Materials Purchased': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
                    'UIDI-Job Equipment': 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased',
                    'UIDI-Sprinkler specialty item': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
                    'UIDI-Drainage Material': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
                }
                
                for uidi_item, account in uidi_mappings.items():
                    mask = (line_items_df['mpi_item'] == uidi_item) & uidi_mask
                    line_items_df.loc[mask, 'account'] = account
                
                # Check for unmatched items
                line_items_df['account'] = line_items_df['account'].replace([None, 'None'], '')
                unmatched_items = line_items_df[line_items_df['account'] == '']
                
                if not unmatched_items.empty:
                    unmatched_refs = unmatched_items[['mpi_item', 'ref_no']].drop_duplicates().to_dict('records')
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unmatched items in invoice {invoice_id}: {unmatched_refs}"
                    )
                
                # ULTRA OPTIMIZATION 7: Efficient data type conversion
                line_items_df['amount'] = pd.to_numeric(line_items_df['amount'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
                line_items_df['qty'] = pd.to_numeric(line_items_df['qty'], errors='coerce').fillna(0)
                line_items_df['cost'] = pd.to_numeric(line_items_df['cost'], errors='coerce').fillna(0)
                
                # ULTRA OPTIMIZATION 8: Efficient grouping and aggregation
                batch_entry = line_items_df.groupby(['account', 'ref_no', 'customer_job'], as_index=False).agg({
                    'amount': 'sum',
                    'date': 'first',
                    'vendor': 'first',
                    'memo': 'first',
                    'class_': 'first'
                })
                
                # Format data efficiently
                batch_entry['date'] = pd.to_datetime(batch_entry['date'], errors='coerce').dt.strftime('%m/%d/%Y')
                batch_entry['amount'] = batch_entry['amount'] + tax
                batch_entry['terms'] = ''
                batch_entry['bill due'] = ''
                
                # Rename columns
                batch_entry = batch_entry.rename(columns={
                    'date': 'Date', 
                    'ref_no': 'Ref', 
                    'amount': 'Amount', 
                    'customer_job': 'Customer Job', 
                    'class_': 'Class', 
                    'memo': 'Memo'
                })
                
                # Select final columns
                final_columns = ['Date', 'Ref', 'vendor', 'terms', 'bill due', 'account', 'Amount', 'Memo', 'Customer Job', 'Class']
                batch_entry = batch_entry[final_columns]
                
                all_batch_entries.append(batch_entry)
                
                # BUG FIX: Collect IDs for status update - INCLUDE ALL items (including TAX)
                # This ensures that when invoice ref 158086 is sent to QuickBooks, 
                # ALL items (including TAX items) get their status updated to 'Sent'
                all_item_ids = invoice_items_df['id'].tolist()  # Include both regular and TAX items
                all_invoice_item_ids_to_update.extend(all_item_ids)
            
            batch_time_taken = time.time() - batch_time
            print(f"✅ Batch {batch_start//BATCH_SIZE + 1} completed in {batch_time_taken:.2f}s")
        
        # ULTRA OPTIMIZATION 9: Memory-efficient concatenation
        if not all_batch_entries:
            raise HTTPException(status_code=400, detail="No invoice items found for processing.")
        
        print(f"🔗 Combining {len(all_batch_entries)} batch entries...")
        final_batch_entry = pd.concat(all_batch_entries, ignore_index=True, copy=False)
        
        # ULTRA OPTIMIZATION 10: Bulk status updates
        print(f"💾 Updating status for {len(all_invoice_item_ids_to_update)} items...")
        if all_invoice_item_ids_to_update:
            # Process status updates in chunks for very large datasets
            STATUS_UPDATE_BATCH_SIZE = 5000
            for i in range(0, len(all_invoice_item_ids_to_update), STATUS_UPDATE_BATCH_SIZE):
                batch_ids = all_invoice_item_ids_to_update[i:i+STATUS_UPDATE_BATCH_SIZE]
                InvoiceItemController(db).set_export_status_to_sent(batch_ids)
            
            # Update invoice statuses efficiently
            invoice_controller = InvoiceController(db)
            invoice_item_controller = InvoiceItemController(db)
            
            # Check and update invoice statuses in chunks
            INVOICE_CHECK_BATCH_SIZE = 100
            unique_invoice_ids = list(set(invoice_id_list))
            
            for i in range(0, len(unique_invoice_ids), INVOICE_CHECK_BATCH_SIZE):
                batch_invoice_ids = unique_invoice_ids[i:i+INVOICE_CHECK_BATCH_SIZE]
                for invoice_id in batch_invoice_ids:
                    if invoice_item_controller.is_exported(str(invoice_id)):
                        invoice_controller.set_invoice_is_exported(str(invoice_id))
        
        # Generate Excel file
        print(f"📊 Generating Excel file for {len(final_batch_entry)} rows...")
        exported_file_path = export_batch_entry_to_excel(final_batch_entry)
        file_name = os.path.basename(exported_file_path)
        
        # Upload to S3
        print(f"☁️ Uploading {file_name} to S3...")
        upload_file(
            exported_file_path, 
            file_key=f'Exports/{file_name}', 
            is_invoice=False
        )
        download_url = get_presigned_url(
            file_key=f'Exports/{file_name}', 
            is_invoice=False
        )
        
        total_time = time.time() - start_time
        print(f"🎉 PRIORITY QuickBooks migration completed in {total_time:.2f}s for {total_invoices} invoices!")
        
        return download_url
    
    finally:
        # 🔓 Always resume background jobs, even if export fails
        resume_background_jobs()


@router.post("/migrate")
def migrate_invoice_to_QB(
        invoice_ids: List[UUID], 
        db: Session = Depends(get_qb_db if QB_PRIORITY_MODE else get_db)):
    """
    Migrate specific invoices to QuickBooks by invoice IDs.
    Ultra-high-performance version for massive datasets (20K+ invoices).
    Uses dedicated database connection pool for enterprise performance.
    Returns the download URL for the exported Excel file.
    """
    import time
    start_time = time.time()
    
    # 🏆 ENTERPRISE PRIORITY: Pause background jobs for maximum performance
    pause_background_jobs()
    
    try:
        # ULTRA OPTIMIZATION 1: Batch processing for massive datasets
        BATCH_SIZE = 1000  # Process 1000 invoices at a time to manage memory
        total_invoices = len(invoice_ids)
        
        print(f"🚀 Processing {total_invoices} invoices in PRIORITY mode with batches of {BATCH_SIZE}")
        print(f"🔧 Using {'DEDICATED QB' if QB_PRIORITY_MODE else 'SHARED'} database connection")
        
        all_batch_entries = []
        all_invoice_item_ids_to_update = []
        
        # Process invoices in chunks to avoid memory issues
        for batch_start in range(0, total_invoices, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total_invoices)
            batch_invoice_ids = invoice_ids[batch_start:batch_end]
            
            batch_time = time.time()
            print(f"📦 Processing batch {batch_start//BATCH_SIZE + 1}/{(total_invoices-1)//BATCH_SIZE + 1} ({len(batch_invoice_ids)} invoices)")
            
            # ULTRA OPTIMIZATION 2: Raw SQL query for maximum performance
            from mpi_backend.database.models.InvoiceItems import InvoiceItem
            from sqlalchemy import text
            
            # Use raw SQL for fastest possible data retrieval
            batch_invoice_ids_str = ','.join([f"'{str(id)}'" for id in batch_invoice_ids])
            
            raw_query = text(f"""
                SELECT id, invoice_id, sheet_name, class_, ref_no, mpi_item, customer_job,
                       amount, date, vendor, memo, qty, cost, description, filename, po_number, bill, buyer, mpi_description, date_added
                FROM invoice_items 
                WHERE invoice_id IN ({batch_invoice_ids_str})
                ORDER BY invoice_id
            """)
            
            result = db.execute(raw_query)
            items_data = result.fetchall()
            
            if not items_data:
                continue
                
            # ULTRA OPTIMIZATION 3: Direct DataFrame creation from raw SQL results
            import pandas as pd
            columns = ['id', 'invoice_id', 'sheet_name', 'class_', 'ref_no', 'mpi_item', 'customer_job',
                      'amount', 'date', 'vendor', 'memo', 'qty', 'cost', 'description', 'filename', 'po_number', 'bill', 'buyer', 'mpi_description', 'date_added']
            
            all_items_df = pd.DataFrame(items_data, columns=columns)
            
            # ULTRA OPTIMIZATION 4: Vectorized classification lookup
            unique_sheet_names = all_items_df[
                (all_items_df['sheet_name'].notna()) & 
                (all_items_df['sheet_name'] != '(TAX)')
            ]['sheet_name'].unique()
            
            # Bulk load classifications
            classification_cache = {}
            if len(unique_sheet_names) > 0:
                for sheet_name in unique_sheet_names:
                    classification_cache[sheet_name] = ItemClassificationController(db).get_classification(sheet_name)
            
            # ULTRA OPTIMIZATION 5: Vectorized processing by invoice
            invoice_groups = all_items_df.groupby('invoice_id')
            
            for invoice_id, invoice_items_df in invoice_groups:
                # Calculate tax efficiently
                tax_items = invoice_items_df[invoice_items_df['sheet_name'] == '(TAX)']
                tax = tax_items['amount'].str.replace(',', '').astype(float).sum() if not tax_items.empty else 0
                
                # Filter out TAX items
                line_items_df = invoice_items_df[invoice_items_df['sheet_name'] != '(TAX)'].copy()
                
                if line_items_df.empty:
                    continue
                
                # ULTRA OPTIMIZATION 6: Vectorized account assignment
                line_items_df['account'] = ''
                
                # Class A/L logic - vectorized
                class_a_refs = line_items_df[line_items_df['class_'] == 'A']['ref_no'].unique()
                class_l_refs = line_items_df[line_items_df['class_'] == 'L']['ref_no'].unique()
                
                if len(class_a_refs) > 0:
                    mask = line_items_df['ref_no'].isin(class_a_refs)
                    line_items_df.loc[mask, 'account'] = 'UnInvoiced JIP:Material:Additional Material'
                
                if len(class_l_refs) > 0:
                    mask = line_items_df['ref_no'].isin(class_l_refs) & (line_items_df['account'] == '')
                    line_items_df.loc[mask, 'account'] = 'UnInvoiced JIP:Subcontractors Expense:Labor'
                
                # Apply classifications - vectorized
                unassigned_mask = line_items_df['account'] == ''
                if unassigned_mask.any():
                    line_items_df.loc[unassigned_mask, 'account'] = line_items_df.loc[unassigned_mask, 'sheet_name'].map(
                        lambda x: classification_cache.get(x, '') if x else ''
                    )
                
                # UIDI mappings - vectorized
                uidi_mask = line_items_df['account'] == ''
                uidi_mappings = {
                    'UIDI-Job Materials Purchased': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
                    'UIDI-Job Equipment': 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased',
                    'UIDI-Sprinkler specialty item': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
                    'UIDI-Drainage Material': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
                }
                
                for uidi_item, account in uidi_mappings.items():
                    mask = (line_items_df['mpi_item'] == uidi_item) & uidi_mask
                    line_items_df.loc[mask, 'account'] = account
                
                # Check for unmatched items
                line_items_df['account'] = line_items_df['account'].replace([None, 'None'], '')
                unmatched_items = line_items_df[line_items_df['account'] == '']
                
                if not unmatched_items.empty:
                    unmatched_refs = unmatched_items[['mpi_item', 'ref_no']].drop_duplicates().to_dict('records')
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unmatched items in invoice {invoice_id}: {unmatched_refs}"
                    )
                
                # ULTRA OPTIMIZATION 7: Efficient data type conversion
                line_items_df['amount'] = pd.to_numeric(line_items_df['amount'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
                line_items_df['qty'] = pd.to_numeric(line_items_df['qty'], errors='coerce').fillna(0)
                line_items_df['cost'] = pd.to_numeric(line_items_df['cost'], errors='coerce').fillna(0)
                
                # ULTRA OPTIMIZATION 8: Efficient grouping and aggregation
                batch_entry = line_items_df.groupby(['account', 'ref_no', 'customer_job'], as_index=False).agg({
                    'amount': 'sum',
                    'date': 'first',
                    'vendor': 'first',
                    'memo': 'first',
                    'class_': 'first'
                })
                
                # Format data efficiently
                batch_entry['date'] = pd.to_datetime(batch_entry['date'], errors='coerce').dt.strftime('%m/%d/%Y')
                batch_entry['amount'] = batch_entry['amount'] + tax
                batch_entry['terms'] = ''
                batch_entry['bill due'] = ''
                
                # Rename columns
                batch_entry = batch_entry.rename(columns={
                    'date': 'Date', 
                    'ref_no': 'Ref', 
                    'amount': 'Amount', 
                    'customer_job': 'Customer Job', 
                    'class_': 'Class', 
                    'memo': 'Memo'
                })
                
                # Select final columns
                final_columns = ['Date', 'Ref', 'vendor', 'terms', 'bill due', 'account', 'Amount', 'Memo', 'Customer Job', 'Class']
                batch_entry = batch_entry[final_columns]
                
                all_batch_entries.append(batch_entry)
                
                # BUG FIX: Collect IDs for status update - INCLUDE ALL items (including TAX)
                # This ensures that when invoice ref 158086 is sent to QuickBooks, 
                # ALL items (including TAX items) get their status updated to 'Sent'
                all_item_ids = invoice_items_df['id'].tolist()  # Include both regular and TAX items
                all_invoice_item_ids_to_update.extend(all_item_ids)
            
            batch_time_taken = time.time() - batch_time
            print(f"✅ Batch {batch_start//BATCH_SIZE + 1} completed in {batch_time_taken:.2f}s")
        
        # ULTRA OPTIMIZATION 9: Memory-efficient concatenation
        if not all_batch_entries:
            raise HTTPException(status_code=400, detail="No invoice items found for processing.")
        
        print(f"🔗 Combining {len(all_batch_entries)} batch entries...")
        final_batch_entry = pd.concat(all_batch_entries, ignore_index=True, copy=False)
        
        # ULTRA OPTIMIZATION 10: Bulk status updates
        print(f"💾 Updating status for {len(all_invoice_item_ids_to_update)} items...")
        if all_invoice_item_ids_to_update:
            # Process status updates in chunks for very large datasets
            STATUS_UPDATE_BATCH_SIZE = 5000
            for i in range(0, len(all_invoice_item_ids_to_update), STATUS_UPDATE_BATCH_SIZE):
                batch_ids = all_invoice_item_ids_to_update[i:i+STATUS_UPDATE_BATCH_SIZE]
                InvoiceItemController(db).set_export_status_to_sent(batch_ids)
            
            # Update invoice statuses efficiently
            invoice_controller = InvoiceController(db)
            invoice_item_controller = InvoiceItemController(db)
            
            # Check and update invoice statuses in chunks
            INVOICE_CHECK_BATCH_SIZE = 100
            unique_invoice_ids = list(set(invoice_ids))
            
            for i in range(0, len(unique_invoice_ids), INVOICE_CHECK_BATCH_SIZE):
                batch_invoice_ids = unique_invoice_ids[i:i+INVOICE_CHECK_BATCH_SIZE]
                for invoice_id in batch_invoice_ids:
                    if invoice_item_controller.is_exported(str(invoice_id)):
                        invoice_controller.set_invoice_is_exported(str(invoice_id))
        
        # Generate Excel file
        print(f"📊 Generating Excel file for {len(final_batch_entry)} rows...")
        exported_file_path = export_batch_entry_to_excel(final_batch_entry)
        file_name = os.path.basename(exported_file_path)
        
        # Upload to S3
        print(f"☁️ Uploading {file_name} to S3...")
        upload_file(
            exported_file_path, 
            file_key=f'Exports/{file_name}', 
            is_invoice=False
        )
        download_url = get_presigned_url(
            file_key=f'Exports/{file_name}', 
            is_invoice=False
        )
        
        total_time = time.time() - start_time
        print(f"🎉 PRIORITY QuickBooks migration completed in {total_time:.2f}s for {total_invoices} invoices!")
        
        return download_url
    
    finally:
        # 🔓 Always resume background jobs, even if export fails
        resume_background_jobs()
 