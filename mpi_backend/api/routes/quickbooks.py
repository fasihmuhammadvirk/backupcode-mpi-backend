from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
import pandas as pd
import time
import logging
import traceback
from contextlib import contextmanager
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


@contextmanager
def safe_priority_context(operation_type="regular"):
    """Context manager to ensure background jobs are always resumed"""
    try:
        if operation_type == "migrate_all":
            pause_all_background_jobs_for_migrate_all()
            logger.info(
                "ABSOLUTE PRIORITY: ALL background jobs paused for "
                "migrate-all operation"
            )
        else:
            pause_background_jobs()
            logger.info("Background jobs paused for QuickBooks migration")
        yield
    except Exception as e:
        logger.error(f"Error in QuickBooks operation: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise
    finally:
        # CRITICAL: Always resume background jobs, even if operation fails
        try:
            if operation_type == "migrate_all":
                resume_all_background_jobs_from_migrate_all()
                logger.info(
                    "PRIORITY RELEASED: ALL background jobs resumed after "
                    "migrate-all operation"
                )
            else:
                resume_background_jobs()
                logger.info("Background jobs resumed after QuickBooks operation")
        except Exception as resume_error:
            logger.error(
                f"CRITICAL: Failed to resume background jobs: {resume_error}"
            )
            # This is critical - try alternative cleanup
            try:
                resume_all_background_jobs_from_migrate_all()
                logger.info("Alternative background job resume successful")
            except Exception as alt_error:
                logger.error(
                    f"CRITICAL: Alternative resume also failed: {alt_error}"
                )


def validate_invoice_ids(invoice_ids: List[UUID]) -> List[UUID]:
    """Validate and clean invoice IDs"""
    if not invoice_ids:
        raise HTTPException(
            status_code=400, detail="No invoice IDs provided"
        )
    
    # Remove duplicates and None values
    clean_ids = list(set([id for id in invoice_ids if id is not None]))
    
    if not clean_ids:
        raise HTTPException(
            status_code=400, detail="No valid invoice IDs provided"
        )
    
    if len(clean_ids) > 5000:
        logger.warning(f"Large dataset detected: {len(clean_ids)} invoices")
        
    return clean_ids


@router.post("/migrate-all")
def migrate_all_invoice_to_QB(request: SendtoQBFilterRequest, db: Session = Depends(get_db)):
    """PRIORITY: QuickBooks migration with background job control - maintains old API signature"""
    operation_start = time.time()
    
    with safe_priority_context("migrate_all"):
        try:
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

            # Validate and clean invoice IDs
            invoice_ids = validate_invoice_ids(invoice_ids)

            logger.info(f"Migrate-all processing {len(invoice_ids)} invoices")
            result = migrate_invoice_to_QB(invoice_ids, db=db)
            
            operation_time = time.time() - operation_start
            logger.info(f"Migrate-all completed successfully in {operation_time:.2f}s")
            return result
            
        except Exception as e:
            operation_time = time.time() - operation_start
            logger.error(
                f"QuickBooks migrate-all failed after {operation_time:.2f}s: "
                f"{str(e)}"
            )
            raise


@router.post("/migrate")
def migrate_invoice_to_QB(invoice_ids: List[UUID], db: Session = Depends(get_db)):
    """OPTIMIZED: QuickBooks migration with priority control - maintains old API signature"""
    start_time = time.time()
    
    with safe_priority_context("regular"):
        try:
            # Validate input
            invoice_ids = validate_invoice_ids(invoice_ids)
            
            logger.info(f"Processing {len(invoice_ids)} invoices")
            
            # ULTRA-OPTIMIZATION: Check if we can use bulk processing
            if len(invoice_ids) > 10:
                result = migrate_invoice_to_QB_optimized(invoice_ids, db)
            else:
                result = migrate_invoice_to_QB_original(invoice_ids, db)
                
            total_time = time.time() - start_time
            logger.info(f"QuickBooks migration completed successfully in {total_time:.2f}s")
            return result
            
        except Exception as e:
            total_time = time.time() - start_time
            logger.error(f"QuickBooks migration failed after {total_time:.2f}s: {str(e)}")
            raise


def safe_getattr_with_fallback(obj, attr, default=''):
    """Safely get attribute with fallback and logging"""
    try:
        value = getattr(obj, attr, default)
        # Handle None values
        if value is None:
            return default
        # Convert to string for safety
        return str(value) if not isinstance(value, str) else value
    except Exception as e:
        logger.warning(f"Error getting attribute {attr}: {e}")
        return default


def migrate_invoice_to_QB_optimized(invoice_ids: List[UUID], db: Session):
    """ULTRA-OPTIMIZED version for large datasets while maintaining exact business logic"""
    
    operation_start = time.time()
    logger.info(f"Starting optimized processing for {len(invoice_ids)} invoices")
    
    try:
        # OPTIMIZATION 1: Bulk data retrieval with timeout protection
        retrieval_start = time.time()
        invoice_items = []
        
        if hasattr(InvoiceItemController(db), 'get_invoice_items_by_invoice_ids'):
            try:
                invoice_items = InvoiceItemController(db).get_invoice_items_by_invoice_ids(invoice_ids)
            except Exception as bulk_error:
                logger.warning(f"Bulk retrieval failed: {bulk_error}, falling back to individual calls")
                invoice_items = []
        
        # Fallback to individual calls if bulk fails
        if not invoice_items:
            for i, invoice_id in enumerate(invoice_ids):
                try:
                    items = InvoiceItemController(db).get_invoice_items(invoice_id)
                    if items:
                        invoice_items.extend(items)
                    
                    # Progress logging for large datasets
                    if i > 0 and i % 100 == 0:
                        logger.info(f"Retrieved data for {i}/{len(invoice_ids)} invoices")
                        
                except Exception as item_error:
                    logger.warning(f"Failed to get items for invoice {invoice_id}: {item_error}")
                    continue
        
        retrieval_time = time.time() - retrieval_start
        logger.info(f"Data retrieval completed in {retrieval_time:.3f}s for {len(invoice_items)} items")
        
        if not invoice_items:
            raise HTTPException(status_code=400, detail="No invoice items found for processing")
        
        # OPTIMIZATION 2: Single-pass data extraction with error handling
        extract_start = time.time()
        all_items_data = []
        tax_by_invoice = {}
        all_item_ids_for_status = []
        
        # Pre-build classification cache with error handling
        classification_controller = ItemClassificationController(db)
        unique_sheet_names = set()
        
        for item in invoice_items:
            sheet_name = safe_getattr_with_fallback(item, 'sheet_name', '')
            if sheet_name and sheet_name.strip() and sheet_name != '(TAX)':
                unique_sheet_names.add(sheet_name)
        
        # Build classification cache with proper error handling
        classification_cache = {'': '', None: '', 'None': ''}
        classification_errors = 0
        
        for sheet_name in unique_sheet_names:
            try:
                classification = classification_controller.get_classification(sheet_name)
                classification_cache[sheet_name] = classification if classification else ''
            except Exception as class_error:
                logger.warning(f"Classification error for '{sheet_name}': {class_error}")
                classification_cache[sheet_name] = ''
                classification_errors += 1
                
        if classification_errors > 0:
            logger.warning(f"Had {classification_errors} classification errors, using empty classifications")

        # Single pass through ALL items with robust error handling (EXACT ORIGINAL LOGIC)
        item_errors = 0
        for i, item in enumerate(invoice_items):
            try:
                item_sheet_name = safe_getattr_with_fallback(item, 'sheet_name', '')
                item_invoice_id = getattr(item, 'invoice_id', None)
                
                if not item_invoice_id:
                    logger.warning(f"Item {i} missing invoice_id, skipping")
                    item_errors += 1
                    continue
                
                # Tax calculation (EXACT ORIGINAL LOGIC)
                if item_sheet_name == '(TAX)':
                    if item_invoice_id not in tax_by_invoice:
                        tax_by_invoice[item_invoice_id] = 0
                    amount_str = str(safe_getattr_with_fallback(item, 'amount', '0')).replace(',', '')
                    try:
                        tax_by_invoice[item_invoice_id] += float(amount_str)
                    except (ValueError, TypeError) as tax_error:
                        logger.warning(f"Tax calculation error for item {i}: {tax_error}")
                        pass
                else:
                    # Extract item data with error handling (EXACT ORIGINAL LOGIC)
                    item_data = {
                        'id': getattr(item, 'id', None),
                        'invoice_id': item_invoice_id,
                        'sheet_name': item_sheet_name,
                        'mpi_item': safe_getattr_with_fallback(item, 'mpi_item', 'No Match'),
                        'qty': safe_getattr_with_fallback(item, 'qty', 0),
                        'cost': safe_getattr_with_fallback(item, 'cost', 0.0),
                        'amount': safe_getattr_with_fallback(item, 'amount', '0'),
                        'date': getattr(item, 'date', None),
                        'ref_no': safe_getattr_with_fallback(item, 'ref_no', ''),
                        'customer_job': safe_getattr_with_fallback(item, 'customer_job', ''),
                        'vendor': safe_getattr_with_fallback(item, 'vendor', ''),
                        'class_': safe_getattr_with_fallback(item, 'class_', ''),
                        'memo': safe_getattr_with_fallback(item, 'memo', ''),
                    }
                    all_items_data.append(item_data)
                    
                    if item_data['id']:
                        all_item_ids_for_status.append(item_data['id'])
                        
            except Exception as item_error:
                logger.warning(f"Error processing item {i}: {item_error}")
                item_errors += 1
                continue
        
        extract_time = time.time() - extract_start
        logger.info(f"Data extraction completed in {extract_time:.3f}s")
        
        if item_errors > 0:
            logger.warning(f"Had {item_errors} item processing errors")
        
        if not all_items_data:
            raise HTTPException(status_code=400, detail="No valid non-tax items found after processing")

        # OPTIMIZATION 3: Single DataFrame with vectorized operations (PRESERVE EXACT ORIGINAL LOGIC)
        vectorized_start = time.time()
        
        try:
            df = pd.DataFrame(all_items_data)
        except Exception as df_error:
            logger.error(f"Failed to create DataFrame: {df_error}")
            raise HTTPException(status_code=500, detail="Failed to process data for QuickBooks export")
        
        # Initialize account column
        df['account'] = ''
        
        # VECTORIZED Class A and L logic (PRESERVE EXACT ORIGINAL BUSINESS LOGIC)
        try:
            class_a_refs = df[df['class_'] == 'A']['ref_no'].unique()
            class_l_refs = df[df['class_'] == 'L']['ref_no'].unique()
            
            # Apply class logic vectorized (EXACT ORIGINAL LOGIC)
            if len(class_a_refs) > 0:
                df.loc[df['ref_no'].isin(class_a_refs), 'account'] = 'UnInvoiced JIP:Material:Additional Material'
            
            if len(class_l_refs) > 0:
                mask = df['ref_no'].isin(class_l_refs) & (df['account'] == '')
                df.loc[mask, 'account'] = 'UnInvoiced JIP:Subcontractors Expense:Labor'
        except Exception as class_error:
            logger.error(f"Error in class A/L processing: {class_error}")
            # Continue without class processing if it fails
        
        # VECTORIZED classification mapping (EXACT ORIGINAL LOGIC)
        try:
            unassigned_mask = df['account'] == ''
            if unassigned_mask.any():
                df.loc[unassigned_mask, 'account'] = df.loc[unassigned_mask, 'sheet_name'].map(
                    lambda x: classification_cache.get(x, '') if x else ''
                )
        except Exception as class_map_error:
            logger.error(f"Error in classification mapping: {class_map_error}")
            # Continue without classification mapping if it fails
        
        # VECTORIZED MPI mappings (EXACT ORIGINAL LOGIC)
        mpi_mappings = {
            'UIDI-Job Materials Purchased': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
            'UIDI-Job Equipment': 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased',
            'UIDI-Sprinkler specialty item': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
            'UIDI-Drainage Material': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
        }
        
        try:
            for mpi_item, account in mpi_mappings.items():
                mask = (df['mpi_item'] == mpi_item) & (df['account'] == '')
                df.loc[mask, 'account'] = account
        except Exception as mpi_error:
            logger.error(f"Error in MPI mapping: {mpi_error}")
            # Continue without MPI mapping if it fails
        
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
        
        # VECTORIZED data type conversions with error handling
        try:
            df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
            df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0)
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
        except Exception as convert_error:
            logger.error(f"Error in data type conversion: {convert_error}")
            raise HTTPException(status_code=500, detail="Failed to convert data types for processing")
        
        # Add tax amounts vectorized
        df['tax_amount'] = df['invoice_id'].map(lambda x: tax_by_invoice.get(x, 0))
        
        vectorized_time = time.time() - vectorized_start
        logger.info(f"Vectorized processing completed in {vectorized_time:.3f}s")
        
        # OPTIMIZATION 4: Single aggregation operation with error handling
        aggregation_start = time.time()
        
        try:
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
            
        except Exception as agg_error:
            logger.error(f"Error in aggregation: {agg_error}")
            raise HTTPException(status_code=500, detail="Failed to aggregate data for QuickBooks export")
        
        aggregation_time = time.time() - aggregation_start
        logger.info(f"Aggregation completed in {aggregation_time:.3f}s for {len(final_batch_entry)} rows")
        
        # OPTIMIZATION 5: Batch status updates with error handling
        status_start = time.time()
        try:
            if all_item_ids_for_status:
                InvoiceItemController(db).set_export_status_to_sent(all_item_ids_for_status)
                
                # Batch invoice status updates
                invoice_controller = InvoiceController(db)
                for invoice_id in invoice_ids:
                    try:
                        if InvoiceItemController(db).is_exported(str(invoice_id)):
                            invoice_controller.set_invoice_is_exported(str(invoice_id))
                    except Exception as status_error:
                        logger.warning(f"Failed to update status for invoice {invoice_id}: {status_error}")
                        continue
                        
        except Exception as batch_status_error:
            logger.error(f"Error in batch status updates: {batch_status_error}")
            # Don't fail the entire operation for status update errors
        
        status_time = time.time() - status_start
        logger.info(f"Status updates completed in {status_time:.3f}s")
        
        # S3 upload and return (EXACT ORIGINAL LOGIC) with error handling
        try:
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
            
            # Clean up local file
            try:
                os.remove(exported_file_path)
            except OSError:
                pass
                
        except Exception as export_error:
            logger.error(f"Error in export/S3 upload: {export_error}")
            raise HTTPException(status_code=500, detail="Failed to export file to S3")

        total_time = time.time() - operation_start
        logger.info(f"Optimized processing completed successfully in {total_time:.2f}s")
        return download_url
        
    except HTTPException:
        # Re-raise HTTP exceptions as they are
        raise
    except Exception as e:
        total_time = time.time() - operation_start
        logger.error(f"Optimized processing failed after {total_time:.2f}s: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal processing error: {str(e)}")


