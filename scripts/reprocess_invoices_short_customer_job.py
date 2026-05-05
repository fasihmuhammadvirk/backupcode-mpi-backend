#!/usr/bin/env python3
"""
Invoice Customer Job Recovery Script
===================================

This script reprocesses all invoices from the past 3 months to update customer job information
using the existing /invoice/process API endpoint.

Usage:
    python scripts/reprocess_invoices_short_customer_job.py [options]

Options:
    --dry-run                  Preview what would be reprocessed
    --verbose                  Enable detailed logging
    --batch-size INT           Number of invoices per batch (default: 5)
    --supplier-filter STR      Only process specific supplier
    --max-invoices INT         Maximum invoices to process
    --months-back INT          Number of months back to process (default: 3)
"""

import sys
import argparse
import logging
import requests
import os
import shutil
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
from datetime import datetime, timedelta
from sqlalchemy import and_, func

# Add the parent directory to the path
sys.path.append(str(Path(__file__).parent.parent))

from mpi_backend.database import get_db
from mpi_backend.database.models import Invoice, InvoiceItem, Supplier
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.database.controllers.Invoice import InvoiceController
from mpi_backend.config.logging_config import setup_logging
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_converter import convert_single_invoice
from mpi_backend.utils.s3_utils import get_presigned_url

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


def _sanitize_path_component(name: str) -> str:
    """Sanitize user/DB-provided strings for safe filesystem usage on Windows/Linux.
    Replaces reserved characters and path separators with underscores.
    """
    if not name:
        return "unknown"
    # Replace Windows reserved characters and any slashes/backslashes
    name = re.sub(r'[<>:"/\\|?*]+', '_', name)
    # Collapse spaces
    name = re.sub(r"\s+", " ", name).strip()
    # Guard against device names (CON, PRN, AUX, NUL, COM1, LPT1, etc.)
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name):
        name = f"_{name}__"
    return name


def get_invoices_past_months(
    db,
    supplier_filter: Optional[str] = None,
    max_invoices: Optional[int] = None,
    months_back: int = 3
) -> List[Dict[str, Any]]:
    """Get invoices from the past N months for customer job reprocessing."""
    logger.info(f"Fetching invoices from the past {months_back} months...")

    # Calculate date threshold
    cutoff_date = datetime.now() - timedelta(days=months_back * 30)
    logger.info(f"Processing invoices from {cutoff_date.strftime('%Y-%m-%d')} onwards")

    # Base query - exclude credit invoices
    query = db.query(Invoice).join(
        Supplier, Invoice.supplier_id == Supplier.id)
    query = query.filter(~Invoice.filename.like('CustomerCredit%'))
    query = query.filter(Invoice.date >= cutoff_date)

    # Apply filters
    if supplier_filter:
        query = query.filter(
            Supplier.supplier_name.ilike(f"%{supplier_filter}%")
        )
        logger.info(f"Filtering by supplier: {supplier_filter}")

    # Get invoices with item counts
    invoices_with_counts = db.query(
        Invoice.id,
        Invoice.filename,
        Invoice.date,
        Invoice.supplier_id,
        Invoice.status,
        Supplier.supplier_name,
        func.count(InvoiceItem.id).label('item_count')
    ).join(Supplier, Invoice.supplier_id == Supplier.id)\
     .outerjoin(InvoiceItem, and_(
         Invoice.id == InvoiceItem.invoice_id,
         InvoiceItem.is_active
     ))\
     .filter(~Invoice.filename.like('CustomerCredit%'))\
     .filter(Invoice.date >= cutoff_date)\
     .group_by(
         Invoice.id, Invoice.filename, Invoice.date,
         Invoice.supplier_id, Invoice.status, Supplier.supplier_name
     )

    # Apply additional filters
    if supplier_filter:
        invoices_with_counts = invoices_with_counts.filter(
            Supplier.supplier_name.ilike(f"%{supplier_filter}%")
        )

    # Order by date (newest first)
    invoices_with_counts = invoices_with_counts.order_by(Invoice.date.desc())

    # Apply limit if specified
    if max_invoices:
        invoices_with_counts = invoices_with_counts.limit(max_invoices)

    logger.info("Executing database query...")

    try:
        results = invoices_with_counts.all()
        logger.info(f"Retrieved {len(results)} invoices from database")
    except Exception as e:
        logger.error(f"Database query failed: {str(e)}")
        return []

    # Convert results to list of dictionaries
    invoices_to_reprocess = []
    logger.info("Preparing invoices for reprocessing...")

    processed_count = 0
    for result in results:
        processed_count += 1
        invoice_id = str(result.id)
        item_count = result.item_count or 0

        # Show progress every 50 invoices
        if processed_count % 50 == 0 or processed_count == len(results):
            logger.info(f"Processed {processed_count}/{len(results)} invoices...")

        # Only process invoices that have items
        if item_count > 0:
            invoices_to_reprocess.append({
                'id': invoice_id,
                'filename': result.filename,
                'date': result.date,
                'supplier_id': result.supplier_id,
                'supplier_name': result.supplier_name or 'Unknown',
                'status': result.status,
                'item_count': item_count,
                'reason': f"Reprocessing customer job from past {months_back} months"
            })

    logger.info(f"Found {len(invoices_to_reprocess)} invoices to reprocess:")
    for inv in invoices_to_reprocess[:5]:  # Show first 5
        logger.info(f"  - {inv['filename']} ({inv['date']}): {inv['item_count']} items")
    if len(invoices_to_reprocess) > 5:
        logger.info(f"  ... and {len(invoices_to_reprocess) - 5} more")

    return invoices_to_reprocess


