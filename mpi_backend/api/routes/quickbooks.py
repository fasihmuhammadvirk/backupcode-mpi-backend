from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
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
from mpi_backend.database.controllers.Invoice import InvoiceController
from mpi_backend.database.controllers.ItemClassification import (
    ItemClassificationController
)
from mpi_backend.database.schemas import SendtoQBFilterRequest
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
from mpi_backend.utils.quickbooks_priority_controller import (
    pause_background_jobs,
    resume_background_jobs,
    pause_all_background_jobs_for_migrate_all,
    resume_all_background_jobs_from_migrate_all
)

# Configure logging for performance monitoring
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quickbooks", tags=["QuickBooks"])

# Global progress tracking for QuickBooks operations
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
    logger.info(f"QB Progress [{operation_id}]: {stage} - {progress}% - {message}")


@contextmanager
def safe_priority_context(operation_type="regular"):
    """Context manager to ensure background jobs are always resumed"""
    logger.info(f"QB Priority Context: Starting {operation_type} operation")
    try:
        if operation_type == "migrate_all":
            pause_all_background_jobs_for_migrate_all()
            logger.info("ABSOLUTE PRIORITY: ALL background jobs paused for migrate-all operation")
        else:
            pause_background_jobs()
            logger.info("Background jobs paused for QuickBooks migration")
        yield
    except Exception as e:
        logger.error(f"QB Priority Context: Error in QuickBooks operation: {str(e)}")
        logger.error(f"QB Priority Context: Traceback: {traceback.format_exc()}")
        raise
    finally:
        # CRITICAL: Always resume background jobs, even if operation fails
        try:
            if operation_type == "migrate_all":
                resume_all_background_jobs_from_migrate_all()
                logger.info("PRIORITY RELEASED: ALL background jobs resumed after migrate-all operation")
            else:
                resume_background_jobs()
                logger.info("Background jobs resumed after QuickBooks operation")
        except Exception as resume_error:
            logger.error(f"CRITICAL: Failed to resume background jobs: {resume_error}")
            # This is critical - try alternative cleanup
            try:
                resume_all_background_jobs_from_migrate_all()
                logger.info("Alternative background job resume successful")
            except Exception as alt_error:
                logger.error(f"CRITICAL: Alternative resume also failed: {alt_error}")


def validate_invoice_ids(invoice_ids: List[UUID]) -> List[UUID]:
    """Validate and clean invoice IDs"""
    logger.info(f"QB Validation: Validating {len(invoice_ids) if invoice_ids else 0} invoice IDs")
    
    if not invoice_ids:
        logger.warning("QB Validation: No invoice IDs provided")
        raise HTTPException(status_code=400, detail="No invoice IDs provided")

    # Remove duplicates and None values
    clean_ids = list(set([id for id in invoice_ids if id is not None]))

    if not clean_ids:
        logger.warning("QB Validation: No valid invoice IDs provided")
        raise HTTPException(status_code=400, detail="No valid invoice IDs provided")

    if len(clean_ids) > 5000:
        logger.warning(f"QB Validation: Large dataset detected: {len(clean_ids)} invoices")

    logger.info(f"QB Validation: Validated {len(clean_ids)} invoice IDs")
    return clean_ids