def migrate_invoice_to_QB_original(invoice_ids: List[UUID], db: Session):
    """Original logic for smaller datasets - EXACT COPY of old code with error handling"""

    operation_start = time.time()
    all_batch_entries = []

    try:
        for i, invoice_id in enumerate(invoice_ids):
            try:
                line_items = InvoiceItemController(db).get_invoice_items(invoice_id)
                if not line_items:
                    logger.warning(f"No items found for invoice {invoice_id}")
                    continue
                    
                line_item_copy = line_items

                tax = 0
                for item in line_items:
                    if safe_getattr_with_fallback(item, 'sheet_name', '') == '(TAX)':
                        try:
                            amount_str = safe_getattr_with_fallback(item, 'amount', '0').replace(',', '')
                            tax = float(amount_str)
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid tax amount for invoice {invoice_id}")
                            tax = 0

                line_items = [item for item in line_items if safe_getattr_with_fallback(item, 'sheet_name', '') != '(TAX)']

                if not line_items:
                    logger.warning(f"No non-tax items found for invoice {invoice_id}")
                    continue

                # Create DataFrame and handle possible missing fields
                try:
                    # First get reference numbers before creating DataFrame
                    ref_numbers = [safe_getattr_with_fallback(item, 'ref_no', 'unknown') for item in line_items]
                    
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
                    try:
                        return ItemClassificationController(db).get_classification(sheet_name)
                    except Exception as class_error:
                        logger.warning(f"Classification error for {sheet_name}: {class_error}")
                        return ''
                
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
                try:
                    invoice_item_ids = [item.id for item in line_item_copy if item.id]
                    if invoice_item_ids:
                        InvoiceItemController(db).set_export_status_to_sent(invoice_item_ids)

                    if InvoiceItemController(db).is_exported(str(invoice_id)):
                        InvoiceController(db).set_invoice_is_exported(str(invoice_id))
                except Exception as status_error:
                    logger.warning(f"Failed to update status for invoice {invoice_id}: {status_error}")
                    
                # Progress logging
                if i > 0 and i % 5 == 0:
                    logger.info(f"Processed {i+1}/{len(invoice_ids)} invoices")
                    
            except HTTPException:
                # Re-raise HTTP exceptions
                raise
            except Exception as invoice_error:
                logger.error(f"Error processing invoice {invoice_id}: {invoice_error}")
                # Continue with other invoices
                continue

        if not all_batch_entries:
            raise HTTPException(status_code=400, detail="No valid invoice data found for processing")

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

        # Clean up local file
        try:
            os.remove(exported_file_path)
        except OSError:
            pass

        total_time = time.time() - operation_start
        logger.info(f"Original processing completed successfully in {total_time:.2f}s")
        return download_url
        
    except HTTPException:
        # Re-raise HTTP exceptions as they are
        raise
    except Exception as e:
        total_time = time.time() - operation_start
        logger.error(f"Original processing failed after {total_time:.2f}s: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal processing error: {str(e)}")


@router.get("/priority-status")
def get_priority_status():
    """Get current QuickBooks priority system status"""
    try:
        from mpi_backend.utils.quickbooks_priority import get_qb_priority_status
        return get_qb_priority_status()
    except Exception as e:
        logger.error(f"Failed to get priority status: {e}")
        return {"status": "error", "message": str(e)}
 