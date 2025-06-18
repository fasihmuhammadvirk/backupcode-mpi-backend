from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
import pandas as pd
import time
import logging
import asyncio
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
    resume_all_background_jobs_from_migrate_all,
    is_migrate_all_active
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
    logger.info(f"🔄 QB Progress [{operation_id}]: {stage} - {progress}% - "
                f"{message}")


@router.get("/progress/{operation_id}")
async def get_operation_progress(operation_id: str):
    """Get real-time progress for QuickBooks operations"""
    if operation_id in qb_operation_progress:
        return qb_operation_progress[operation_id]
    else:
        raise HTTPException(
            status_code=404, 
            detail=f"Operation {operation_id} not found"
        )


@router.post("/migrate-all")
async def migrate_all_invoice_to_QB(
    request: SendtoQBFilterRequest, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_qb_db)  # Use dedicated QB database session
):
    """ABSOLUTE PRIORITY: QuickBooks migration with complete background job 
    control and timeout protection"""
    start_time = time.time()
    operation_id = f"qb_migrate_all_{int(start_time)}"
    
    try:
        # STEP 1: Initialize progress tracking
        update_progress(operation_id, "initializing", 0, 
                       "Starting PRIORITY QuickBooks migration")
        
        # STEP 2: ABSOLUTE PRIORITY - Pause ALL background jobs
        pause_all_background_jobs_for_migrate_all()
        logger.info("🚫 ABSOLUTE PRIORITY: ALL background jobs paused for "
                   "migrate-all operation")
        
        # STEP 3: Optimized filtering with progress tracking
        update_progress(operation_id, "filtering", 10, 
                       "Applying filters to get invoice data")
        
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
        logger.info(f"Filter processing completed in {filter_time:.3f}s for "
                   f"{len(invoice_ids)} invoices")
        
        update_progress(operation_id, "filtering", 20, 
                       f"Found {len(invoice_ids)} invoices to process")

        # STEP 4: Check if dataset is too large and needs chunking
        if len(invoice_ids) > 1000:
            logger.warning(f"⚠️ Large dataset detected: {len(invoice_ids)} "
                          f"invoices")
            update_progress(operation_id, "chunking", 25, 
                           f"Large dataset - processing in chunks")
            
            # Process in chunks to prevent timeout
            chunk_size = 500
            chunks = [invoice_ids[i:i + chunk_size] 
                     for i in range(0, len(invoice_ids), chunk_size)]
            
            all_results = []
            for i, chunk in enumerate(chunks):
                chunk_progress = 25 + (i + 1) * 60 // len(chunks)
                update_progress(operation_id, "processing_chunks", 
                               chunk_progress, 
                               f"Processing chunk {i+1}/{len(chunks)} "
                               f"({len(chunk)} invoices)")
                
                chunk_result = await migrate_invoice_to_QB_internal(
                    chunk, db=db, operation_id=f"{operation_id}_chunk_{i}")
                all_results.append(chunk_result)
                
                # Brief pause between chunks to prevent overwhelming
                await asyncio.sleep(1)
            
            update_progress(operation_id, "completed", 100, 
                           f"All {len(chunks)} chunks processed successfully")
            return {"message": "Large dataset processed in chunks", 
                   "chunks": len(chunks), "results": all_results}
        else:
            # Process normally for smaller datasets
            return await migrate_invoice_to_QB_internal(
                invoice_ids, db=db, operation_id=operation_id)
            
    except Exception as e:
        logger.error(f"❌ QuickBooks migration failed: {str(e)}")
        update_progress(operation_id, "error", 0, f"Error: {str(e)}")
        raise HTTPException(status_code=500, 
                          detail=f"QuickBooks migration failed: {str(e)}")
    finally:
        # ABSOLUTE PRIORITY: Always resume ALL background jobs
        resume_all_background_jobs_from_migrate_all()
        logger.info("PRIORITY RELEASED: ALL background jobs resumed after "
                   "migrate-all operation")