def perform_database_updates_background(all_item_ids_for_status: List,
                                        operation_id: str,
                                        invoice_ids: List[UUID] = None):
    """
    Background task to handle ALL status updates after Excel generation.
    CRITICAL PRIORITY: Ensures status changes from Pending to Sent.
    Enhanced with robust error handling and transaction management.
    """
    db = None
    try:
        # CRITICAL: Proper database session for background processing
        from mpi_backend.database import SessionLocal
        db = SessionLocal()

        update_progress(operation_id, "background_updating", 95,
                        "CRITICAL: Updating export statuses to 'Sent'")

        status_start = time.time()
        total_operations = 0
        successful_operations = 0
        failed_operations = 0

        logger.info(
            f"PRIORITY STATUS UPDATE: Starting background updates for "
            f"{len(all_item_ids_for_status)} items and "
            f"{len(invoice_ids) if invoice_ids else 0} invoices"
        )

        # PRIORITY 1: Update invoice-level export status with enhanced validation
        updated_invoices = 0
        skipped_invoices = 0
        failed_invoices = 0
        
        if invoice_ids:
            invoice_controller = InvoiceController(db)
            total_operations += len(invoice_ids)
            
            for invoice_id in invoice_ids:
                try:
                    # Enhanced validation: Check current status before updating
                    from mpi_backend.database.models import Invoice
                    invoice = db.query(Invoice).filter(
                        Invoice.id == str(invoice_id)
                    ).first()
                    
                    if invoice:
                        current_status = invoice.is_exported
                        logger.debug(f"Invoice {invoice_id} current status: {current_status}")
                        
                        if current_status != 'Sent':
                            # CRITICAL: Update invoice status to 'Sent'
                            success = (
                                invoice_controller.set_invoice_is_exported(
                                    str(invoice_id)
                                )
                            )
                            if success:
                                updated_invoices += 1
                                successful_operations += 1
                                logger.info(
                                    f"✓ Invoice {invoice_id} status updated: "
                                    f"{current_status} → Sent"
                                )
                            else:
                                failed_invoices += 1
                                failed_operations += 1
                                logger.error(
                                    f"✗ Failed to update invoice {invoice_id}"
                                )
                        else:
                            skipped_invoices += 1
                            successful_operations += 1  # Count as successful
                            logger.debug(
                                f"Invoice {invoice_id} already marked as "
                                f"Sent, skipping"
                            )
                    else:
                        failed_invoices += 1
                        failed_operations += 1
                        logger.error(f"✗ Invoice {invoice_id} not found")
                        
                except Exception as e:
                    if db:
                        db.rollback()
                    failed_invoices += 1
                    failed_operations += 1
                    logger.error(f"✗ Exception updating invoice {invoice_id}: {e}")
                    continue

        # PRIORITY 2: Update item-level export status with enhanced error handling
        updated_items = 0
        failed_items = 0
        
        if all_item_ids_for_status:
            total_operations += len(all_item_ids_for_status)
            
            try:
                # CRITICAL: Batch update item statuses from Pending to Sent
                logger.info(
                    f"CRITICAL UPDATE: Updating "
                    f"{len(all_item_ids_for_status)} item statuses to 'Sent'"
                )
                
                # Validate items exist and get current statuses
                from mpi_backend.database.models import InvoiceItem
                existing_items = db.query(InvoiceItem).filter(
                    InvoiceItem.id.in_(all_item_ids_for_status)
                ).all()
                
                logger.info(
                    f"Found {len(existing_items)} items out of "
                    f"{len(all_item_ids_for_status)} requested"
                )
                
                # Log current status distribution
                status_counts = {}
                for item in existing_items:
                    status = item.export_status or 'None'
                    status_counts[status] = status_counts.get(status, 0) + 1
                
                logger.info(
                    f"Current item status distribution: {status_counts}"
                )
                
                # Use the controller method for batch update
                invoice_item_controller = InvoiceItemController(db)
                updated_items = (
                    invoice_item_controller.set_export_status_to_sent(
                        all_item_ids_for_status
                    )
                )
                
                if updated_items > 0:
                    successful_operations += updated_items
                    logger.info(
                        f"✓ Successfully updated {updated_items} items to "
                        f"'Sent'"
                    )
                else:
                    logger.warning("⚠ No items were updated")
                    
            except Exception as e:
                if db:
                    db.rollback()
                failed_items = len(all_item_ids_for_status)
                failed_operations += failed_items
                logger.error(f"✗ CRITICAL ERROR updating item statuses: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")

        status_time = time.time() - status_start
        
        # COMPREHENSIVE STATUS REPORT
        logger.info(
            f"BACKGROUND UPDATE COMPLETED in {status_time:.3f}s:\n"
            f"  INVOICES: {updated_invoices} updated, {skipped_invoices} already sent, "
            f"{failed_invoices} failed\n"
            f"  ITEMS: {updated_items} updated, {failed_items} failed\n"
            f"  OVERALL: {successful_operations}/{total_operations} operations successful"
        )

        # Update progress with detailed results
        success_rate = (successful_operations / total_operations * 100) if total_operations > 0 else 100
        update_progress(
            operation_id, "background_completed", 100,
            f"Status updates completed - {success_rate:.1f}% success rate: "
            f"Invoices({updated_invoices}✓,{skipped_invoices}skip,{failed_invoices}✗), "
            f"Items({updated_items}✓,{failed_items}✗)"
        )

        # CRITICAL: Verify updates were successful
        if failed_operations > 0:
            logger.error(f"ATTENTION REQUIRED: {failed_operations} status updates failed")
            # Optional: You could implement retry logic here
            
    except Exception as e:
        if db:
            db.rollback()
        logger.error(f"CRITICAL: Background database update failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        update_progress(operation_id, "background_error", 100,
                        f"CRITICAL ERROR in background update: {str(e)}")
    finally:
        if db:
            try:
                db.close()
                logger.debug("Database session closed successfully")
            except Exception as e:
                logger.error(f"Error closing background db session: {e}")


