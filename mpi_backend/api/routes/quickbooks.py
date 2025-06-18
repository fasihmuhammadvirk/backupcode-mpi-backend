from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
import pandas as pd
import time
import logging
import traceback
from contextlib import contextmanager
from mpi_backend.database import get_qb_db
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

# CRITICAL: Global progress tracking for QuickBooks operations
qb_operation_progress = {}


def update_progress(operation_id: str, stage: str, progress: int, 
                   message: str = ""):
    """Update progress for QuickBooks operations"""
    qb_operation_progress[operation_id] = {
        "stage": stage,
        "progress": progress,
        "message": message,
        "timestamp": time.time()
    }
    logger.info(f"QB Progress [{operation_id}]: {stage} - {progress}% - "
                f"{message}")


@router.get("/progress/{operation_id}")
def get_operation_progress(operation_id: str):
    """Get real-time progress for QuickBooks operations"""
    if operation_id in qb_operation_progress:
        return qb_operation_progress[operation_id]
    else:
        raise HTTPException(
            status_code=404, 
            detail=f"Operation {operation_id} not found"
        )


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


def perform_database_updates_background(all_item_ids_for_status: List, 
                                      operation_id: str):
    """
    Background task to handle ONLY item-level status updates after Excel generation.
    Invoice status updates are now done immediately before download URL is returned.
    """
    try:
        # Create a new database session for background processing
        from mpi_backend.database import get_qb_db
        db_gen = get_qb_db()
        db = next(db_gen)
        
        update_progress(operation_id, "background_updating", 95, 
                       "Updating item status in background")
        
        status_start = time.time()
        
        # ONLY update item-level export status in background
        if all_item_ids_for_status:
            InvoiceItemController(db).set_export_status_to_sent(
                all_item_ids_for_status)
        
        status_time = time.time() - status_start
        logger.info(f"Background item status updates completed in {status_time:.3f}s "
                   f"for {len(all_item_ids_for_status)} items")
        
        update_progress(operation_id, "background_completed", 100, 
                       f"Background updates completed - {len(all_item_ids_for_status)} items updated")
        
    except Exception as e:
        logger.error(f"Background database update failed: {e}")
        update_progress(operation_id, "background_error", 100, 
                       f"Background update error: {str(e)}")
    finally:
        try:
            db.close()
        except:
            pass


def update_invoice_statuses_immediately(invoice_ids: List[UUID], db: Session, operation_id: str):
    """
    IMMEDIATE invoice status updates - called right before returning download URL.
    This ensures invoice status changes from pending to sent when user gets Excel file.
    """
    try:
        update_progress(operation_id, "updating_invoices", 88, 
                       "Updating invoice statuses to 'sent'")
        
        status_start = time.time()
        invoice_controller = InvoiceController(db)
        updated_invoices = 0
        
        # Update all invoice statuses immediately
        for invoice_id in invoice_ids:
            try:
                # Set invoice as exported immediately (optimistic update)
                invoice_controller.set_invoice_is_exported(str(invoice_id))
                updated_invoices += 1
            except Exception as e:
                logger.warning(f"Failed to update invoice {invoice_id}: {e}")
                continue
        
        status_time = time.time() - status_start
        logger.info(f"IMMEDIATE invoice status updates completed in {status_time:.3f}s "
                   f"for {updated_invoices} invoices")
        
        return updated_invoices
        
    except Exception as e:
        logger.error(f"Immediate invoice status update failed: {e}")
        return 0


@router.post("/migrate-all")
def migrate_all_invoice_to_QB(request: SendtoQBFilterRequest, 
                            background_tasks: BackgroundTasks,
                            db: Session = Depends(get_qb_db)):
    """ULTRA-FAST: QuickBooks migration optimized to match export-all speed"""
    operation_start = time.time()
    operation_id = f"qb_migrate_all_{int(operation_start)}"
    
    with safe_priority_context("migrate_all"):
        try:
            logger.info("Starting ULTRA-FAST QuickBooks migration")
            
            # ULTRA-FAST filtering - get just IDs like export-all does
            invoice_ids = InvoiceItemController(db).apply_filters(
                request, page=1, size=0, col_param='invoice_id')

            if request.excluded_invoice_ids:
                excluded_set = set(request.excluded_invoice_ids)
                invoice_ids = [
                    invoice_id for invoice_id in invoice_ids 
                    if invoice_id not in excluded_set
                ]

            # Validate and clean invoice IDs
            invoice_ids = validate_invoice_ids(invoice_ids)

            logger.info(f"Migrate-all processing {len(invoice_ids)} invoices")
            
            # ULTRA-FAST PROCESSING: Generate Excel and return immediately
            result = migrate_invoice_to_QB_fast(
                invoice_ids, db=db, operation_id=operation_id, 
                background_tasks=background_tasks)
            
            operation_time = time.time() - operation_start
            logger.info(f"Migrate-all completed ULTRA-FAST in {operation_time:.2f}s")
            return result
            
        except Exception as e:
            operation_time = time.time() - operation_start
            logger.error(f"QuickBooks migrate-all failed after {operation_time:.2f}s: {str(e)}")
            raise


