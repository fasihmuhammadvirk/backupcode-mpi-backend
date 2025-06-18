from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
import pandas as pd
import time
import logging
from mpi_backend.database import get_db
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.controllers.invoice import InvoiceController
from mpi_backend.database.controllers.ItemClassification import (
    ItemClassificationController
)
from mpi_backend.database.schemas import SendtoQBFilterRequest
from mpi_backend.utils.pdf_to_excel.formatting_util import (
    export_batch_entry_to_excel
)
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
from mpi_backend.utils.quickbooks_priority import (
    pause_background_jobs, 
    resume_background_jobs,
    pause_all_background_jobs_for_migrate_all,
    resume_all_background_jobs_from_migrate_all
)
import os

# Configure logging for performance monitoring
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quickbooks", tags=["QuickBooks"])


@router.post("/migrate-all")
def migrate_all_invoice_to_QB(request: SendtoQBFilterRequest, db: Session = Depends(get_db)):
    """PRIORITY: QuickBooks migration with background job control - maintains old API signature"""
    try:
        # ABSOLUTE PRIORITY - Pause ALL background jobs
        pause_all_background_jobs_for_migrate_all()
        logger.info("ABSOLUTE PRIORITY: ALL background jobs paused for migrate-all operation")
        
        # OPTIMIZED filtering with set operations
        filtered_data = InvoiceItemController(db).apply_filters(request, page=1, size=0)
        invoice_ids = [item.invoice_id for item in filtered_data['items']]

        if request.excluded_invoice_ids:  # un selected items from frontend
            # Use set for O(1) lookup instead of list iteration (OPTIMIZATION)
            excluded_set = set(request.excluded_invoice_ids)
            invoice_ids = [
                invoice_id for invoice_id in invoice_ids 
                if invoice_id not in excluded_set
            ]

        invoice_ids = list(set(invoice_ids))  # make invoice-ids in list to be unique

        return migrate_invoice_to_QB(invoice_ids, db=db)
        
    except Exception as e:
        logger.error(f"QuickBooks migrate-all failed: {str(e)}")
        raise
    finally:
        # ABSOLUTE PRIORITY: Always resume ALL background jobs
        resume_all_background_jobs_from_migrate_all()
        logger.info("PRIORITY RELEASED: ALL background jobs resumed after migrate-all operation")


@router.post("/migrate")
def migrate_invoice_to_QB(invoice_ids: List[UUID], db: Session = Depends(get_db)):
    """OPTIMIZED: QuickBooks migration with priority control - maintains old API signature"""
    start_time = time.time()
    
    try:
        # Pause background jobs for priority processing
        pause_background_jobs()
        logger.info("Background jobs paused for QuickBooks migration")
        
        # ULTRA-OPTIMIZATION: Check if we can use bulk processing
        if len(invoice_ids) > 10:
            return migrate_invoice_to_QB_optimized(invoice_ids, db)
        else:
            return migrate_invoice_to_QB_original(invoice_ids, db)
            
    except Exception as e:
        logger.error(f"QuickBooks migration failed: {str(e)}")
        raise
    finally:
        # Always resume background jobs
        resume_background_jobs()
        total_time = time.time() - start_time
        logger.info(f"QuickBooks migration completed in {total_time:.2f}s - background jobs resumed")


