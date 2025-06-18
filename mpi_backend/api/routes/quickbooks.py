from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Dict, Any
import pandas as pd
import os
import time
import logging
import threading

from mpi_backend.database import get_db, get_qb_db
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.controllers.invoice import InvoiceController
from mpi_backend.database.controllers.ItemClassification import ItemClassificationController
from mpi_backend.database.schemas import SendtoQBFilterRequest
from mpi_backend.utils.pdf_to_excel.formatting_util import export_batch_entry_to_excel
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
from mpi_backend.utils.quickbooks_priority import (
    pause_background_jobs,
    resume_background_jobs, 
    is_qb_export_active,
    QB_PRIORITY_MODE
)

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quickbooks", tags=["QuickBooks"])


def update_statuses_in_background(db, item_ids, invoice_ids):
    """Background task to update export statuses after URL is returned"""
    try:
        logger.info("Starting background status updates")
        # Process status updates in chunks for very large datasets
        STATUS_UPDATE_BATCH_SIZE = 5000
        for i in range(0, len(item_ids), STATUS_UPDATE_BATCH_SIZE):
            batch_ids = item_ids[i:i+STATUS_UPDATE_BATCH_SIZE]
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
        
        logger.info(f"Status updates completed for {len(item_ids)} items")
    except Exception as e:
        logger.error(f"Error in background status updates: {str(e)}")