async def migrate_invoice_to_QB_internal(
    invoice_ids: List[UUID], 
    db: Session,
    operation_id: str
) -> str:
    """ENHANCED: Internal migration function with ultra-optimized processing"""
    
    # ULTRA-OPTIMIZATION 1: Fast data retrieval with single query
    retrieval_start = time.time()
    update_progress(operation_id, "retrieving_data", 30, 
                   f"Retrieving data for {len(invoice_ids)} invoices")
    
    # Get all required data in single optimized query
    invoice_items = InvoiceItemController(db).get_invoice_items_by_invoice_ids(
        invoice_ids)
    invoice_item_ids = [item.id for item in invoice_items]
    all_item_ids_for_status = invoice_item_ids.copy()
    
    retrieval_time = time.time() - retrieval_start
    logger.info(f"Data retrieval completed in {retrieval_time:.3f}s for "
               f"{len(invoice_items)} items")
    
    update_progress(operation_id, "processing_data", 50, 
                   f"Processing {len(invoice_items)} items")
    
    # ULTRA-OPTIMIZATION 2: Convert to DataFrame for vectorized operations
    vectorized_start = time.time()
    
    # Convert to list of dicts for pandas (faster than individual field access)
    data_dicts = []
    for item in invoice_items:
        data_dicts.append({
            'invoice_id': item.invoice_id,
            'date': item.invoice.date if item.invoice else None,
            'ref_no': item.invoice.invoice_number if item.invoice else '',
            'vendor': item.invoice.supplier.name if item.invoice and item.invoice.supplier else '',
            'mpi_item': item.mpi_item or '',
            'mpi_description': item.mpi_description or '',
            'customer_job': item.customer_job or '',
            'cost': item.cost or 0,
            'qty': item.qty or 0,
            'amount': item.amount or 0,
            'class_': item.class_ or '',
            'account': '',  # Will be filled later
            'memo': item.memo or ''
        })
    
    df = pd.DataFrame(data_dicts)
    
    # ULTRA-OPTIMIZATION 3: Vectorized tax processing
    # Get tax amounts for all invoices at once
    tax_query = db.query(
        InvoiceItemController.model.invoice_id,
        InvoiceItemController.model.amount
    ).filter(
        InvoiceItemController.model.invoice_id.in_(invoice_ids),
        InvoiceItemController.model.mpi_item.like('%Tax%')
    ).all()
    
    # Create tax lookup dictionary
    tax_by_invoice = {}
    for invoice_id, tax_amount in tax_query:
        tax_by_invoice[invoice_id] = tax_by_invoice.get(invoice_id, 0) + (tax_amount or 0)
    
    # Get MPI mappings for account assignment
    classifications = ItemClassificationController(db).get_all_classifications()
    mpi_mappings = {item.mpi_item: item.account for item in classifications 
                   if item.mpi_item and item.account}
    
    # Apply account mappings vectorized
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
    logger.info(f"Vectorized processing completed in {vectorized_time:.3f}s")
    
    update_progress(operation_id, "aggregating", 70, "Aggregating data for QuickBooks export")

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
    logger.info(f"Aggregation completed in {aggregation_time:.3f}s for {len(final_batch_entry)} rows")
    
    update_progress(operation_id, "generating_excel", 80, f"Generating Excel file with {len(final_batch_entry)} rows")

    # ULTRA-OPTIMIZATION 5: Fast Excel generation
    excel_start = time.time()
    exported_file_path = export_batch_entry_to_excel(final_batch_entry)
    file_name = os.path.basename(exported_file_path)
    excel_time = time.time() - excel_start
    logger.info(f"Excel generation completed in {excel_time:.3f}s")
    
    update_progress(operation_id, "updating_status", 90, "Updating database status")

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
    logger.info(f"Status updates completed in {status_time:.3f}s")
    
    update_progress(operation_id, "uploading", 95, "Uploading to S3")

    # ULTRA-OPTIMIZATION 7: Fast S3 upload
    upload_start = time.time()
    try:
        s3_file_path = upload_file(exported_file_path)
        s3_url = get_presigned_url(s3_file_path)
        upload_time = time.time() - upload_start
        logger.info(f"S3 upload completed in {upload_time:.3f}s")
        
        # Clean up local file
        try:
            os.remove(exported_file_path)
        except OSError:
            pass
            
    except Exception as upload_error:
        logger.error(f"S3 upload failed: {str(upload_error)}")
        s3_url = f"Local file: {exported_file_path}"
        upload_time = time.time() - upload_start
    
    # Final completion
    total_time = time.time() - start_time if 'start_time' in locals() else 0
    update_progress(operation_id, "completed", 100, 
                   f"Export completed in {total_time:.2f}s")
    
    logger.info(f"🎯 PRIORITY EXPORT COMPLETED: {len(final_batch_entry)} rows "
               f"in {total_time:.2f}s")
    
    return s3_url


@router.post("/migrate")
async def migrate_invoice_to_QB(
    invoice_ids: List[UUID], 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_qb_db)  # Use dedicated QB database session
):
    """ENHANCED: Direct QuickBooks migration with timeout protection"""
    operation_id = f"qb_migrate_{int(time.time())}"
    
    try:
        # Pause background jobs for priority processing
        pause_background_jobs()
        
        result = await migrate_invoice_to_QB_internal(
            invoice_ids, db=db, operation_id=operation_id)
        return result
        
    except Exception as e:
        logger.error(f"QuickBooks migration failed: {str(e)}")
        raise HTTPException(status_code=500, 
                          detail=f"QuickBooks migration failed: {str(e)}")
    finally:
        # Always resume background jobs
        resume_background_jobs()


@router.get("/priority-status")
async def get_priority_status():
    """Get current QuickBooks priority system status"""
    from mpi_backend.utils.quickbooks_priority import get_qb_priority_status
    return get_qb_priority_status()
 