@router.post("/migrate")
def migrate_invoice_to_QB(invoice_ids: List[UUID], 
                        background_tasks: BackgroundTasks,
                        db: Session = Depends(get_qb_db)):
    """QuickBooks migration with priority control - small datasets stay synchronous"""
    start_time = time.time()
    operation_id = f"qb_migrate_{int(start_time)}"
    
    with safe_priority_context("regular"):
        try:
            # Validate input
            invoice_ids = validate_invoice_ids(invoice_ids)
            
            logger.info(f"Processing {len(invoice_ids)} invoices")
            
            # For smaller datasets, keep synchronous processing
            # For larger datasets, use fast async processing
            if len(invoice_ids) > 50:
                result = migrate_invoice_to_QB_fast(
                    invoice_ids, db=db, operation_id=operation_id,
                    background_tasks=background_tasks)
            else:
                result = migrate_invoice_to_QB_internal(
                    invoice_ids, db=db, operation_id=operation_id)
                
            total_time = time.time() - start_time
            logger.info(f"QuickBooks migration completed successfully in "
                       f"{total_time:.2f}s")
            return result
            
        except Exception as e:
            total_time = time.time() - start_time
            logger.error(f"QuickBooks migration failed after "
                        f"{total_time:.2f}s: {str(e)}")
            raise


def safe_getattr_with_fallback(obj, attr, default=''):
    """Safely get attribute with fallback and logging"""
    try:
        value = getattr(obj, attr, default)
        if value is None:
            return default
        return str(value) if not isinstance(value, str) else value
    except Exception as e:
        logger.warning(f"Error getting attribute {attr}: {e}")
        return default


