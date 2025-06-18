from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Dict, Any
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
from mpi_backend.utils.pdf_to_excel.formatting_util import export_batch_entry_to_excel
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
import os

# Configure logging for performance monitoring
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quickbooks", tags=["QuickBooks"])


@router.post("/migrate-all")
def migrate_all_invoice_to_QB(
    request: SendtoQBFilterRequest, 
    db: Session = Depends(get_db)
):
    start_time = time.time()
    
    # Optimized filtering - get invoice IDs efficiently
    filtered_data = InvoiceItemController(db).apply_filters(
        request, page=1, size=0
    )
    invoice_ids = [item.invoice_id for item in filtered_data['items']]

    if request.excluded_invoice_ids:  # un selected items from frontend
        # Use set for O(1) lookup instead of list iteration
        excluded_set = set(request.excluded_invoice_ids)
        invoice_ids = [
            invoice_id for invoice_id in invoice_ids 
            if invoice_id not in excluded_set
        ]

    # Use set for deduplication (faster than list conversion)
    invoice_ids = list(set(invoice_ids))
    
    filter_time = time.time() - start_time
    logger.info(f"⚡ Filter processing completed in {filter_time:.3f}s for {len(invoice_ids)} invoices")

    return migrate_invoice_to_QB(invoice_ids, db=db)