def reprocess_invoice_direct(
    invoice_id: str, 
    db,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Reprocess a single invoice using the same logic as the /invoice/process endpoint."""
    result = {
        'invoice_id': invoice_id,
        'success': False,
        'error': None,
        'filename': None
    }

    try:
        if dry_run:
            logger.info(f"DRY RUN: Would reprocess invoice ID: {invoice_id}")
            result['success'] = True
            return result

        logger.info(f"Starting direct reprocessing of invoice: {invoice_id}")
        
        # Get invoice and supplier info
        invoice = InvoiceController(db).get_invoice_by_invoiceID(invoice_id, db)
        if not invoice:
            result['error'] = f"Invoice with ID {invoice_id} not found"
            logger.error(f"Invoice not found: {invoice_id}")
            return result

        supplier = SupplierController(db).get_supplier_by_id(invoice.supplier_id)
        if not supplier:
            result['error'] = f"Supplier for invoice {invoice_id} not found: {invoice.supplier_id}"
            logger.error(f"Supplier not found for invoice {invoice_id}: {invoice.supplier_id}")
            return result

        result['filename'] = invoice.filename

        # Download invoice from S3
        invoice_url = get_presigned_url(file_key=f'{supplier}/{invoice_id}')
        if not invoice_url:
            result['error'] = f"Couldn't fetch requested Invoice URL for: {invoice_id}"
            logger.error(f"Couldn't fetch requested Invoice URL for: {invoice_id}")
            return result

        # Create upload directory (sanitize supplier for filesystem safety)
        safe_supplier = _sanitize_path_component(supplier)
        upload_folder = os.path.join(INVOICE_DOWNLOAD_FOLDER, safe_supplier)
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        # Download file
        response = requests.get(invoice_url, timeout=30)
        if response.status_code == 200:
            file_path = os.path.join(upload_folder, invoice.filename)
            with open(file_path, 'wb') as file:
                file.write(response.content)
        else:
            result['error'] = f"Failed to download invoice from URL: {invoice_url}, status: {response.status_code}"
            logger.error(f"Failed to download invoice from URL: {invoice_url}, status: {response.status_code}")
            return result

        # Convert and process the invoice
        converted_files, failed_files = convert_single_invoice(file_path, supplier)
        if failed_files:
            result['error'] = f"Failed to convert invoice: {failed_files}"
            logger.error(f"Failed to convert invoice: {failed_files}")
            return result

        # Process extracted data with existing invoice ID
        # The enhanced duplicate detection logic will handle updating existing invoice items
        # without deleting the invoice record itself
        process_extracted_data(
            converted_files, failed_files, existing_invoice_id=invoice_id
        )

        # Clean up files after processing (handle files and directories)
        for entry in os.listdir(upload_folder):
            path = os.path.join(upload_folder, entry)
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass

        result['success'] = True
        logger.info(f"Successfully reprocessed invoice: {invoice.filename}")

    except Exception as e:
        logger.error(f"Error reprocessing invoice {invoice_id}: {str(e)}")
        result['error'] = str(e)

    return result


def reprocess_invoices_customer_job(
    dry_run: bool = False,
    batch_size: int = 5,
    supplier_filter: Optional[str] = None,
    max_invoices: Optional[int] = None,
    months_back: int = 3,
    verbose: bool = False
) -> Dict[str, Any]:
    """Reprocess invoices from the past N months to update customer job information."""
    stats = {
        'total_invoices': 0,
        'processed_invoices': 0,
        'successful_invoices': 0,
        'failed_invoices': 0,
        'batches_processed': 0,
        'errors': []
    }

    if verbose:
        logger.setLevel(logging.DEBUG)

    logger.info("="*80)
    logger.info("STARTING INVOICE CUSTOMER JOB REPROCESSING")
    logger.info("="*80)
    logger.info(f"Targeting invoices from the past {months_back} months")

    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    try:
        # Create database context manager
        db_context = contextmanager(get_db)
        with db_context() as db:
            # Get invoices from past months
            invoices = get_invoices_past_months(
                db, supplier_filter, max_invoices, months_back
            )

            stats['total_invoices'] = len(invoices)

            if stats['total_invoices'] == 0:
                logger.info(f"No invoices found from the past {months_back} months")
                return stats

            logger.info(f"Found {stats['total_invoices']} invoices to reprocess")

            # Process invoices in batches
            for i in range(0, len(invoices), batch_size):
                batch = invoices[i:i + batch_size]
                stats['batches_processed'] += 1

                logger.info(f"Processing batch {stats['batches_processed']}: "
                          f"{len(batch)} invoices")
                logger.info("-" * 60)

                for invoice_data in batch:
                    try:
                        stats['processed_invoices'] += 1

                        result = reprocess_invoice_direct(
                            invoice_data['id'], db, dry_run
                        )

                        if result['success']:
                            stats['successful_invoices'] += 1
                            logger.info(f"✓ {invoice_data['filename']}: Success")
                        else:
                            stats['failed_invoices'] += 1
                            stats['errors'].append({
                                'filename': invoice_data['filename'],
                                'invoice_id': invoice_data['id'],
                                'error': result['error']
                            })
                            logger.error(f"✗ {invoice_data['filename']}: {result['error']}")

                    except Exception as e:
                        stats['failed_invoices'] += 1
                        stats['errors'].append({
                            'filename': invoice_data['filename'],
                            'invoice_id': invoice_data['id'],
                            'error': str(e)
                        })
                        logger.error(f"✗ {invoice_data['filename']}: {str(e)}")

                logger.info("-" * 60)
                logger.info(f"Batch {stats['batches_processed']} completed: "
                          f"{stats['successful_invoices']}/{stats['processed_invoices']} successful")

            logger.info("="*80)
            logger.info("INVOICE CUSTOMER JOB REPROCESSING COMPLETED")
            logger.info("="*80)
            logger.info(f"Total invoices found: {stats['total_invoices']}")
            logger.info(f"Processed invoices: {stats['processed_invoices']}")
            logger.info(f"Successful invoices: {stats['successful_invoices']}")
            logger.info(f"Failed invoices: {stats['failed_invoices']}")
            logger.info(f"Batches processed: {stats['batches_processed']}")

            if stats['errors']:
                logger.info(f"Errors encountered: {len(stats['errors'])}")
                for error in stats['errors'][:5]:  # Show first 5 errors
                    logger.error(f"  - {error['filename']} (ID: {error['invoice_id']}): {error['error']}")
                if len(stats['errors']) > 5:
                    logger.error(f"  ... and {len(stats['errors']) - 5} more errors")

            if dry_run:
                logger.info("DRY RUN COMPLETE - No actual changes were made")

            return stats

    except Exception as e:
        logger.error(f"Critical error in reprocess_invoices_customer_job: {str(e)}")
        stats['errors'].append({
            'filename': 'SYSTEM_ERROR',
            'invoice_id': 'N/A',
            'error': str(e)
        })
        return stats


def main():
    """Main function with command line argument parsing"""
    parser = argparse.ArgumentParser(
        description='Reprocess invoices from the past N months to update customer job information'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Preview what would be reprocessed without making changes'
    )
    parser.add_argument(
        '--verbose', action='store_true',
        help='Enable detailed logging'
    )
    parser.add_argument(
        '--batch-size', type=int, default=5,
        help='Number of invoices to process per batch (default: 5)'
    )
    parser.add_argument(
        '--supplier-filter', type=str,
        help='Only process invoices from specific supplier (partial name match)'
    )
    parser.add_argument(
        '--max-invoices', type=int,
        help='Maximum number of invoices to process (for testing)'
    )
    parser.add_argument(
        '--months-back', type=int, default=3,
        help='Number of months back to process (default: 3)'
    )
    args = parser.parse_args()

    try:
        stats = reprocess_invoices_customer_job(
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            supplier_filter=args.supplier_filter,
            max_invoices=args.max_invoices,
            months_back=args.months_back,
            verbose=args.verbose
        )

        # Exit with error code if there were errors
        if stats['errors']:
            logger.error(f"Reprocessing completed with {len(stats['errors'])} errors")
            return 1

        logger.info("Invoice customer job reprocessing completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Script failed: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