def migrate_invoice_to_QB_fast(invoice_ids: List[UUID], 
                              db: Session, operation_id: str,
                              background_tasks: BackgroundTasks) -> str:
    """
    ULTRA-FAST QuickBooks migration - optimized to match export-all speed
    """
    
    # FAST START - minimal logging
    start_time = time.time()
    logger.info(f"FAST QB migration starting for {len(invoice_ids)} invoices")
    
    # ULTRA-FAST data retrieval - direct database query like export-all
    from mpi_backend.database.models import InvoiceItem
    invoice_items = db.query(InvoiceItem).filter(
        InvoiceItem.invoice_id.in_(invoice_ids),
        InvoiceItem.is_active == True
    ).all()
    
    if not invoice_items:
        raise HTTPException(status_code=400, detail="No items found")
    
    logger.info(f"Retrieved {len(invoice_items)} items in {time.time() - start_time:.3f}s")
    
    # FAST classification cache - only build for unique sheet names
    classification_controller = ItemClassificationController(db)
    unique_sheet_names = {getattr(item, 'sheet_name', '') for item in invoice_items if getattr(item, 'sheet_name', '')}
    
    # Bulk classification lookup
    classification_cache = {'': '', None: ''}
    if unique_sheet_names:
        try:
            from mpi_backend.database.models import ItemClassification
            classifications = db.query(ItemClassification).filter(
                ItemClassification.item.in_(unique_sheet_names)
            ).all()
            
            for classification in classifications:
                account = ''
                if classification.category == 'M':
                    account = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
                elif classification.category == 'E':
                    account = 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased'
                classification_cache[classification.item] = account
                
        except Exception as e:
            logger.warning(f"Bulk classification failed: {e}, using fallback")
    
    # ULTRA-FAST single-pass data processing
    process_start = time.time()
    
    # Pre-allocate lists for speed
    all_items_data = []
    tax_by_invoice = {}
    all_item_ids_for_status = []
    
    # Single pass through ALL items - optimized for speed
    for item in invoice_items:
        item_sheet_name = getattr(item, 'sheet_name', '') or ''
        item_invoice_id = getattr(item, 'invoice_id')
        
        # Fast tax calculation
        if item_sheet_name == '(TAX)':
            if item_invoice_id not in tax_by_invoice:
                tax_by_invoice[item_invoice_id] = 0
            try:
                amount_str = str(getattr(item, 'amount', '0')).replace(',', '')
                tax_by_invoice[item_invoice_id] += float(amount_str)
            except (ValueError, TypeError):
                pass
        else:
            # Fast data extraction - direct attribute access
            item_data = {
                'id': getattr(item, 'id', None),
                'invoice_id': item_invoice_id,
                'sheet_name': item_sheet_name,
                'mpi_item': getattr(item, 'mpi_item', 'No Match') or 'No Match',
                'item': getattr(item, 'item', '') or '',
                'description': getattr(item, 'description', '') or '',
                'qty': getattr(item, 'qty', 0) or 0,
                'cost': getattr(item, 'cost', 0.0) or 0.0,
                'amount': getattr(item, 'amount', '0') or '0',
                'date': getattr(item, 'date', None),
                'ref_no': getattr(item, 'ref_no', '') or '',
                'customer_job': getattr(item, 'customer_job', '') or '',
                'vendor': getattr(item, 'vendor', '') or '',
                'class_': getattr(item, 'class_', '') or '',
                'memo': getattr(item, 'memo', '') or '',
            }
            all_items_data.append(item_data)
            
            if item_data['id']:
                all_item_ids_for_status.append(item_data['id'])
    
    if not all_items_data:
        raise HTTPException(status_code=400, detail="No non-tax items found")
    
    logger.info(f"Data processing completed in {time.time() - process_start:.3f}s")
    
    # VECTORIZED operations - ultra-fast pandas processing
    vectorized_start = time.time()
    
    df = pd.DataFrame(all_items_data)
    df['account'] = ''
    
    # FAST Class A and L logic
    class_a_mask = df['class_'] == 'A'
    class_l_mask = df['class_'] == 'L'
    
    if class_a_mask.any():
        class_a_refs = df.loc[class_a_mask, 'ref_no'].unique()
        df.loc[df['ref_no'].isin(class_a_refs), 'account'] = 'UnInvoiced JIP:Material:Additional Material'
    
    if class_l_mask.any():
        class_l_refs = df.loc[class_l_mask, 'ref_no'].unique()
        mask = df['ref_no'].isin(class_l_refs) & (df['account'] == '')
        df.loc[mask, 'account'] = 'UnInvoiced JIP:Subcontractors Expense:Labor'
    
    # FAST classification mapping
    unassigned_mask = df['account'] == ''
    if unassigned_mask.any():
        df.loc[unassigned_mask, 'account'] = df.loc[unassigned_mask, 'sheet_name'].map(
            classification_cache.get
        ).fillna('')
    
    # FAST MPI mappings
    mpi_mappings = {
        'UIDI-Job Materials Purchased': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
        'UIDI-Job Equipment': 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased',
        'UIDI-Sprinkler specialty item': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
        'UIDI-Drainage Material': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
    }
    
    for mpi_item, account in mpi_mappings.items():
        mask = (df['mpi_item'] == mpi_item) & (df['account'] == '')
        if mask.any():
            df.loc[mask, 'account'] = account
    
    # Default account for unmatched
    df.loc[df['account'] == '', 'account'] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
    
    # FAST data type conversions
    df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
    df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0)
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
    df['tax_amount'] = df['invoice_id'].map(tax_by_invoice).fillna(0)
    
    logger.info(f"Vectorized processing in {time.time() - vectorized_start:.3f}s")
    
    # FAST aggregation
    agg_start = time.time()
    
    batch_entry = df.groupby(['account', 'ref_no', 'customer_job'], as_index=False).agg({
        'amount': 'sum',
        'tax_amount': 'first',
        'date': 'first',
        'vendor': 'first',
        'memo': 'first',
        'class_': 'first'
    })
    
    # Add tax to amount
    batch_entry['amount'] = batch_entry['amount'] + batch_entry['tax_amount']
    
    # FAST formatting
    batch_entry['date'] = pd.to_datetime(batch_entry['date'], errors='coerce').dt.strftime('%m/%d/%Y')
    batch_entry['terms'] = ''
    batch_entry['bill due'] = ''
    
    # Column mapping
    final_batch_entry = batch_entry.rename(columns={
        'date': 'Date', 'ref_no': 'Ref', 'amount': 'Amount', 
        'customer_job': 'Customer Job', 'class_': 'Class', 'memo': 'Memo'
    })[[
        'Date', 'Ref', 'vendor', 'terms', 'bill due', 
        'account', 'Amount', 'Memo', 'Customer Job', 'Class'
    ]]
    
    logger.info(f"Aggregation completed in {time.time() - agg_start:.3f}s for {len(final_batch_entry)} rows")
    
    # FAST Excel generation and S3 upload
    excel_start = time.time()
    
    # Use same fast method as export-all
    try:
        from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data_fast
        from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
        from datetime import datetime
        import os
        
        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
        filename = f'qb_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        file_path = f'{upload_folder}{filename}'
        
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        # FAST Excel save
        save_final_data_fast(final_batch_entry, file_path)
        
        # FAST S3 upload
        upload_file(file_path, file_key=f'Exports/{filename}', is_invoice=False)
        download_url = get_presigned_url(file_key=f'Exports/{filename}', is_invoice=False)
        
        # Clean up
        try:
            os.remove(file_path)
        except OSError:
            pass
            
    except Exception as upload_error:
        logger.error(f"S3 upload failed: {str(upload_error)}")
        raise HTTPException(status_code=500, detail="Failed to upload to S3")
    
    logger.info(f"Excel and S3 upload in {time.time() - excel_start:.3f}s")
    
    # IMMEDIATE invoice status update - no progress tracking for speed
    try:
        invoice_controller = InvoiceController(db)
        updated_invoices = 0
        for invoice_id in invoice_ids:
            try:
                invoice_controller.set_invoice_is_exported(str(invoice_id))
                updated_invoices += 1
            except Exception:
                continue
        logger.info(f"IMMEDIATE: Updated {updated_invoices} invoice statuses")
    except Exception as e:
        logger.warning(f"Invoice status update failed: {e}")
        updated_invoices = 0
    
    # Background item status updates - minimal overhead
    if all_item_ids_for_status:
        background_tasks.add_task(
            perform_database_updates_background,
            all_item_ids_for_status,
            operation_id
        )
    
    total_time = time.time() - start_time
    logger.info(f"ULTRA-FAST QB EXPORT COMPLETED: {len(final_batch_entry)} rows in {total_time:.2f}s")
    
    return download_url


