from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
import pyodbc
import pandas as pd
from mpi_backend.database import get_db
from mpi_backend.database.controllers import InvoiceItemController,InvoiceController, ItemClassificationController
from mpi_backend.database.schemas import SendtoQBFilterRequest
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.pdf_to_excel.formatting_util import export_batch_entry_to_excel
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quickbooks",tags=["QuickBooks"])

@router.post("/migrate-all")
def migrate_all_invoice_to_QB(request: SendtoQBFilterRequest, db: Session = Depends(get_db), background_tasks: BackgroundTasks = None):
    """
    Migrate all invoices to QuickBooks based on filters.
    Uses batch processing to handle large datasets more efficiently.
    """
    # Get filtered invoice IDs
    logger.info("Starting migrate-all process with filters")
    filtered_data = InvoiceItemController(db).apply_filters(request, page=1, size=0)
    invoice_ids = [item.invoice_id for item in filtered_data['items']]

    if request.excluded_invoice_ids:  # un selected items from frontend
        invoice_ids = [
            invoice_id for invoice_id in invoice_ids 
            if invoice_id not in request.excluded_invoice_ids
        ]

    invoice_ids = list(set(invoice_ids))  # make invoice-ids in list to be unique
    
    logger.info(f"Found {len(invoice_ids)} invoices to process")
    
    # If too many invoices, process in background
    if len(invoice_ids) > 20 and background_tasks:
        logger.info(f"Processing {len(invoice_ids)} invoices in background task")
        background_tasks.add_task(migrate_invoice_to_QB, invoice_ids, db)
        return {"status": "processing", "message": f"Processing {len(invoice_ids)} invoices in background. This may take some time."}
    
    # Otherwise process normally
    return migrate_invoice_to_QB(invoice_ids, db=db)


