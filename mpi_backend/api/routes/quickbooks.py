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
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
from mpi_backend.utils.quickbooks_priority import (
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
    logger.info(f"QB Progress [{operation_id}]: {stage} - {progress}% - "
                f"{message}")


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
                logger.info(
                    "Background jobs resumed after QuickBooks operation"
                )
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
                                        operation_id: str,
                                        invoice_ids: List[UUID] = None):
    """
    Background task to handle ALL status updates after Excel generation.
    This ensures maximum speed by returning download URL immediately.
    """
    db = None
    try:
        # CRITICAL FIX: Proper database session for background processing
        from mpi_backend.database import SessionLocal
        db = SessionLocal()

        update_progress(operation_id, "background_updating", 95,
                        "Updating statuses in background")

        status_start = time.time()

        # CRITICAL FIX: Update invoice statuses with proper validation
        updated_invoices = 0
        skipped_invoices = 0
        if invoice_ids:
            invoice_controller = InvoiceController(db)
            for invoice_id in invoice_ids:
                try:
                    # Check current status before updating
                    from mpi_backend.database.models import Invoice
                    invoice = db.query(Invoice).filter(
                        Invoice.id == str(invoice_id)
                    ).first()
                    if invoice:
                        if invoice.is_exported != 'Sent':
                            success = (
                                invoice_controller.set_invoice_is_exported(
                                    str(invoice_id)
                                )
                            )
                            if success:
                                updated_invoices += 1
                        else:
                            skipped_invoices += 1
                            logger.debug(
                                f"Invoice {invoice_id} already marked as "
                                f"Sent, skipping"
                            )
                except Exception as e:
                    logger.warning(
                        f"Failed to update invoice {invoice_id}: {e}"
                    )
                    continue

        # Update item-level export status in background
        if all_item_ids_for_status:
            InvoiceItemController(db).set_export_status_to_sent(
                all_item_ids_for_status)

        status_time = time.time() - status_start
        logger.info(
            f"Background updates completed in {status_time:.3f}s: "
            f"{updated_invoices} invoices updated, {skipped_invoices} "
            f"already sent, {len(all_item_ids_for_status)} items"
        )

        update_progress(
            operation_id, "background_completed", 100,
            f"Background updates completed - {updated_invoices} invoices "
            f"updated, {skipped_invoices} already sent, "
            f"{len(all_item_ids_for_status)} items"
        )

    except Exception as e:
        logger.error(f"Background database update failed: {e}")
        update_progress(operation_id, "background_error", 100,
                        f"Background update error: {str(e)}")
    finally:
        if db:
            try:
                db.close()
            except Exception as e:
                logger.error(f"Error closing background db session: {e}")


@router.post("/migrate-all")
def migrate_all_invoice_to_QB(request: SendtoQBFilterRequest,
                              background_tasks: BackgroundTasks,
                              db: Session = Depends(get_qb_db)):
    """ULTRA-FAST: QuickBooks migration optimized for all invoices"""
    operation_start = time.time()
    operation_id = f"qb_migrate_all_{int(operation_start)}"

    with safe_priority_context("migrate_all"):
        try:
            logger.info("Starting ULTRA-FAST QuickBooks migration")

            filtered_data = InvoiceItemController(db).apply_filters(
                request, page=1, size=0
            )
            # ULTRA-FAST filtering - get just IDs like export-all does
            invoice_ids = [item.invoice_id for item in filtered_data['items']]

            if request.excluded_invoice_ids:
                # un selected items from frontend
                invoice_ids = [
                    invoice_id for invoice_id in invoice_ids
                    if invoice_id not in request.excluded_invoice_ids
                ]

            # make invoice-ids in list to be unique
            invoice_ids = list(set(invoice_ids))

            logger.info(f"Migrate-all processing {len(invoice_ids)} invoices")

            # ULTRA-FAST PROCESSING: Generate Excel and return immediately
            result = migrate_invoice_to_QB_ultra_fast(
                invoice_ids, db=db, operation_id=operation_id,
                background_tasks=background_tasks
            )

            operation_time = time.time() - operation_start
            logger.info(
                f"Migrate-all completed ULTRA-FAST in {operation_time:.2f}s"
            )
            return result

        except Exception as e:
            operation_time = time.time() - operation_start
            logger.error(
                f"QuickBooks migrate-all failed after {operation_time:.2f}s: "
                f"{str(e)}"
            )
            raise