def migrate_invoice_to_QB_internal(invoice_ids: List[UUID], 
                                 db: Session, operation_id: str) -> str:
    """
    Original synchronous migration function for smaller datasets
    """
    
    # Fast data retrieval with progress tracking
    retrieval_start = time.time()
    update_progress(operation_id, "retrieving_data", 30, 
                   f"Retrieving data for {len(invoice_ids)} invoices")
    
    # Get all required data efficiently
    invoice_items = []
    if hasattr(InvoiceItemController(db), 'get_invoice_items_by_invoice_ids'):
        try:
            invoice_items = InvoiceItemController(db).get_invoice_items_by_invoice_ids(invoice_ids)
        except Exception as bulk_error:
            logger.warning(f"Bulk retrieval failed: {bulk_error}, falling back")
    
    # Fallback to individual calls if bulk fails
    if not invoice_items:
        for invoice_id in invoice_ids:
            try:
                items = InvoiceItemController(db).get_invoice_items(invoice_id)
                if items:
                    invoice_items.extend(items)
            except Exception:
                continue
    
    retrieval_time = time.time() - retrieval_start
    logger.info(f"Data retrieval completed in {retrieval_time:.3f}s for "
               f"{len(invoice_items)} items")
    
    update_progress(operation_id, "processing_data", 50, 
                   f"Processing {len(invoice_items)} items")
    
    # Single-pass data extraction (PRESERVE EXACT ORIGINAL LOGIC)
    extract_start = time.time()
    
    all_items_data = []
    tax_by_invoice = {}
    all_item_ids_for_status = []
    
    # Get classification controller
    classification_controller = ItemClassificationController(db)
    
    # Pre-build classification cache
    unique_sheet_names = set()
    for item in invoice_items:
        sheet_name = getattr(item, 'sheet_name', '')
        if sheet_name and sheet_name.strip():
            unique_sheet_names.add(sheet_name)
    
    # Build classification cache
    classification_cache = {'': '', None: ''}
    for sheet_name in unique_sheet_names:
        try:
            classification_cache[sheet_name] = classification_controller.get_classification(sheet_name)
        except Exception:
            classification_cache[sheet_name] = ''

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
            # Extract all item data (EXACT ORIGINAL LOGIC)
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
            
            if item_data['id']:
                all_item_ids_for_status.append(item_data['id'])
    
    extract_time = time.time() - extract_start
    logger.info(f"Data extraction completed in {extract_time:.3f}s")
    
    if not all_items_data:
        raise HTTPException(status_code=400, detail="No non-tax items found")

    update_progress(operation_id, "processing_data", 60, 
                   "Performing vectorized data operations")

    # Vectorized operations with DataFrame (PRESERVE EXACT ORIGINAL LOGIC)
    vectorized_start = time.time()
    
    df = pd.DataFrame(all_items_data)
    df['account'] = ''
    
    # VECTORIZED Class A and L logic (EXACT ORIGINAL BUSINESS LOGIC)
    class_a_refs = df[df['class_'] == 'A']['ref_no'].unique()
    class_l_refs = df[df['class_'] == 'L']['ref_no'].unique()
    
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
    
    # CRITICAL BUSINESS LOGIC FIX: Default account for unmatched items
    df.loc[df['account'] == '', 'account'] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
    
    # VECTORIZED data type conversions
    df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
    df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0)
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
    
    # Add tax amounts vectorized
    df['tax_amount'] = df['invoice_id'].map(lambda x: tax_by_invoice.get(x, 0))
    
    vectorized_time = time.time() - vectorized_start
    logger.info(f"Vectorized processing completed in {vectorized_time:.3f}s")
    
    update_progress(operation_id, "aggregating", 70, 
                   "Aggregating data for QuickBooks export")

    # Single aggregation operation
    aggregation_start = time.time()
    
    batch_entry = df.groupby(['account', 'ref_no', 'customer_job']).agg({
        'amount': 'sum',
        'tax_amount': 'first',
        'date': 'first',
        'vendor': 'first',
        'memo': 'first',
        'class_': 'first'
    }).reset_index()
    
    # Add tax to amount
    batch_entry['amount'] = batch_entry['amount'] + batch_entry['tax_amount']
    
    # Final formatting
    batch_entry['date'] = pd.to_datetime(batch_entry['date'], 
                                        errors='coerce').dt.strftime('%m/%d/%Y')
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
    logger.info(f"Aggregation completed in {aggregation_time:.3f}s for "
               f"{len(final_batch_entry)} rows")
    
    update_progress(operation_id, "generating_excel", 80, 
                   f"Generating Excel file with {len(final_batch_entry)} rows")

    # Excel generation
    excel_start = time.time()
    exported_file_path = export_batch_entry_to_excel(final_batch_entry)
    file_name = os.path.basename(exported_file_path)
    excel_time = time.time() - excel_start
    logger.info(f"Excel generation completed in {excel_time:.3f}s")
    
    update_progress(operation_id, "updating_status", 90, 
                   "Updating database status")

    # Synchronous status updates for smaller datasets  
    status_start = time.time()
    
    # Update invoice statuses immediately
    updated_invoices = update_invoice_statuses_immediately(invoice_ids, db, operation_id)
    
    # Update item statuses synchronously for smaller datasets
    if all_item_ids_for_status:
        InvoiceItemController(db).set_export_status_to_sent(
            all_item_ids_for_status)
    
    status_time = time.time() - status_start
    logger.info(f"Status updates completed in {status_time:.3f}s for "
               f"{updated_invoices} invoices and {len(all_item_ids_for_status)} items")
    
    update_progress(operation_id, "uploading", 95, "Uploading to S3")

    # S3 upload
    upload_start = time.time()
    try:
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
        logger.info(f"S3 upload completed in {upload_time:.3f}s")
        
        # Clean up local file
        try:
            os.remove(exported_file_path)
        except OSError:
            pass
            
    except Exception as upload_error:
        logger.error(f"S3 upload failed: {str(upload_error)}")
        raise HTTPException(status_code=500, detail="Failed to upload to S3")
    
    # Final completion
    total_time = time.time() - retrieval_start
    update_progress(operation_id, "completed", 100, 
                   f"Export completed in {total_time:.2f}s")
    
    logger.info(f"SYNCHRONOUS EXPORT COMPLETED: {len(final_batch_entry)} rows "
               f"in {total_time:.2f}s")
    
    return download_url


@router.get("/priority-status")
def get_priority_status():
    """Get current QuickBooks priority system status"""
    try:
        from mpi_backend.utils.quickbooks_priority import get_qb_priority_status
        return get_qb_priority_status()
    except Exception as e:
        logger.error(f"Failed to get priority status: {e}")
        return {"status": "error", "message": str(e)}
 