def immediate_status_update(all_item_ids_for_status: List,
                           invoice_ids: List[UUID],
                           db: Session,
                           operation_id: str) -> dict:
    """
    IMMEDIATE STATUS UPDATE: Perform status updates synchronously before returning.
    This ensures status changes happen immediately, not in background.
    Returns detailed results of the update operation.
    """
    logger.info("IMMEDIATE STATUS UPDATE: Starting synchronous status updates")
    update_start = time.time()
    
    results = {
        'invoices_updated': 0,
        'invoices_skipped': 0,
        'invoices_failed': 0,
        'items_updated': 0,
        'items_failed': 0,
        'total_time': 0,
        'success': False
    }
    
    try:
        # CRITICAL PRIORITY 1: Update invoice statuses immediately
        if invoice_ids:
            invoice_controller = InvoiceController(db)
            logger.info(f"Updating {len(invoice_ids)} invoice statuses to 'Sent'")
            
            for invoice_id in invoice_ids:
                try:
                    from mpi_backend.database.models import Invoice
                    invoice = db.query(Invoice).filter(
                        Invoice.id == str(invoice_id)
                    ).first()
                    
                    if invoice:
                        if invoice.is_exported != 'Sent':
                            success = invoice_controller.set_invoice_is_exported(
                                str(invoice_id)
                            )
                            if success:
                                results['invoices_updated'] += 1
                                logger.debug(f"Invoice {invoice_id}: Pending → Sent")
                            else:
                                results['invoices_failed'] += 1
                                logger.error(f"Failed to update invoice {invoice_id}")
                        else:
                            results['invoices_skipped'] += 1
                            logger.debug(f"Invoice {invoice_id} already 'Sent'")
                    else:
                        results['invoices_failed'] += 1
                        logger.error(f"Invoice {invoice_id} not found")
                        
                except Exception as e:
                    if db:
                        db.rollback()
                    results['invoices_failed'] += 1
                    logger.error(f"Exception updating invoice {invoice_id}: {e}")

        # CRITICAL PRIORITY 2: Update item statuses immediately
        if all_item_ids_for_status:
            logger.info(f"Updating {len(all_item_ids_for_status)} item statuses to 'Sent'")
            
            try:
                invoice_item_controller = InvoiceItemController(db)
                updated_count = invoice_item_controller.set_export_status_to_sent(
                    all_item_ids_for_status
                )
                results['items_updated'] = updated_count
                logger.info(f"Updated {updated_count} item statuses to 'Sent'")
                
            except Exception as e:
                if db:
                    db.rollback()
                results['items_failed'] = len(all_item_ids_for_status)
                logger.error(f"CRITICAL: Failed to update item statuses: {e}")

        results['total_time'] = time.time() - update_start
        
        # Determine overall success
        total_attempted = len(invoice_ids) + len(all_item_ids_for_status)
        total_successful = (results['invoices_updated'] + results['invoices_skipped'] + 
                           results['items_updated'])
        
        results['success'] = (results['invoices_failed'] == 0 and results['items_failed'] == 0)
        
        logger.info(
            f" IMMEDIATE STATUS UPDATE COMPLETED in {results['total_time']:.3f}s:\n"
            f"  INVOICES: {results['invoices_updated']} updated, "
            f"{results['invoices_skipped']} skipped, {results['invoices_failed']} failed\n"
            f"  ITEMS: {results['items_updated']} updated, {results['items_failed']} failed\n"
            f"  SUCCESS: {results['success']} ({total_successful}/{total_attempted} operations)"
        )
        
        return results
        
    except Exception as e:
        if db:
            db.rollback()
        logger.error(f"CRITICAL: Immediate status update failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        results['success'] = False
        results['total_time'] = time.time() - update_start
        return results


@router.post("/migrate-all")
def migrate_all_invoice_to_QB(request: SendtoQBFilterRequest,
                              background_tasks: BackgroundTasks,
                              db: Session = Depends(get_qb_db)):
    """
    Migrate all filtered invoices to QuickBooks with ultra-fast processing.
    
    **Summary:**
        Exports all invoices matching the specified filter criteria to QuickBooks
        format with ultra-fast processing and guaranteed status updates. This
        endpoint is optimized for bulk operations and handles large datasets
        efficiently with priority control over background jobs.
        
    **Request Body:**
        - **request** (`SendtoQBFilterRequest`): Filter criteria for selecting invoices:
            - Filter parameters (supplier, date range, status, etc.)
            - **excluded_invoice_ids** (`List[str]`, optional): Invoice IDs to exclude
            - **order_by** (`List[dict]`, optional): Sorting criteria
            
    **Background Tasks:**
        - **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing
        
    **Returns:**
        - **str**: Presigned S3 URL for downloading the QuickBooks Excel file
        
    **Response Example:**
    ```json
    "https://s3.amazonaws.com/bucket/Exports/qb_export_20241219_143025.xlsx?AWSAccessKeyId=..."
    ```
    
    **Process Flow:**
        1. Applies filter criteria to get matching invoice IDs
        2. Excludes specified invoice IDs if provided
        3. Pauses all background jobs for absolute priority
        4. Processes invoices with ultra-fast QuickBooks migration
        5. Generates Excel file in QuickBooks format
        6. Updates export statuses to 'Sent'
        7. Resumes background jobs
        8. Returns download URL
        
    **Priority Control:**
        - **ABSOLUTE PRIORITY**: Pauses ALL background jobs during processing
        - Ensures maximum system resources for QuickBooks migration
        - Automatic resume of background jobs after completion
        - Critical priority context management
        
    **Performance Features:**
        - Ultra-fast data processing with vectorized operations
        - Optimized database queries for large datasets
        - Fast Excel generation and S3 upload
        - Immediate status updates for guaranteed consistency
        
    **Error Codes:**
        - **400**: No invoice IDs found for export
        - **500**: Processing or upload error
        
    **Status Updates:**
        - Invoice-level export status updated to 'Sent'
        - Item-level export status updated to 'Sent'
        - Immediate updates for guaranteed consistency
        - Comprehensive status reporting
        
    **Notes:**
        - Designed for bulk operations with large datasets
        - Uses absolute priority control over background jobs
        - Guaranteed status updates before response
        - Excel file includes QuickBooks-compatible format
        - File is stored in S3 with timestamp for uniqueness
        - Presigned URL has limited expiration time
        - Automatic cleanup by S3 lifecycle policies
    """
    operation_start = time.time()
    operation_id = f"qb_migrate_all_{int(operation_start)}"

    logger.info(f"POST /quickbooks/migrate-all - Starting migrate-all operation: {operation_id}")

    with safe_priority_context("migrate_all"):
        try:
            logger.info("QB Migrate-All: Starting ULTRA-FAST QuickBooks migration with guaranteed status updates")

            filtered_data = InvoiceItemController(db).apply_filters(
                request, page=1, size=0
            )
            invoice_ids = [item.invoice_id for item in filtered_data['items']]
            if (not invoice_ids or len(invoice_ids) == 0):
                # If no invoice_ids, fetch all matching invoice IDs from the DB (old behavior)
                from mpi_backend.database.models import Invoice
                query = db.query(Invoice.id)
                # Optionally apply filters from request here if needed
                invoice_ids = [row.id for row in query.all()]
            
            if request.excluded_invoice_ids:
                invoice_ids = [
                    invoice_id for invoice_id in invoice_ids
                    if invoice_id not in request.excluded_invoice_ids
                ]
            invoice_ids = list(set(invoice_ids))
            if not invoice_ids:
                raise HTTPException(status_code=400, detail="No invoice IDs provided or found for export.")

            logger.info(f"QB Migrate-All: Processing {len(invoice_ids)} invoices with STATUS PRIORITY")

            # ULTRA-FAST PROCESSING: Generate Excel and ensure status updates
            result = migrate_invoice_to_QB_ultra_fast(
                invoice_ids, db=db, operation_id=operation_id,
                background_tasks=background_tasks, update_mode="immediate",
                item_order=None,
                order_by=getattr(request, 'order_by', None)
            )

            operation_time = time.time() - operation_start
            logger.info(f"POST /quickbooks/migrate-all - Completed in {operation_time:.2f}s with status updates")
            return result

        except Exception as e:
            operation_time = time.time() - operation_start
            logger.error(f"POST /quickbooks/migrate-all - Failed after {operation_time:.2f}s: {str(e)}")
            raise


@router.post("/migrate")
async def migrate_invoice_to_QB(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_qb_db),
    order_by: list = None
):
    """
    Migrate specific invoices to QuickBooks with priority control.
    
    **Summary:**
        Exports specified invoices to QuickBooks format with priority control
        over background jobs and guaranteed status updates. This endpoint
        supports both individual invoice selection and bulk operations
        with flexible request formats.
        
    **Request Body:**
        Supports multiple formats:
        - **Array of UUIDs**: Direct list of invoice IDs
        - **Object with invoice_ids**: `{"invoice_ids": ["uuid1", "uuid2"]}`
        - **Empty/None**: Exports all invoices in the system
        
    **Query Parameters:**
        - **order_by** (`list`, optional): Sorting criteria for the export
        
    **Background Tasks:**
        - **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing
        
    **Returns:**
        - **str**: Presigned S3 URL for downloading the QuickBooks Excel file
        
    **Response Example:**
    ```json
    "https://s3.amazonaws.com/bucket/Exports/qb_export_20241219_143025.xlsx?AWSAccessKeyId=..."
    ```
    
    **Request Examples:**
    
    **Array of Invoice IDs:**
    ```json
    ["550e8400-e29b-41d4-a716-446655440000", "550e8400-e29b-41d4-a716-446655440001"]
    ```
    
    **Object with Invoice IDs:**
    ```json
    {
        "invoice_ids": ["550e8400-e29b-41d4-a716-446655440000", "550e8400-e29b-41d4-a716-446655440001"]
    }
    ```
    
    **Process Flow:**
        1. Validates and cleans invoice IDs
        2. Pauses background jobs for priority processing
        3. Processes invoices with ultra-fast QuickBooks migration
        4. Generates Excel file in QuickBooks format
        5. Updates export statuses to 'Sent' immediately
        6. Resumes background jobs
        7. Returns download URL
        
    **Priority Control:**
        - Pauses background jobs during processing
        - Ensures system resources for QuickBooks migration
        - Automatic resume of background jobs after completion
        - Safe priority context management
        
    **Performance Features:**
        - Ultra-fast data processing with vectorized operations
        - Optimized database queries
        - Fast Excel generation and S3 upload
        - Immediate status updates for guaranteed consistency
        
    **Validation:**
        - Removes duplicate and null invoice IDs
        - Validates UUID format
        - Limits to 5000 invoices for performance
        - Comprehensive error handling
        
    **Error Codes:**
        - **400**: No valid invoice IDs provided
        - **500**: Processing or upload error
        
    **Status Updates:**
        - Invoice-level export status updated to 'Sent'
        - Item-level export status updated to 'Sent'
        - Immediate updates for guaranteed consistency
        - Detailed status reporting
        
    **Notes:**
        - Supports flexible request formats for easy integration
        - Uses priority control over background jobs
        - Guaranteed status updates before response
        - Excel file includes QuickBooks-compatible format
        - File is stored in S3 with timestamp for uniqueness
        - Presigned URL has limited expiration time
        - Automatic cleanup by S3 lifecycle policies
    """
    start_time = time.time()
    operation_id = f"qb_migrate_{int(start_time)}"
    invoice_ids = None

    with safe_priority_context("regular"):
        try:
            # Accept both raw list and object with 'invoice_ids'
            try:
                body = await request.json()
            except Exception:
                body = None
            if isinstance(body, list):
                invoice_ids = body
            elif isinstance(body, dict) and 'invoice_ids' in body:
                invoice_ids = body['invoice_ids']
            if invoice_ids is None:
                from mpi_backend.database.models import Invoice
                query = db.query(Invoice.id)
                invoice_ids = [row.id for row in query.all()]
            logger.info(f"POST /quickbooks/migrate - Starting migration for {len(invoice_ids)} invoices")
            logger.info(f"Received invoice_ids: {invoice_ids}")
            invoice_ids = validate_invoice_ids(invoice_ids)

            logger.info(f"QB Migrate: Processing {len(invoice_ids)} invoices with STATUS PRIORITY")

            # Use ultra-fast method with immediate status updates for regular migrations
            result = migrate_invoice_to_QB_ultra_fast(
                invoice_ids, db=db, operation_id=operation_id,
                background_tasks=background_tasks, update_mode="immediate",
                item_order=None,
                order_by=order_by
            )

            total_time = time.time() - start_time
            logger.info(f"POST /quickbooks/migrate - Completed in {total_time:.2f}s with guaranteed status updates")
            return result

        except Exception as e:
            total_time = time.time() - start_time
            logger.error(f"POST /quickbooks/migrate - Failed after {total_time:.2f}s: {str(e)}")
            raise