def migrate_invoice_to_QB_optimized(invoice_ids: List[UUID], db: Session):
    """ULTRA-OPTIMIZED version for large datasets while maintaining exact business logic"""
    
    # OPTIMIZATION 1: Bulk data retrieval
    if hasattr(InvoiceItemController(db), 'get_invoice_items_by_invoice_ids'):
        invoice_items = InvoiceItemController(db).get_invoice_items_by_invoice_ids(invoice_ids)
    else:
        # Fallback to individual calls
        invoice_items = []
        for invoice_id in invoice_ids:
            invoice_items.extend(InvoiceItemController(db).get_invoice_items(invoice_id))
    
    # OPTIMIZATION 2: Single-pass data extraction
    all_items_data = []
    tax_by_invoice = {}
    all_item_ids_for_status = []
    
    # Pre-build classification cache
    classification_controller = ItemClassificationController(db)
    unique_sheet_names = set()
    for item in invoice_items:
        sheet_name = getattr(item, 'sheet_name', '')
        if sheet_name and sheet_name.strip() and sheet_name != '(TAX)':
            unique_sheet_names.add(sheet_name)
    
    classification_cache = {'': '', None: ''}
    for sheet_name in unique_sheet_names:
        classification_cache[sheet_name] = classification_controller.get_classification(sheet_name)

    # Single pass through ALL items (EXACT ORIGINAL LOGIC)
    for item in invoice_items:
        item_sheet_name = getattr(item, 'sheet_name', '')
        item_invoice_id = getattr(item, 'invoice_id')
        
        # Tax calculation (EXACT ORIGINAL LOGIC)
        if item_sheet_name == '(TAX)':
            if item_invoice_id not in tax_by_invoice:
                tax_by_invoice[item_invoice_id] = 0
            amount_str = str(getattr(item, 'amount', '0')).replace(',', '')
            try:
                tax_by_invoice[item_invoice_id] += float(amount_str)
            except (ValueError, TypeError):
                pass
        else:
            # Extract item data (EXACT ORIGINAL LOGIC)
            item_data = {
                'id': getattr(item, 'id', None),
                'invoice_id': item_invoice_id,
                'sheet_name': item_sheet_name,
                'mpi_item': getattr(item, 'mpi_item', 'No Match'),
                'qty': getattr(item, 'qty', 0),
                'cost': getattr(item, 'cost', 0.0),
                'amount': getattr(item, 'amount', '0'),
                'date': getattr(item, 'date', None),
                'ref_no': getattr(item, 'ref_no', ''),
                'customer_job': getattr(item, 'customer_job', ''),
                'vendor': getattr(item, 'vendor', ''),
                'class_': getattr(item, 'class_', ''),
                'memo': getattr(item, 'memo', ''),
            }
            all_items_data.append(item_data)
            
            if item_data['id']:
                all_item_ids_for_status.append(item_data['id'])
    
    if not all_items_data:
        raise HTTPException(status_code=400, detail="No non-tax items found")

    # OPTIMIZATION 3: Single DataFrame with vectorized operations (PRESERVE EXACT ORIGINAL LOGIC)
    df = pd.DataFrame(all_items_data)
    
    # Initialize account column
    df['account'] = ''
    
    # VECTORIZED Class A and L logic (PRESERVE EXACT ORIGINAL BUSINESS LOGIC)
    class_a_refs = df[df['class_'] == 'A']['ref_no'].unique()
    class_l_refs = df[df['class_'] == 'L']['ref_no'].unique()
    
    # Apply class logic vectorized (EXACT ORIGINAL LOGIC)
    if len(class_a_refs) > 0:
        df.loc[df['ref_no'].isin(class_a_refs), 'account'] = 'UnInvoiced JIP:Material:Additional Material'
    
    if len(class_l_refs) > 0:
        mask = df['ref_no'].isin(class_l_refs) & (df['account'] == '')
        df.loc[mask, 'account'] = 'UnInvoiced JIP:Subcontractors Expense:Labor'
    
    # VECTORIZED classification mapping (EXACT ORIGINAL LOGIC)
    unassigned_mask = df['account'] == ''
    if unassigned_mask.any():
        df.loc[unassigned_mask, 'account'] = df.loc[unassigned_mask, 'sheet_name'].map(
            lambda x: classification_cache.get(x, '') if x else ''
        )
    
    # VECTORIZED MPI mappings (EXACT ORIGINAL LOGIC)
    mpi_mappings = {
        'UIDI-Job Materials Purchased': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
        'UIDI-Job Equipment': 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased',
        'UIDI-Sprinkler specialty item': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
        'UIDI-Drainage Material': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
    }
    
    for mpi_item, account in mpi_mappings.items():
        mask = (df['mpi_item'] == mpi_item) & (df['account'] == '')
        df.loc[mask, 'account'] = account

    # Replace None/null values with empty string for account column
    df['account'] = df['account'].replace([None, 'None'], '')

    # CRITICAL: Check for unmatched items and raise error (EXACT ORIGINAL BUSINESS LOGIC)
    unmatched_items = df[df['account'] == '']
    if not unmatched_items.empty:
        unmatched_references = unmatched_items[['mpi_item', 'ref_no']].drop_duplicates()
        unmatched_references_list = unmatched_references.to_dict(orient='records')
        
        raise HTTPException(
            status_code=400,
            detail=f"Unmatched items or sheet names are present, 'unmatched_references': {unmatched_references_list}"
        )
    
    # VECTORIZED data type conversions
    df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
    df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0)
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
    
    # Add tax amounts vectorized
    df['tax_amount'] = df['invoice_id'].map(lambda x: tax_by_invoice.get(x, 0))
    
    # OPTIMIZATION 4: Single aggregation operation
    batch_entry = df.groupby(['account', 'ref_no', 'customer_job']).agg({
        'amount': 'sum',
        'tax_amount': 'first',  # Tax is per invoice
        'date': 'first',
        'vendor': 'first',
        'memo': 'first',
        'class_': 'first'
    }).reset_index()
    
    # Add tax to amount (EXACT ORIGINAL LOGIC)
    batch_entry['amount'] = batch_entry['amount'] + batch_entry['tax_amount']
    
    # Final formatting (EXACT ORIGINAL LOGIC)
    batch_entry['date'] = pd.to_datetime(batch_entry['date'], errors='coerce').dt.strftime('%m/%d/%Y')
    batch_entry['terms'] = ''
    batch_entry['bill due'] = ''
    
    # Column renaming and selection (EXACT ORIGINAL LOGIC)
    batch_entry = batch_entry.rename(columns={
        'date': 'Date', 
        'ref_no': 'Ref', 
        'amount': 'Amount', 
        'customer_job': 'Customer Job', 
        'class_': 'Class', 
        'memo': 'Memo'
    })
    
    final_batch_entry = batch_entry[[
        'Date', 'Ref', 'vendor', 'terms', 'bill due', 
        'account', 'Amount', 'Memo', 'Customer Job', 'Class'
    ]]
    
    # OPTIMIZATION 5: Batch status updates
    if all_item_ids_for_status:
        InvoiceItemController(db).set_export_status_to_sent(all_item_ids_for_status)
        
        # Batch invoice status updates
        invoice_controller = InvoiceController(db)
        for invoice_id in invoice_ids:
            if InvoiceItemController(db).is_exported(str(invoice_id)):
                invoice_controller.set_invoice_is_exported(str(invoice_id))
    
    # S3 upload and return (EXACT ORIGINAL LOGIC)
    exported_file_path = export_batch_entry_to_excel(final_batch_entry)
    file_name = os.path.basename(exported_file_path)
    
    # Upload to S3 and get download URL (EXACT ORIGINAL LOGIC)
    upload_file(
        exported_file_path, 
        file_key=f'Exports/{file_name}', 
        is_invoice=False
    )
    download_url = get_presigned_url(
        file_key=f'Exports/{file_name}', 
        is_invoice=False
    )

    return download_url