@router.post("/migrate")
def migrate_invoice_to_QB(
        invoice_ids: List[UUID], db: Session = Depends(get_db)):

    all_batch_entries = []
    processed_invoices = []
    skipped_invoices = []
    
    logger.info(f"Starting migration of {len(invoice_ids)} invoices")
    
    # Process invoices in batches to improve performance
    batch_size = 20
    for i in range(0, len(invoice_ids), batch_size):
        batch_invoice_ids = invoice_ids[i:i+batch_size]
        logger.info(f"Processing batch {i//batch_size + 1} with {len(batch_invoice_ids)} invoices")
        
        # Process each invoice in the batch
        for invoice_id in batch_invoice_ids:
            try:
                # Get only raw SQLAlchemy objects for DataFrame (more efficient)
                line_items_raw = InvoiceItemController(db).get_invoice_items_raw(invoice_id)
                
                # Skip if no items found for this invoice
                if not line_items_raw:
                    logger.info(f"Skipping invoice {invoice_id}: No items found")
                    skipped_invoices.append(str(invoice_id))
                    continue
                
                # Extract tax amount more efficiently
                tax = 0
                tax_items = [item for item in line_items_raw if item.sheet_name == '(TAX)']
                if tax_items:
                    for tax_item in tax_items:
                        try:
                            tax += float(tax_item.amount.replace(',', ''))
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid tax amount format: {tax_item.amount}")
                
                # Filter using raw items for DataFrame creation (more memory efficient)
                line_items_for_df = [item for item in line_items_raw if item.sheet_name != '(TAX)']
                
                # Store IDs for status update later
                invoice_item_ids = [item.id for item in line_items_raw if item.id]

                # Skip invoice if no non-TAX items remain
                if not line_items_for_df:
                    logger.info(f"Skipping invoice {invoice_id}: Only TAX items found")
                    skipped_invoices.append(str(invoice_id))
                    continue

                # Create DataFrame more efficiently
                try:
                    # Convert raw SQLAlchemy objects to DataFrame more efficiently
                    line_items_data = []
                    for item in line_items_for_df:
                        # Only extract the fields we need
                        item_dict = {
                            'sheet_name': getattr(item, 'sheet_name', ''),
                            'mpi_item': getattr(item, 'mpi_item', ''),
                            'ref_no': getattr(item, 'ref_no', ''),
                            'customer_job': getattr(item, 'customer_job', ''),
                            'date': getattr(item, 'date', None),
                            'vendor': getattr(item, 'vendor', ''),
                            'memo': getattr(item, 'memo', ''),
                            'class_': getattr(item, 'class_', ''),
                            'qty': getattr(item, 'qty', 0),
                            'cost': getattr(item, 'cost', 0),
                            'amount': getattr(item, 'amount', '0')
                        }
                        line_items_data.append(item_dict)
                    
                    # Create DataFrame with predefined dtypes for better performance
                    line_item_df = pd.DataFrame(line_items_data)
                    
                    # Ensure sheet_name column exists, fill missing values with empty string
                    if 'sheet_name' not in line_item_df.columns:
                        line_item_df['sheet_name'] = ''
                    else:
                        line_item_df['sheet_name'] = line_item_df['sheet_name'].fillna('')
                    
                    logger.info(f"Processing invoice {invoice_id} with {len(line_item_df)} items")
                    
                except Exception as e:
                    logger.error(f"Error processing invoice {invoice_id}: {str(e)}")
                    skipped_invoices.append(str(invoice_id))
                    continue
                
                # Apply classification with error handling - optimize by caching classifications
                classification_cache = {}
                def get_classification_safe(sheet_name):
                    if not sheet_name:
                        return ''
                    if sheet_name not in classification_cache:
                        classification_cache[sheet_name] = ItemClassificationController(db).get_classification(sheet_name)
                    return classification_cache[sheet_name]
                
                # Initialize the account column
                line_item_df['account'] = ''
                
                # Identify invoices (by ref_no) that have ANY class 'A' or 'L' items - optimize with vectorized operations
                if 'class_' in line_item_df.columns:
                    # Handle class A items
                    class_a_refs = set(line_item_df[line_item_df['class_'] == 'A']['ref_no'].unique())
                    if class_a_refs:
                        line_item_df.loc[line_item_df['ref_no'].isin(class_a_refs), 'account'] = 'UnInvoiced JIP:Material:Additional Material'
                    
                    # Handle class L items (only those not already assigned)
                    class_l_refs = set(line_item_df[line_item_df['class_'] == 'L']['ref_no'].unique())
                    if class_l_refs:
                        mask = (line_item_df['ref_no'].isin(class_l_refs)) & (line_item_df['account'] == '')
                        line_item_df.loc[mask, 'account'] = 'UnInvoiced JIP:Subcontractors Expense:Labor'
                
                # For all remaining items (invoices with no class A or L), apply normal logic
                unassigned_mask = line_item_df['account'] == ''
                
                # Apply sheet_name classification to unassigned items - vectorize when possible
                if unassigned_mask.any():
                    # Get unique sheet names to minimize classification calls
                    unique_sheet_names = line_item_df.loc[unassigned_mask, 'sheet_name'].unique()
                    sheet_name_to_account = {name: get_classification_safe(name) for name in unique_sheet_names}
                    
                    # Apply the mapping using vectorized operations
                    line_item_df.loc[unassigned_mask, 'account'] = line_item_df.loc[unassigned_mask, 'sheet_name'].map(sheet_name_to_account)
                
                # Map specific items to accounts (only for items still unassigned after class logic)
                unassigned_mask = line_item_df['account'] == ''
                
                # Use vectorized operations with boolean indexing for UIDI mappings
                if 'mpi_item' in line_item_df.columns:
                    uidi_mappings = {
                        'UIDI-Job Materials Purchased': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
                        'UIDI-Job Equipment': 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased',
                        'UIDI-Sprinkler specialty item': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
                        'UIDI-Drainage Material': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
                    }
                    
                    for uidi_item, account in uidi_mappings.items():
                        mask = (line_item_df['mpi_item'] == uidi_item) & unassigned_mask
                        if mask.any():
                            line_item_df.loc[mask, 'account'] = account
                
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

                # Convert data types efficiently
                for col in ['qty', 'cost']:
                    if col in line_item_df.columns:
                        line_item_df[col] = pd.to_numeric(line_item_df[col], errors='coerce').fillna(0)
                
                if 'amount' in line_item_df.columns:
                    line_item_df['amount'] = pd.to_numeric(line_item_df['amount'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

                # Group by efficiently
                required_columns = ['account', 'ref_no', 'customer_job', 'amount', 'date', 'vendor', 'memo', 'class_']
                for col in required_columns:
                    if col not in line_item_df.columns:
                        line_item_df[col] = ''
                
                batch_entry = line_item_df.groupby(['account', 'ref_no', 'customer_job']).agg({
                    'amount': 'sum',
                    'date': 'first',
                    'vendor': 'first',
                    'memo': 'first',
                    'class_': 'first'
                }).reset_index()

                # Format date efficiently
                if 'date' in batch_entry.columns:
                    batch_entry['date'] = pd.to_datetime(batch_entry['date'], errors='coerce')
                    batch_entry['date'] = batch_entry['date'].dt.strftime('%m/%d/%Y')
                    batch_entry['date'] = batch_entry['date'].fillna('')
                
                # Add tax and format columns
                batch_entry['amount'] = batch_entry['amount'] + tax
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

                # Update export status in batches for better performance
                InvoiceItemController(db).set_export_status_to_sent(invoice_item_ids)

                if InvoiceItemController(db).is_exported(str(invoice_id)):
                    InvoiceController(db).set_invoice_is_exported(str(invoice_id))
                    
                processed_invoices.append(str(invoice_id))
                logger.info(f"Successfully processed invoice {invoice_id}")
                
            except HTTPException as e:
                # For QuickBooks-specific errors, reraise them
                if len(invoice_ids) == 1:  # Single invoice processing - reraise error
                    raise e
                else:  # Batch processing - log error and continue
                    logger.error(f"Error processing invoice {invoice_id}: {e.detail}")
                    skipped_invoices.append(str(invoice_id))
                    continue
            except Exception as e:
                logger.error(f"Unexpected error processing invoice {invoice_id}: {str(e)}")
                skipped_invoices.append(str(invoice_id))
                continue

    # Check if we have any data to export
    if not all_batch_entries:
        error_message = f"No invoice items found for processing."
        if skipped_invoices:
            error_message += f" Skipped invoices: {skipped_invoices}"
        raise HTTPException(status_code=400, detail=error_message)

    # Combine all successfully processed invoices
    logger.info(f"Combining {len(all_batch_entries)} batch entries")
    
    # Use memory-efficient concatenation
    if len(all_batch_entries) > 1:
        final_batch_entry = pd.concat(all_batch_entries, ignore_index=True, copy=False)
    else:
        final_batch_entry = all_batch_entries[0]
    
    # Export to Excel
    exported_file_path = export_batch_entry_to_excel(final_batch_entry)
    file_name = os.path.basename(exported_file_path)
    
    # Upload to S3 and get download URL
    logger.info(f"Uploading exported file to S3: {file_name}")
    upload_file(
        exported_file_path, 
        file_key=f'Exports/{file_name}', 
        is_invoice=False
    )
    download_url = get_presigned_url(
        file_key=f'Exports/{file_name}', 
        is_invoice=False
    )

    response = {
        "download_url": download_url,
        "processed": len(processed_invoices)
    }
    
    if skipped_invoices:
        response["skipped_invoice_ids"] = skipped_invoices
        logger.info(f"Processing complete. Processed: {len(processed_invoices)}, Skipped: {len(skipped_invoices)}")
    
    return response
 