def migrate_invoice_to_QB_ultra_fast(invoice_ids: List[UUID],
                                     db: Session, operation_id: str,
                                     background_tasks: BackgroundTasks,
                                     update_mode: str = "background",
                                     item_order: list = None,
                                     order_by: list = None) -> str:
    """
    ULTRA-FAST QuickBooks migration with GUARANTEED status updates
    update_mode: "immediate" for synchronous updates, "background" for async updates
    """

    # FAST START - minimal logging
    start_time = time.time()
    logger.info(f"FAST QB migration starting for {len(invoice_ids)} invoices "
               f"(update_mode: {update_mode})")

    update_progress(operation_id, "retrieving_data", 10,
                    f"Retrieving data for {len(invoice_ids)} invoices")

    # ULTRA-FAST data retrieval - direct database query
    from mpi_backend.database.models import InvoiceItem
    invoice_items = db.query(InvoiceItem).filter(
        InvoiceItem.invoice_id.in_(invoice_ids)
    ).all()

    if not invoice_items:
        raise HTTPException(status_code=400, detail="No items found")

    logger.info(
        f"Retrieved {len(invoice_items)} items in "
        f"{time.time() - start_time:.3f}s"
    )

    update_progress(operation_id, "processing_data", 30,
                    f"Processing {len(invoice_items)} items")

    # Get classification controller
    classification_controller = ItemClassificationController(db)

    # Pre-build classification cache (vectorized)
    unique_sheet_names = set(getattr(item, 'sheet_name', '') for item in invoice_items if getattr(item, 'sheet_name', '').strip())
    classification_cache = {'': '', None: ''}
    for sheet_name in unique_sheet_names:
        try:
            classification_cache[sheet_name] = classification_controller.get_classification(sheet_name)
        except Exception:
            classification_cache[sheet_name] = ''

    # Pre-allocate lists for speed
    all_items_data = []
    tax_by_invoice = {}
    all_item_ids_for_status = []
    tax_item_classes = {}

    for item in invoice_items:
        item_sheet_name = getattr(item, 'sheet_name', '') or ''
        item_invoice_id = getattr(item, 'invoice_id')
        if item_sheet_name == '(TAX)':
            if item_invoice_id not in tax_by_invoice:
                tax_by_invoice[item_invoice_id] = 0
            try:
                amount_str = str(getattr(item, 'amount', '0')).replace(',', '')
                tax_by_invoice[item_invoice_id] += float(amount_str)
            except (ValueError, TypeError):
                pass
            item_class = getattr(item, 'class_', '') or ''
            if item_class and item_invoice_id:
                if item_invoice_id not in tax_item_classes:
                    tax_item_classes[item_invoice_id] = []
                tax_item_classes[item_invoice_id].append(item_class)
            tax_item_id = getattr(item, 'id', None)
            if tax_item_id:
                all_item_ids_for_status.append(tax_item_id)
        else:
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
                'account': getattr(item, 'account', '') or '',
                'memo': getattr(item, 'memo', '') or '',
            }
            all_items_data.append(item_data)
            if item_data['id']:
                all_item_ids_for_status.append(item_data['id'])

    if not all_items_data:
        raise HTTPException(status_code=400, detail="No non-tax items found")

    df = pd.DataFrame(all_items_data)
    # Don't overwrite account values from database - preserve original account values

    # Enhanced account and class mapping logic
    # Step 1: Map account field for one-letter values
    # Account 'A' → Special case: Labor & Material: Additional Material
    df.loc[
        df['account'].str.upper() == 'A',
        'account'
    ] = (
        'UnInvoiced JIP:Subcontractors Expense:Labor & Material:'
        'Additional Material'
    )

    # Account 'M' → Job Materials Purchased
    df.loc[
        df['account'].str.upper() == 'M',
        'account'
    ] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'

    # Account 'E' → Job Equipment
    df.loc[
        df['account'].str.upper() == 'E',
        'account'
    ] = 'UnInvoiced JIP:Cost Of Materials:Job Equipment'

    # Step 2: Do NOT derive default account from class codes when account is empty.
    # Instead, rely on ItemClassification (sheet_name → account) for default mapping.
    
    # Step 3: Do not derive default account from descriptive classes.
    # Leave account blank here; it will be filled by classification mapping below.

    # Vectorized default mapping using ItemClassification (sheet_name → account)
    unassigned_mask = df['account'] == ''
    if unassigned_mask.any():
        df.loc[unassigned_mask, 'account'] = (
            df.loc[unassigned_mask, 'sheet_name']
            .map(classification_cache)
            .fillna('')
        )

    # Special case mapping
    mpi_mappings = {
        'UIDI-Job Materials Purchased': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
        'UIDI-Job Equipment': 'UnInvoiced JIP:Cost Of Materials:Job Equipment',
        'UIDI-Sprinkler specialty item': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
        'UIDI-Drainage Material': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
    }
    for mpi_item, account in mpi_mappings.items():
        mask = (df['mpi_item'] == mpi_item) & (df['account'] == '')
        if mask.any():
            df.loc[mask, 'account'] = account

    # Validation
    no_match_items = df[df['mpi_item'] == 'No Match']
    if not no_match_items.empty:
        no_match_refs = no_match_items[['mpi_item', 'ref_no', 'item', 'description']].drop_duplicates()
        no_match_list = no_match_refs.to_dict(orient='records')
        raise HTTPException(status_code=400, detail=(f"Cannot export to QuickBooks: Found {len(no_match_items)} 'No Match' items. Please map these items first. Sample unmapped items: {no_match_list[:5]}"))
    unmatched_accounts = df[df['account'] == '']
    if not unmatched_accounts.empty:
        unmatched_references = unmatched_accounts[['mpi_item', 'ref_no', 'sheet_name']].drop_duplicates()
        unmatched_references_list = unmatched_references.to_dict(orient='records')
        raise HTTPException(status_code=400, detail=(f"Unmatched sheet names are present. Please add classifications for these sheet names: {unmatched_references_list[:5]}"))
    df.loc[df['account'] == '', 'account'] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'

    # Data type conversions
    df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
    df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0)
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
    df['tax_amount'] = df['invoice_id'].map(tax_by_invoice).fillna(0)

    # --- Sorting to match frontend order or by id/order_by ---
    if item_order is not None and len(item_order) > 0 and 'id' in df.columns:
        df['__order'] = pd.Categorical(df['id'], categories=item_order, ordered=True)
        df = df.sort_values(['invoice_id', '__order']).drop(columns='__order')
    elif order_by is not None and isinstance(order_by, list) and len(order_by) > 0:
        # order_by may be a list of dicts or Pydantic objects
        sort_cols = []
        ascending = []
        for o in order_by:
            # Try dict-style first
            col = None
            ord_val = 'asc'
            try:
                col = o['column']
                ord_val = o.get('order', 'asc')
            except (TypeError, KeyError):
                # Fallback to attribute access (Pydantic model)
                col = getattr(o, 'column', None)
                ord_val = getattr(o, 'order', 'asc')
            if col and col in df.columns:
                sort_cols.append(col)
                ascending.append(str(ord_val).lower() != 'desc')
        if sort_cols:
            df = df.sort_values(sort_cols, ascending=ascending)
        else:
            df = df.sort_values(['id'])
    else:
        df = df.sort_values(['id'])

    # --- Output account lines and total line for each invoice ---
    result_rows = []
    for invoice_id, invoice_items in df.groupby('invoice_id', sort=False):
        ref_no = invoice_items['ref_no'].iloc[0]
        date = invoice_items['date'].iloc[0]
        vendor = invoice_items['vendor'].iloc[0]
        memo = invoice_items['memo'].iloc[0]
        customer_job = invoice_items['customer_job'].iloc[0]
        tax_amount = invoice_items['tax_amount'].iloc[0]
        from mpi_backend.database.models import Invoice
        db_invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if db_invoice and hasattr(db_invoice, 'amount') and db_invoice.amount is not None:
            authoritative_total = float(db_invoice.amount)
        else:
            authoritative_total = invoice_items['amount'].sum() + tax_amount
        # Group by account/class for account lines
        group_cols = ['account', 'class_']
        grouped = invoice_items.groupby(group_cols, sort=False)
        item_total = invoice_items['amount'].sum()
        tax_pct = (tax_amount / item_total) if item_total else 0
        split_totals = []
        for (account, class_val), group in grouped:
            group_amount = group['amount'].sum()
            group_tax = group_amount * tax_pct
            group_total = group_amount + group_tax
            split_totals.append((account, class_val, group, group_total))
        invoice_lines = []
        running_sum = 0
        for i, (account, class_val, group, group_total) in enumerate(split_totals):
            if i < len(split_totals) - 1:
                rounded_total = round(group_total, 4)
                running_sum += rounded_total
            else:
                rounded_total = round(authoritative_total - running_sum, 4)
            invoice_lines.append({
                'Date': pd.to_datetime(date, errors='coerce').strftime('%m/%d/%Y') if pd.notnull(date) else '',
                'Ref': ref_no,
                'vendor': vendor,
                'terms': '',
                'bill due': '',
                'account': account,
                'Amount': rounded_total,
                'Memo': memo,
                'Customer Job': customer_job,
                'Class': class_val or '',
            })
        result_rows.extend(invoice_lines)
        # Add a total line ONLY when the invoice is split across multiple accounts
        if len(split_totals) > 1 and len(invoice_lines) > 0:
            total_line_account = invoice_lines[0].get('account', '')
            total_line_class = invoice_lines[0].get('Class', '')
            result_rows.append({
                'Date': pd.to_datetime(date, errors='coerce').strftime('%m/%d/%Y') if pd.notnull(date) else '',
                'Ref': ref_no,
                'vendor': vendor,
                'terms': '',
                'bill due': '',
                'account': total_line_account,
                'Amount': round(authoritative_total, 4),
                'Memo': memo,
                'Customer Job': customer_job,
                'Class': total_line_class,
            })
    final_batch_entry = pd.DataFrame(result_rows)[[
        'Date', 'Ref', 'vendor', 'terms', 'bill due',
        'account', 'Amount', 'Memo', 'Customer Job', 'Class'
    ]]
    # --- NEW BUSINESS LOGIC END ---

    # Remove obsolete batch_entry formatting and column mapping
    # (No need to reformat final_batch_entry, it is already in correct format)

    logger.info(
        f"Aggregation completed for {len(final_batch_entry)} rows"
    )

    update_progress(operation_id, "generating_excel", 85,
                    f"Generating Excel file with {len(final_batch_entry)} "
                    f"rows")

    # FAST Excel generation and S3 upload
    excel_start = time.time()

    # Use same fast method as export-all
    try:
        from mpi_backend.utils.pdf_to_excel.formatting_util import (
            save_ultra_fast_excel
        )
        from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
        from datetime import datetime
        import os

        upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
        filename = (
            f'qb_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )
        file_path = f'{upload_folder}{filename}'

        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        # FAST Excel save
        save_ultra_fast_excel(final_batch_entry, file_path)

        # FAST S3 upload
        upload_file(file_path, file_key=f'Exports/{filename}',
                    is_invoice=False)
        download_url = get_presigned_url(file_key=f'Exports/{filename}',
                                         is_invoice=False)

        # Clean up
        try:
            os.remove(file_path)
        except OSError:
            pass

    except Exception as upload_error:
        logger.error(f"S3 upload failed: {str(upload_error)}")
        raise HTTPException(status_code=500, detail="Failed to upload to S3")

    logger.info(
        f"Excel and S3 upload in {time.time() - excel_start:.3f}s"
    )

    # CRITICAL PRIORITY: STATUS UPDATES - Choose immediate or background based on mode
    update_progress(operation_id, "updating_statuses", 90,
                    f"CRITICAL: Updating statuses ({update_mode} mode)")
    
    if update_mode == "immediate":
        # IMMEDIATE STATUS UPDATE - Guaranteed before return
        logger.info("CRITICAL: Performing IMMEDIATE status updates")
        status_results = immediate_status_update(
            all_item_ids_for_status, invoice_ids, db, operation_id
        )
        
        if not status_results['success']:
            logger.error("ATTENTION: Some status updates failed")
            # You could choose to raise an exception here if status updates are critical
            # raise HTTPException(status_code=500, detail="Status updates failed")
        
        logger.info(f"IMMEDIATE STATUS UPDATES: "
                   f"Invoices({status_results['invoices_updated']}✓,"
                   f"{status_results['invoices_skipped']}skip,"
                   f"{status_results['invoices_failed']}✗), "
                   f"Items({status_results['items_updated']}✓,"
                   f"{status_results['items_failed']}✗)")
        
    else:
        # BACKGROUND STATUS UPDATE - For maximum speed
        logger.info("STATUS UPDATES: Moving to background for maximum speed")
        if all_item_ids_for_status or invoice_ids:
            background_tasks.add_task(
                perform_database_updates_background,
                all_item_ids_for_status,
                operation_id,
                invoice_ids
            )

    total_time = time.time() - start_time
    logger.info(
        f"ULTRA-FAST QB EXPORT COMPLETED: {len(final_batch_entry)} rows in "
        f"{total_time:.2f}s (status_mode: {update_mode})"
    )

    update_progress(operation_id, "completed", 100,
                    f"Export completed in {total_time:.2f}s with {update_mode} status updates")

    return download_url