@router.post("/migrate")
def migrate_invoice_to_QB(
        invoice_ids: List[UUID], db: Session = Depends(get_db)):
    
    start_time = time.time()
    logger.info(f"🚀 Starting ULTRA-OPTIMIZED QuickBooks migration for {len(invoice_ids)} invoices")
    
    if not invoice_ids:
        raise HTTPException(status_code=400, detail="No invoice IDs provided")
    
    # ULTRA-OPTIMIZATION 1: Single bulk fetch with minimal database load
    batch_start = time.time()
    all_invoice_items = InvoiceItemController(db).get_invoice_items_by_invoice_ids(invoice_ids)
    fetch_time = time.time() - batch_start
    logger.info(f"⚡ Fetched {len(all_invoice_items)} items in {fetch_time:.3f}s")
    
    if not all_invoice_items:
        raise HTTPException(status_code=400, detail="No invoice items found for provided invoice IDs")
    
    # ULTRA-OPTIMIZATION 2: Single-pass data extraction and classification
    extract_start = time.time()
    
    # Pre-allocate lists for maximum performance
    all_items_data = []
    tax_by_invoice = {}
    all_item_ids_for_status = []
    
    # Get classification controller once
    classification_controller = ItemClassificationController(db)
    
    # Pre-build classification cache for ALL unique sheet names in single pass
    unique_sheet_names = set()
    for item in all_invoice_items:
        sheet_name = getattr(item, 'sheet_name', '')
        if sheet_name and sheet_name.strip():
            unique_sheet_names.add(sheet_name)
    
    # Build classification cache (try bulk if available, fallback to individual)
    classification_cache = {'': '', None: ''}
    if hasattr(classification_controller, 'get_all_classifications'):
        try:
            # Try to get all classifications at once
            all_classifications = classification_controller.get_all_classifications()
            for sheet_name in unique_sheet_names:
                classification_cache[sheet_name] = all_classifications.get(sheet_name, '')
        except:
            # Fallback to individual lookups
            for sheet_name in unique_sheet_names:
                classification_cache[sheet_name] = classification_controller.get_classification(sheet_name)
    else:
        # Individual lookups (still cached)
        for sheet_name in unique_sheet_names:
            classification_cache[sheet_name] = classification_controller.get_classification(sheet_name)
    
    # Single pass through ALL items for extraction and tax calculation
    for item in all_invoice_items:
        item_sheet_name = getattr(item, 'sheet_name', '')
        item_invoice_id = getattr(item, 'invoice_id')
        
        # Tax calculation
        if item_sheet_name == '(TAX)':
            if item_invoice_id not in tax_by_invoice:
                tax_by_invoice[item_invoice_id] = 0
            amount_str = str(getattr(item, 'amount', '0')).replace(',', '')
            try:
                tax_by_invoice[item_invoice_id] += float(amount_str)
            except (ValueError, TypeError):
                pass
        else:
            # Extract all item data at once
            item_data = {
                'id': getattr(item, 'id', None),
                'invoice_id': item_invoice_id,
                'sheet_name': item_sheet_name,
                'mpi_item': getattr(item, 'mpi_item', 'No Match'),
                'item': getattr(item, 'item', ''),
                'description': getattr(item, 'description', ''),
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
            
            # Collect IDs for status updates
            if item_data['id']:
                all_item_ids_for_status.append(item_data['id'])
    
    extract_time = time.time() - extract_start
    logger.info(f"⚡ Data extraction completed in {extract_time:.3f}s")
    
    if not all_items_data:
        raise HTTPException(status_code=400, detail="No non-tax items found")
    
    # ULTRA-OPTIMIZATION 3: Single DataFrame with vectorized operations
    vectorized_start = time.time()
    
    # Create single large DataFrame (much faster than multiple small ones)
    df = pd.DataFrame(all_items_data)
    
    # Initialize account column
    df['account'] = ''
    
    # VECTORIZED Class A and L logic (preserve business logic exactly)
    class_a_refs = df[df['class_'] == 'A']['ref_no'].unique()
    class_l_refs = df[df['class_'] == 'L']['ref_no'].unique()
    
    # Apply class logic vectorized
    if len(class_a_refs) > 0:
        df.loc[df['ref_no'].isin(class_a_refs), 'account'] = 'UnInvoiced JIP:Material:Additional Material'
    
    if len(class_l_refs) > 0:
        mask = df['ref_no'].isin(class_l_refs) & (df['account'] == '')
        df.loc[mask, 'account'] = 'UnInvoiced JIP:Subcontractors Expense:Labor'
    
    # VECTORIZED classification mapping
    unassigned_mask = df['account'] == ''
    if unassigned_mask.any():
        df.loc[unassigned_mask, 'account'] = df.loc[unassigned_mask, 'sheet_name'].map(
            lambda x: classification_cache.get(x, '') if x else ''
        )
    
    # VECTORIZED MPI mappings
    mpi_mappings = {
        'UIDI-Job Materials Purchased': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
        'UIDI-Job Equipment': 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased',
        'UIDI-Sprinkler specialty item': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
        'UIDI-Drainage Material': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
    }
    
    for mpi_item, account in mpi_mappings.items():
        mask = (df['mpi_item'] == mpi_item) & (df['account'] == '')
        df.loc[mask, 'account'] = account
    
    # Default account for any remaining unmatched
    df.loc[df['account'] == '', 'account'] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
    
    # VECTORIZED data type conversions
    df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
    df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0)
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
    
    # Add tax amounts vectorized
    df['tax_amount'] = df['invoice_id'].map(lambda x: tax_by_invoice.get(x, 0))
    
    vectorized_time = time.time() - vectorized_start
    logger.info(f"⚡ Vectorized processing completed in {vectorized_time:.3f}s")
    
    # ULTRA-OPTIMIZATION 4: Single aggregation operation
    aggregation_start = time.time()
    
    # Single groupby operation
    batch_entry = df.groupby(['account', 'ref_no', 'customer_job']).agg({
        'amount': 'sum',
        'tax_amount': 'first',  # Tax is per invoice
        'date': 'first',
        'vendor': 'first',
        'memo': 'first',
        'class_': 'first'
    }).reset_index()
    
    # Add tax to amount
    batch_entry['amount'] = batch_entry['amount'] + batch_entry['tax_amount']
    
    # Final formatting
    batch_entry['date'] = pd.to_datetime(batch_entry['date'], errors='coerce').dt.strftime('%m/%d/%Y')
    batch_entry['terms'] = ''
    batch_entry['bill due'] = ''
    
    # Column renaming and selection
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
    
    aggregation_time = time.time() - aggregation_start
    logger.info(f"⚡ Aggregation completed in {aggregation_time:.3f}s for {len(final_batch_entry)} rows")
    
    # ULTRA-OPTIMIZATION 5: Fast Excel generation
    excel_start = time.time()
    exported_file_path = export_batch_entry_to_excel(final_batch_entry)
    file_name = os.path.basename(exported_file_path)
    excel_time = time.time() - excel_start
    logger.info(f"⚡ Excel generation completed in {excel_time:.3f}s")
    
    # ULTRA-OPTIMIZATION 6: Batch status updates
    status_start = time.time()
    if all_item_ids_for_status:
        InvoiceItemController(db).set_export_status_to_sent(all_item_ids_for_status)
        
        # Batch invoice status updates
        invoice_controller = InvoiceController(db)
        for invoice_id in invoice_ids:
            if InvoiceItemController(db).is_exported(str(invoice_id)):
                invoice_controller.set_invoice_is_exported(str(invoice_id))
    
    status_time = time.time() - status_start
    logger.info(f"⚡ Status updates completed in {status_time:.3f}s")
    
    # ULTRA-OPTIMIZATION 7: Fast S3 upload
    upload_start = time.time()
    upload_file(
        exported_file_path, 
        file_key=f'Exports/{file_name}', 
        is_invoice=False
    )
    download_url = get_presigned_url(
        file_key=f'Exports/{file_name}', 
        is_invoice=False
    )
    upload_time = time.time() - upload_start
    logger.info(f"⚡ S3 upload completed in {upload_time:.3f}s")
    
    # Performance summary
    total_time = time.time() - start_time
    items_per_second = len(all_item_ids_for_status) / total_time if total_time > 0 else 0
    
    logger.info(f"🎉 ULTRA-OPTIMIZED QuickBooks migration completed!")
    logger.info(f"📊 Performance Summary:")
    logger.info(f"   Total time: {total_time:.3f}s")
    logger.info(f"   Items processed: {len(all_item_ids_for_status)}")
    logger.info(f"   Invoices processed: {len(invoice_ids)}")
    logger.info(f"   Items/second: {items_per_second:.1f}")
    logger.info(f"   Excel rows generated: {len(final_batch_entry)}")
    logger.info(f"   Speed improvement: ULTRA-FAST")
    
    return download_url
 