@router.post("/migrate")
def migrate_invoice_to_QB(invoice_ids: List[UUID],
                          background_tasks: BackgroundTasks,
                          db: Session = Depends(get_qb_db)):
    """QuickBooks migration with priority control using ultra-fast approach"""
    start_time = time.time()
    operation_id = f"qb_migrate_{int(start_time)}"

    with safe_priority_context("regular"):
        try:
            # Validate input
            invoice_ids = validate_invoice_ids(invoice_ids)

            logger.info(f"Processing {len(invoice_ids)} invoices")

            # Use the same ultra-fast method for all migrations
            result = migrate_invoice_to_QB_ultra_fast(
                invoice_ids, db=db, operation_id=operation_id,
                background_tasks=background_tasks
            )

            total_time = time.time() - start_time
            logger.info(
                f"QuickBooks migration completed successfully in "
                f"{total_time:.2f}s"
            )
            return result

        except Exception as e:
            total_time = time.time() - start_time
            logger.error(
                f"QuickBooks migration failed after {total_time:.2f}s: "
                f"{str(e)}"
            )
            raise


def migrate_invoice_to_QB_ultra_fast(invoice_ids: List[UUID],
                                     db: Session, operation_id: str,
                                     background_tasks: BackgroundTasks) -> str:
    """
    ULTRA-FAST QuickBooks migration - consolidated single approach
    """

    # FAST START - minimal logging
    start_time = time.time()
    logger.info(f"FAST QB migration starting for {len(invoice_ids)} invoices")

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

    # Pre-build classification cache
    unique_sheet_names = set()
    for item in invoice_items:
        sheet_name = getattr(item, 'sheet_name', '')
        if sheet_name and sheet_name.strip():
            unique_sheet_names.add(sheet_name)

    # Build classification cache using the same logic
    classification_cache = {'': '', None: ''}
    for sheet_name in unique_sheet_names:
        try:
            classification_cache[sheet_name] = (
                classification_controller.get_classification(sheet_name)
            )
        except Exception:
            classification_cache[sheet_name] = ''

    # ULTRA-FAST single-pass data processing
    process_start = time.time()

    # Pre-allocate lists for speed
    all_items_data = []
    tax_by_invoice = {}
    all_item_ids_for_status = []

    # Store class values from tax items for invoice-level class determination
    tax_item_classes = {}

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

            # CRITICAL BUG FIX: Preserve class values from TAX items
            # Tax items with class A or L should affect entire invoice
            # classification
            item_class = getattr(item, 'class_', '') or ''
            if item_class and item_invoice_id:
                if item_invoice_id not in tax_item_classes:
                    tax_item_classes[item_invoice_id] = []
                tax_item_classes[item_invoice_id].append(item_class)

            # CRITICAL BUG FIX: Add TAX item IDs to status update list
            # TAX items also need their export_status changed from Pending
            # to Sent
            tax_item_id = getattr(item, 'id', None)
            if tax_item_id:
                all_item_ids_for_status.append(tax_item_id)
        else:
            # Fast data extraction - direct attribute access
            item_data = {
                'id': getattr(item, 'id', None),
                'invoice_id': item_invoice_id,
                'sheet_name': item_sheet_name,
                'mpi_item': (
                    getattr(item, 'mpi_item', 'No Match') or 'No Match'
                ),
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

    logger.info(
        f"Data processing completed in {time.time() - process_start:.3f}s"
    )

    update_progress(operation_id, "vectorizing", 50,
                    "Performing vectorized data operations")

    # VECTORIZED operations - ultra-fast pandas processing
    vectorized_start = time.time()

    df = pd.DataFrame(all_items_data)
    df['account'] = ''

    # =================================================================
    # BUSINESS LOGIC IMPLEMENTATION - CORRECT PRIORITY ORDER
    # =================================================================

    # STEP 1: 🔤 CLASS-BASED MAPPING (PRIORITY RULE - OVERRIDES ALL)
    # This is the most important rule and must be applied first

    # Find all invoices that have ANY item with class 'A' or 'L'
    # (including from TAX items)
    invoices_with_class_a = set()
    invoices_with_class_l = set()

    # Check regular items for class A/L
    class_a_items = df[df['class_'] == 'A']
    class_l_items = df[df['class_'] == 'L']

    if not class_a_items.empty:
        invoices_with_class_a.update(class_a_items['invoice_id'].unique())

    if not class_l_items.empty:
        invoices_with_class_l.update(class_l_items['invoice_id'].unique())

    # CRITICAL: Also check TAX items for class A/L
    for invoice_id, classes in tax_item_classes.items():
        if 'A' in classes:
            invoices_with_class_a.add(invoice_id)
        elif 'L' in classes:  # Note: A takes priority over L
            invoices_with_class_l.add(invoice_id)

    # PRIORITY RULE 1: If ANY item in invoice has class 'A'
    # -> ALL items in that invoice get "Additional Material" account
    if invoices_with_class_a:
        df.loc[df['invoice_id'].isin(invoices_with_class_a), 'account'] = (
            'UnInvoiced JIP:Material:Additional Material'
        )
        logger.info(
            f"Applied Class A rule to {len(invoices_with_class_a)} "
            f"invoices (Additional Material)"
        )

    # PRIORITY RULE 2: If ANY item in invoice has class 'L' (but not A)
    # -> ALL items in that invoice get "Labor" account
    invoices_with_class_l_only = invoices_with_class_l - invoices_with_class_a
    if invoices_with_class_l_only:
        df.loc[
            df['invoice_id'].isin(invoices_with_class_l_only), 'account'
        ] = (
            'UnInvoiced JIP:Subcontractors Expense:Labor'
        )
        logger.info(
            f"Applied Class L rule to {len(invoices_with_class_l_only)} "
            f"invoices (Labor)"
        )

    # STEP 2: 🧠 SHEET NAME-BASED MAPPING (FALLBACK LOGIC)
    # Only applied to items without accounts from class rules
    unassigned_mask = df['account'] == ''
    if unassigned_mask.any():
        df.loc[unassigned_mask, 'account'] = (
            df.loc[unassigned_mask, 'sheet_name']
            .map(classification_cache.get).fillna('')
        )
        logger.info(
            f"Applied sheet name mapping to {unassigned_mask.sum()} items"
        )

    # STEP 3: 📌 SPECIAL CASE MAPPING (MANUAL RULES - SAFETY NET)
    # Only applied to items still without accounts
    mpi_mappings = {
        'UIDI-Job Materials Purchased': (
            'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
        ),
        'UIDI-Job Equipment': (
            'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased'
        ),
        'UIDI-Sprinkler specialty item': (
            'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
        ),
        'UIDI-Drainage Material': (
            'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
        )
    }

    for mpi_item, account in mpi_mappings.items():
        mask = (df['mpi_item'] == mpi_item) & (df['account'] == '')
        if mask.any():
            df.loc[mask, 'account'] = account
            logger.info(
                f"Applied special mapping for {mpi_item}: "
                f"{mask.sum()} items"
            )

    # 🚨 VALIDATION: Check for mapping failures
    # CRITICAL VALIDATION: Check for "No Match" items - STRICT BLOCKING
    no_match_items = df[df['mpi_item'] == 'No Match']
    if not no_match_items.empty:
        no_match_refs = no_match_items[
            ['mpi_item', 'ref_no', 'item', 'description']
        ].drop_duplicates()
        no_match_list = no_match_refs.to_dict(orient='records')

        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot export to QuickBooks: Found {len(no_match_items)} "
                f"'No Match' items. Please map these items first. "
                f"Sample unmapped items: {no_match_list[:5]}"
            )
        )

    # Check for items with empty accounts (unmatched sheet names)
    unmatched_accounts = df[df['account'] == '']
    if not unmatched_accounts.empty:
        unmatched_references = unmatched_accounts[
            ['mpi_item', 'ref_no', 'sheet_name']
        ].drop_duplicates()
        unmatched_references_list = unmatched_references.to_dict(
            orient='records'
        )

        raise HTTPException(
            status_code=400,
            detail=(
                f"Unmatched sheet names are present. Please add "
                f"classifications for these sheet names: "
                f"{unmatched_references_list[:5]}"
            )
        )

    # Default account for any remaining unmatched (should not happen after
    # validation)
    df.loc[df['account'] == '', 'account'] = (
        'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
    )

    # FAST data type conversions
    df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
    df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0)
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
    df['tax_amount'] = df['invoice_id'].map(tax_by_invoice).fillna(0)

    logger.info(
        f"Vectorized processing in {time.time() - vectorized_start:.3f}s"
    )

    update_progress(operation_id, "aggregating", 70,
                    "Aggregating data for QuickBooks export")

    # FAST aggregation
    agg_start = time.time()

    batch_entry = df.groupby(
        ['account', 'ref_no', 'customer_job'], as_index=False
    ).agg({
        'amount': 'sum',
        'tax_amount': 'first',
        'date': 'first',
        'vendor': 'first',
        'memo': 'first',
        'class_': 'first'  # This preserves original class values
    })

    # CRITICAL BUSINESS LOGIC FIX: Apply tax like original working code
    # Tax should be added per invoice, not per row
    def add_tax_per_invoice(row):
        return row['amount'] + row['tax_amount']

    batch_entry['amount'] = batch_entry.apply(add_tax_per_invoice, axis=1)

    # =================================================================
    # ✅ CLASS PRESERVATION LOGIC (ENSURES NO CLASS INFO IS LOST)
    # =================================================================
    # This ensures that ANY class value from items within an invoice
    # appears in the Excel Class column - NEVER leave it blank if ANY
    # item has a class!

    # Build comprehensive class mapping including tax items
    invoice_to_classes = {}

    # Get classes from regular items
    for _, row in df.iterrows():
        invoice_id = row['invoice_id']
        class_val = row['class_']
        if class_val and str(class_val).strip():
            if invoice_id not in invoice_to_classes:
                invoice_to_classes[invoice_id] = []
            # Only add if not already present
            if str(class_val).strip() not in invoice_to_classes[invoice_id]:
                invoice_to_classes[invoice_id].append(str(class_val).strip())

    # Add classes from tax items
    for invoice_id, classes in tax_item_classes.items():
        if invoice_id not in invoice_to_classes:
            invoice_to_classes[invoice_id] = []
        for class_val in classes:
            if class_val and str(class_val).strip():
                # Only add if not already present
                class_str = str(class_val).strip()
                if class_str not in invoice_to_classes[invoice_id]:
                    invoice_to_classes[invoice_id].append(class_str)

    # Apply class priority logic for final class column
    # Priority: A > L > other classes (show multiple if different) > empty
    def get_invoice_final_class(ref_no):
        # Find invoice_id for this ref_no
        matching_invoices = df[df['ref_no'] == ref_no]['invoice_id'].unique()
        if len(matching_invoices) == 0:
            return ''

        invoice_id = matching_invoices[0]
        classes = invoice_to_classes.get(invoice_id, [])

        if not classes:
            return ''

        # Priority logic: A > L > show all other classes
        if 'A' in classes:
            return 'A'
        elif 'L' in classes:
            return 'L'
        else:
            # For other classes, show all of them (comma-separated)
            # or pick the first one based on your preference
            non_al_classes = [c for c in classes if c not in ['A', 'L']]
            if non_al_classes:
                # Option 1: Show all classes (comma-separated)
                sorted_classes = sorted(set(non_al_classes))
                return ', '.join(sorted_classes)
                # Option 2: Show just the first one (uncomment below)
                # return non_al_classes[0]
            else:
                # Fallback: return first class found
                return classes[0]

    # Apply the class logic to batch_entry
    batch_entry['class_'] = batch_entry['ref_no'].apply(
        get_invoice_final_class)

    # Log class preservation statistics
    total_invoices = len(batch_entry)
    invoices_with_classes = len(batch_entry[batch_entry['class_'] != ''])
    logger.info(
        f"Class preservation: {invoices_with_classes}/{total_invoices} "
        f"invoices have class values preserved"
    )

    # FAST formatting
    batch_entry['date'] = (
        pd.to_datetime(batch_entry['date'], errors='coerce')
        .dt.strftime('%m/%d/%Y')
    )
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

    logger.info(
        f"Aggregation completed in {time.time() - agg_start:.3f}s for "
        f"{len(final_batch_entry)} rows"
    )

    update_progress(operation_id, "generating_excel", 85,
                    f"Generating Excel file with {len(final_batch_entry)} "
                    f"rows")

    # FAST Excel generation and S3 upload
    excel_start = time.time()

    # Use same fast method as export-all
    try:
        from mpi_backend.utils.pdf_to_excel.formatting_util import (
            save_final_data_fast
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
        save_final_data_fast(final_batch_entry, file_path)

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

    # FAST RESPONSE: Move ALL status updates to background for maximum speed
    # This ensures download URL is returned immediately like export-all
    if all_item_ids_for_status or invoice_ids:
        background_tasks.add_task(
            perform_database_updates_background,
            all_item_ids_for_status,
            operation_id,
            invoice_ids  # Pass invoice_ids to background task
        )

    total_time = time.time() - start_time
    logger.info(
        f"ULTRA-FAST QB EXPORT COMPLETED: {len(final_batch_entry)} rows in "
        f"{total_time:.2f}s"
    )

    update_progress(operation_id, "completed", 100,
                    f"Export completed in {total_time:.2f}s")

    return download_url