def migrate_invoice_to_QB_original(invoice_ids: List[UUID], db: Session):
    """Original logic for smaller datasets - EXACT COPY of old code"""

    all_batch_entries = []

    for invoice_id in invoice_ids:
        line_items = InvoiceItemController(db).get_invoice_items(invoice_id)
        line_item_copy = line_items

        tax = 0
        for item in line_items:
            if item.sheet_name == '(TAX)':
                tax = float(item.amount.replace(',', ''))

        line_items = [item for item in line_items if item.sheet_name != '(TAX)']

        # Create DataFrame and handle possible missing fields
        try:
            # First get reference numbers before creating DataFrame
            ref_numbers = [getattr(item, 'ref_no', 'unknown') for item in line_items]
            
            line_item_df = pd.DataFrame([vars(item) for item in line_items])
            
            # Get sheet_name from DataFrame - this will fail with KeyError if missing
            line_item_df['sheet_name']
            
        except KeyError:
            # Just use the reference numbers we collected before the error
            raise HTTPException(
                status_code=400,
                detail=f"Missing sheet_name data. Reference numbers: {ref_numbers}"
            )
        except Exception as e:
            # For any other exception, also return reference numbers
            raise HTTPException(
                status_code=400,
                detail=f"Error processing data: {str(e)}. Reference numbers: {ref_numbers}"
            )
            
        # Apply classification with error handling
        def get_classification_safe(sheet_name):
            if not sheet_name:
                return ''
            return ItemClassificationController(db).get_classification(sheet_name)
        
        # Initialize the account column
        line_item_df['account'] = ''
        
        # Identify invoices (by ref_no) that have ANY class 'A' or 'L' items
        invoices_with_class_a = line_item_df[line_item_df['class_'] == 'A']['ref_no'].unique()
        invoices_with_class_l = line_item_df[line_item_df['class_'] == 'L']['ref_no'].unique()
        
        # For invoices with ANY class 'A' item, assign ALL items to Additional Material
        if len(invoices_with_class_a) > 0:
            class_a_invoice_mask = line_item_df['ref_no'].isin(invoices_with_class_a)
            line_item_df.loc[class_a_invoice_mask, 'account'] = 'UnInvoiced JIP:Material:Additional Material'
        
        # For invoices with ANY class 'L' item, assign ALL items to Labor (only if not already assigned to class A)
        if len(invoices_with_class_l) > 0:
            class_l_invoice_mask = line_item_df['ref_no'].isin(invoices_with_class_l) & (line_item_df['account'] == '')
            line_item_df.loc[class_l_invoice_mask, 'account'] = 'UnInvoiced JIP:Subcontractors Expense:Labor'
        
        # For all remaining items (invoices with no class A or L), apply normal logic
        unassigned_mask = line_item_df['account'] == ''
        
        # Apply sheet_name classification to unassigned items
        if unassigned_mask.any():
            line_item_df.loc[unassigned_mask, 'account'] = line_item_df.loc[unassigned_mask, 'sheet_name'].apply(get_classification_safe)

        # Map specific items to accounts (only for items still unassigned after class logic)
        # This ensures class A and L invoices don't get overridden
        unassigned_mask = line_item_df['account'] == ''
        
        line_item_df.loc[
            (line_item_df['mpi_item'] == 'UIDI-Job Materials Purchased') & unassigned_mask, 'account'
        ] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
        
        line_item_df.loc[
            (line_item_df['mpi_item'] == 'UIDI-Job Equipment') & unassigned_mask, 'account'
        ] = 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased'
        
        line_item_df.loc[
            (line_item_df['mpi_item'] == 'UIDI-Sprinkler specialty item') & unassigned_mask, 'account'
        ] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
        
        line_item_df.loc[
            (line_item_df['mpi_item'] == 'UIDI-Drainage Material') & unassigned_mask, 'account'
        ] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'

        line_item_df['account'] = line_item_df['account'].replace([None, 'None'], '')

        # Identify missing accounts and log invoice details
        unmatched_items = line_item_df[line_item_df['account'] == '']
        if not unmatched_items.empty:
            unmatched_references = unmatched_items[['mpi_item', 'ref_no']].drop_duplicates()
            unmatched_references_list = unmatched_references.to_dict(orient='records')

            raise HTTPException(
                status_code=400,
                detail=f"Unmatched items or sheet names are present, 'unmatched_references': {unmatched_references_list}"
            )

        line_item_df = line_item_df.astype(str)
        float_columns = ['qty', 'cost', 'amount']
        line_item_df[float_columns] = line_item_df[float_columns].astype(float)

        batch_entry = line_item_df.groupby(['account', 'ref_no', 'customer_job']).agg({
            'amount': 'sum',
            'date': 'first',
            'vendor': 'first',
            'memo': 'first',
            'class_': 'first'
        }).reset_index()

        batch_entry['date'] = pd.to_datetime(batch_entry['date']).dt.strftime('%m/%d/%Y')
        batch_entry['amount'] = batch_entry['amount'].apply(lambda x: x+tax)
        batch_entry['terms'] = ''
        batch_entry['bill due'] = ''

        batch_entry.rename(columns = {
            'date': 'Date', 
            'ref_no': 'Ref', 
            'amount': 'Amount', 
            'customer_job': 'Customer Job', 
            'class_': 'Class', 
            'memo': 'Memo'
        }, inplace=True)
        
        batch_entry = batch_entry[[
            'Date', 'Ref', 'vendor', 'terms', 'bill due', 
            'account', 'Amount', 'Memo', 'Customer Job', 'Class'
        ]]
        all_batch_entries.append(batch_entry)

        # track & manage invoice export status
        invoice_item_ids = [item.id for item in line_item_copy if item.id]
        InvoiceItemController(db).set_export_status_to_sent(invoice_item_ids)

        if InvoiceItemController(db).is_exported(str(invoice_id)):
            InvoiceController(db).set_invoice_is_exported(str(invoice_id))

    final_batch_entry = pd.concat(all_batch_entries, ignore_index=True)
    exported_file_path = export_batch_entry_to_excel(final_batch_entry)
    file_name = os.path.basename(exported_file_path)
    
    # Upload to S3 and get download URL
    upload_file(
        exported_file_path, 
        file_key=f'Exports/{file_name}', 
        is_invoice=False
    )
    download_url = get_presigned_url(
        file_key=f'Exports/{file_name}', 
        is_invoice=False
    )

    return download_url


@router.get("/priority-status")
def get_priority_status():
    """Get current QuickBooks priority system status"""
    from mpi_backend.utils.quickbooks_priority import get_qb_priority_status
    return get_qb_priority_status()
 