@router.post("/migrate-all", response_model=Dict[str, Any])
def migrate_all_invoice_to_QB(
    request: SendtoQBFilterRequest, 
    db: Session = Depends(get_qb_db if QB_PRIORITY_MODE else get_db)
) -> Dict[str, Any]:
    """
    Migrate all invoices to QuickBooks with optional filters.
    Ultra-high-performance version for massive datasets (20K+ invoices).
    Uses dedicated database connection pool for enterprise performance.
    Returns the download URL for the exported Excel file.
    """
    start_time = time.time()
    
    # ENTERPRISE PRIORITY: Pause background jobs for maximum performance
    pause_background_jobs()
    
    try:
        logger.info(f"Starting PRIORITY QuickBooks migration with filters: {request}")
        
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
        
        logger.info(f"Found {len(invoice_id_list)} invoices to process")
        
        # Use the ultra-optimized processing logic from migrate endpoint
        # ULTRA OPTIMIZATION 1: Batch processing for massive datasets
        BATCH_SIZE = 1000  # Process 1000 invoices at a time to manage memory
        total_invoices = len(invoice_id_list)
        
        all_batch_entries = []
        all_invoice_item_ids_to_update = []
        
        # Process invoices in chunks to avoid memory issues
        for i in range(0, len(invoice_id_list), BATCH_SIZE):
            batch_invoice_ids = invoice_id_list[i:i+BATCH_SIZE]
            logger.info(f"Processing batch {i//BATCH_SIZE + 1}/{(len(invoice_id_list) + BATCH_SIZE - 1)//BATCH_SIZE}: {len(batch_invoice_ids)} invoices")
            
            # Get all invoice items for this batch
            invoice_items = InvoiceItemController(db).get_invoice_items_by_invoice_ids(batch_invoice_ids)
            
            # Get unique supplier IDs from this batch
            supplier_ids = list(set([item.supplier_id for item in invoice_items]))
            
            # Get all suppliers in one query
            suppliers_dict = {}
            suppliers = InvoiceItemController(db).get_suppliers_by_ids(supplier_ids)
            for supplier in suppliers:
                suppliers_dict[supplier.id] = supplier.name
            
            # Get all invoices in one query
            invoices_dict = {}
            invoices = InvoiceController(db).get_invoices_by_ids(batch_invoice_ids)
            for invoice in invoices:
                invoices_dict[invoice.id] = invoice
            
            # Get all classifications in one query
            classifications_dict = {}
            classifications = ItemClassificationController(db).get_all_classifications()
            for classification in classifications:
                classifications_dict[classification.id] = classification.classification
            
            # Process all invoice items in this batch
            batch_entries = []
            invoice_item_ids_to_update = []
            
            for item in invoice_items:
                try:
                    # Skip already exported items if requested
                    if request.skip_exported and item.is_exported:
                        continue
                    
                    # Get supplier name
                    supplier_name = suppliers_dict.get(item.supplier_id, "Unknown Supplier")
                    
                    # Get invoice details
                    invoice = invoices_dict.get(item.invoice_id)
                    invoice_date = invoice.date if invoice else None
                    invoice_number = invoice.invoice_number if invoice else None
                    
                    # Get classification
                    classification = classifications_dict.get(item.classification_id, "")
                    
                    # Build the batch entry
                    batch_entry = {
                        "Date": invoice_date,
                        "Ref": invoice_number,
                        "vendor": supplier_name,
                        "terms": "Due on receipt",
                        "bill due": invoice_date,
                        "account": "Purchases - Cost of Goods Sold",
                        "Amount": item.amount,
                        "Memo": item.description,
                        "Customer Job": item.customer_job,
                        "Class": classification
                    }
                    
                    batch_entries.append(batch_entry)
                    invoice_item_ids_to_update.append(item.id)
                    
                except Exception as e:
                    logger.error(f"Error processing item {item.id}: {str(e)}")
                    continue
            
            all_batch_entries.extend(batch_entries)
            all_invoice_item_ids_to_update.extend(invoice_item_ids_to_update)
            
            # Log progress
            batch_time = time.time() - start_time
            logger.info(f"Batch {i//BATCH_SIZE + 1} processed in {batch_time:.2f}s, {len(all_batch_entries)} items total")
        
        # Create final DataFrame for export
        final_batch_entry = pd.DataFrame(all_batch_entries)
        
        # Generate Excel file
        logger.info(f"Generating Excel file for {len(final_batch_entry)} rows...")
        exported_file_path = export_batch_entry_to_excel(final_batch_entry)
        file_name = os.path.basename(exported_file_path)
        
        # Upload to S3
        logger.info(f"Uploading {file_name} to S3...")
        upload_file(exported_file_path, file_key=f'Exports/{file_name}', is_invoice=False)
        
        # Generate presigned URL with extended expiration (3 hours)
        download_url = get_presigned_url(
            file_key=f'Exports/{file_name}', 
            expiration_time=10800,  # 3 hours in seconds
            is_invoice=False
        )
        
        if not download_url:
            logger.error("Failed to generate download URL")
            raise HTTPException(
                status_code=500,
                detail="Failed to generate download URL for export file"
            )
        
        # Start a background thread for status updates
        status_thread = threading.Thread(
            target=update_statuses_in_background,
            args=(db, all_invoice_item_ids_to_update, invoice_id_list)
        )
        status_thread.daemon = True
        status_thread.start()
        
        total_time = time.time() - start_time
        logger.info(f"PRIORITY QuickBooks migration completed in {total_time:.2f}s for {total_invoices} invoices!")
        
        # Return URL immediately without waiting for status updates
        return {
            "download_url": download_url,
            "processing_time": round(total_time, 2),
            "invoices_processed": total_invoices,
            "items_processed": len(all_batch_entries),
            "file_name": file_name,
            "status_updates": "processing in background"
        }
    
    except Exception as e:
        logger.error(f"QuickBooks export error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"QuickBooks export failed: {str(e)}")
    
    finally:
        # Always resume background jobs, even if export fails
        resume_background_jobs()


@router.post("/migrate", response_model=Dict[str, Any])
def migrate_invoice_to_QB(
    invoice_ids: List[UUID], 
    db: Session = Depends(get_qb_db if QB_PRIORITY_MODE else get_db)
) -> Dict[str, Any]:
    """
    Migrate specific invoices to QuickBooks.
    High-performance version for specific invoice selection.
    Uses dedicated database connection pool for enterprise performance.
    Returns the download URL for the exported Excel file.
    """
    start_time = time.time()
    
    # ENTERPRISE PRIORITY: Pause background jobs for maximum performance
    pause_background_jobs()
    
    try:
        logger.info(f"Starting PRIORITY QuickBooks migration for {len(invoice_ids)} invoices")
        
        if not invoice_ids:
            raise HTTPException(status_code=400, detail="No invoice IDs provided.")
        
        total_invoices = len(invoice_ids)
        
        # Get all invoice items for these invoices
        invoice_items = InvoiceItemController(db).get_invoice_items_by_invoice_ids(invoice_ids)
        
        # Get unique supplier IDs
        supplier_ids = list(set([item.supplier_id for item in invoice_items]))
        
        # Get all suppliers in one query
        suppliers_dict = {}
        suppliers = InvoiceItemController(db).get_suppliers_by_ids(supplier_ids)
        for supplier in suppliers:
            suppliers_dict[supplier.id] = supplier.name
        
        # Get all invoices in one query
        invoices_dict = {}
        invoices = InvoiceController(db).get_invoices_by_ids(invoice_ids)
        for invoice in invoices:
            invoices_dict[invoice.id] = invoice
        
        # Get all classifications in one query
        classifications_dict = {}
        classifications = ItemClassificationController(db).get_all_classifications()
        for classification in classifications:
            classifications_dict[classification.id] = classification.classification
        
        # Process all invoice items
        batch_entries = []
        invoice_item_ids_to_update = []
        
        for item in invoice_items:
            try:
                # Get supplier name
                supplier_name = suppliers_dict.get(item.supplier_id, "Unknown Supplier")
                
                # Get invoice details
                invoice = invoices_dict.get(item.invoice_id)
                invoice_date = invoice.date if invoice else None
                invoice_number = invoice.invoice_number if invoice else None
                
                # Get classification
                classification = classifications_dict.get(item.classification_id, "")
                
                # Build the batch entry
                batch_entry = {
                    "Date": invoice_date,
                    "Ref": invoice_number,
                    "vendor": supplier_name,
                    "terms": "Due on receipt",
                    "bill due": invoice_date,
                    "account": "Purchases - Cost of Goods Sold",
                    "Amount": item.amount,
                    "Memo": item.description,
                    "Customer Job": item.customer_job,
                    "Class": classification
                }
                
                batch_entries.append(batch_entry)
                invoice_item_ids_to_update.append(item.id)
                
            except Exception as e:
                logger.error(f"Error processing item {item.id}: {str(e)}")
                continue
        
        # Create DataFrame for export
        final_batch_entry = pd.DataFrame(batch_entries)
        
        # Generate Excel file
        logger.info(f"Generating Excel file for {len(final_batch_entry)} rows...")
        exported_file_path = export_batch_entry_to_excel(final_batch_entry)
        file_name = os.path.basename(exported_file_path)
        
        # Upload to S3
        logger.info(f"Uploading {file_name} to S3...")
        upload_file(exported_file_path, file_key=f'Exports/{file_name}', is_invoice=False)
        
        # Generate presigned URL with extended expiration (3 hours)
        download_url = get_presigned_url(
            file_key=f'Exports/{file_name}', 
            expiration_time=10800,  # 3 hours in seconds
            is_invoice=False
        )
        
        if not download_url:
            logger.error("Failed to generate download URL")
            raise HTTPException(
                status_code=500,
                detail="Failed to generate download URL for export file"
            )
        
        # Start a background thread for status updates
        status_thread = threading.Thread(
            target=update_statuses_in_background,
            args=(db, invoice_item_ids_to_update, invoice_ids)
        )
        status_thread.daemon = True
        status_thread.start()
        
        total_time = time.time() - start_time
        logger.info(f"PRIORITY QuickBooks migration completed in {total_time:.2f}s for {total_invoices} invoices!")
        
        # Return URL immediately without waiting for status updates
        return {
            "download_url": download_url,
            "processing_time": round(total_time, 2),
            "invoices_processed": total_invoices,
            "items_processed": len(batch_entries),
            "file_name": file_name,
            "status_updates": "processing in background"
        }
    
    except Exception as e:
        logger.error(f"QuickBooks export error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"QuickBooks export failed: {str(e)}")
    
    finally:
        # Always resume background jobs, even if export fails
        resume_background_jobs()
 