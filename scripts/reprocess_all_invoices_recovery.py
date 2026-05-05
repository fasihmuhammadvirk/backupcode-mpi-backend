#!/usr/bin/env python3
"""
Targeted Invoice Recovery and Reprocessing Script
=================================================

This script intelligently identifies and reprocesses only invoices that are missing
tax lines or have very few items, indicating they may have been affected by the
freight cleanup script. This targeted approach is much more efficient than reprocessing
all invoices.

The script will:
1. Find invoices with very few items (< threshold) OR missing tax lines
2. Download each affected invoice PDF from S3
3. Reprocess the PDF to extract missing invoice items
4. Add missing invoice items while preserving existing ones
5. Maintain all existing statuses, mappings, and data integrity

Usage:
    python scripts/reprocess_all_invoices_recovery.py [options]

Options:
    --dry-run                  Preview what would be reprocessed without making changes
    --verbose                  Enable detailed logging
    --batch-size INT           Number of invoices to process per batch (default: 10)
    --supplier-filter STR      Only process invoices from specific supplier
    --from-date DATE           Only process invoices from this date onwards (YYYY-MM-DD)
    --max-invoices INT         Maximum number of invoices to process (for testing)
    --min-items-threshold INT  Minimum expected items per invoice (default: 3)
"""

import sys
import argparse
import logging
import os
import shutil
import requests
import tempfile
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

# Add the parent directory to the path so we can import mpi_backend
sys.path.append(str(Path(__file__).parent.parent))

from mpi_backend.database import get_db
from mpi_backend.database.models import Invoice, InvoiceItem, Supplier
from mpi_backend.database.controllers.Invoice import InvoiceController
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.config.logging_config import setup_logging
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.utils.s3_utils import get_presigned_url
from mpi_backend.utils.invoice_converter import convert_single_invoice
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from sqlalchemy import and_, or_, func

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


def get_invoices_missing_tax_or_items(
    db, 
    supplier_filter: Optional[str] = None,
    from_date: Optional[date] = None,
    max_invoices: Optional[int] = None,
    min_items_threshold: int = 3
) -> List[Dict[str, Any]]:
    """
    Get invoices that need reprocessing because they're missing tax lines or have very few items.
    
    Args:
        db: Database session
        supplier_filter: Optional supplier name filter
        from_date: Optional date filter (only invoices from this date onwards)
        max_invoices: Maximum number of invoices to return
        min_items_threshold: Minimum number of items expected (invoices with fewer need reprocessing)
        
    Returns:
        List of invoice dictionaries with metadata
    """
    logger.info("Fetching invoices that need reprocessing (missing tax or few items)...")
    
    # Base query - exclude credit invoices by default
    query = db.query(Invoice).join(Supplier, Invoice.supplier_id == Supplier.id)
    query = query.filter(~Invoice.filename.like('CustomerCredit%'))
    
    # Apply filters
    if supplier_filter:
        query = query.filter(Supplier.supplier_name.ilike(f"%{supplier_filter}%"))
        logger.info(f"Filtering by supplier: {supplier_filter}")
    
    if from_date:
        query = query.filter(Invoice.date >= from_date)
        logger.info(f"Filtering by date from: {from_date}")
    
    # Get all invoices with their item counts
    invoices_with_counts = db.query(
        Invoice.id,
        Invoice.filename,
        Invoice.date,
        Invoice.supplier_id,
        Invoice.status,
        Invoice.is_exported,
        Supplier.supplier_name,
        func.count(InvoiceItem.id).label('item_count')
    ).join(Supplier, Invoice.supplier_id == Supplier.id)\
     .outerjoin(InvoiceItem, and_(
         Invoice.id == InvoiceItem.invoice_id,
         InvoiceItem.is_active == True
     ))\
     .filter(~Invoice.filename.like('CustomerCredit%'))\
     .group_by(Invoice.id, Invoice.filename, Invoice.date, Invoice.supplier_id, 
               Invoice.status, Invoice.is_exported, Supplier.supplier_name)
    
    # Apply additional filters
    if supplier_filter:
        invoices_with_counts = invoices_with_counts.filter(
            Supplier.supplier_name.ilike(f"%{supplier_filter}%")
        )
    
    if from_date:
        invoices_with_counts = invoices_with_counts.filter(Invoice.date >= from_date)
    
    # Order by date (newest first)
    invoices_with_counts = invoices_with_counts.order_by(Invoice.date.desc())
    
    # Apply limit if specified
    if max_invoices:
        invoices_with_counts = invoices_with_counts.limit(max_invoices)
    
    logger.info("Executing database query to get invoice counts...")
    logger.info("This may take a moment for large datasets...")
    
    try:
        results = invoices_with_counts.all()
        logger.info(f"Retrieved {len(results)} invoices from database")
    except Exception as e:
        logger.error(f"Database query failed: {str(e)}")
        logger.info("Trying with a smaller batch...")
        # Fallback to a smaller batch if the query fails
        invoices_with_counts = invoices_with_counts.limit(100)
        results = invoices_with_counts.all()
        logger.info(f"Retrieved {len(results)} invoices from database (limited batch)")
    
    # Filter for invoices that need reprocessing
    invoices_to_reprocess = []
    logger.info("Analyzing invoices for reprocessing criteria...")
    
    processed_count = 0
    for result in results:
        processed_count += 1
        invoice_id = str(result.id)
        item_count = result.item_count or 0
        
        # Show progress every 50 invoices
        if processed_count % 50 == 0 or processed_count == len(results):
            logger.info(f"Processed {processed_count}/{len(results)} invoices...")
        
        # Check if this invoice needs reprocessing
        needs_reprocessing = False
        reason = ""
        
        # Check 1: Very few items (might be missing data)
        if item_count < min_items_threshold:
            needs_reprocessing = True
            reason = f"Only {item_count} items (expected at least {min_items_threshold})"
        
        # Check 2: Missing tax line (efficient batch check)
        if not needs_reprocessing and item_count > 0:
            # Use a more efficient approach - check if this invoice has any tax items
            # by joining with the invoice items in a single query
            tax_items = db.query(InvoiceItem.id).filter(
                and_(
                    InvoiceItem.invoice_id == result.id,
                    InvoiceItem.is_active == True,
                    or_(
                        InvoiceItem.mpi_description.ilike('%tax%'),
                        InvoiceItem.mpi_description.ilike('%gst%'),
                        InvoiceItem.mpi_description.ilike('%hst%'),
                        InvoiceItem.mpi_description.ilike('%pst%'),
                        InvoiceItem.mpi_description.ilike('%vat%'),
                        InvoiceItem.item.ilike('%tax%'),
                        InvoiceItem.description.ilike('%tax%')
                    )
                )
            ).first()  # Use .first() instead of .count() for better performance
            
            if tax_items is None:
                needs_reprocessing = True
                reason = f"No tax items found ({item_count} total items)"
        
        if needs_reprocessing:
            invoices_to_reprocess.append({
                'id': invoice_id,
                'filename': result.filename,
                'date': result.date,
                'supplier_id': result.supplier_id,
                'supplier_name': result.supplier_name or 'Unknown',
                'status': result.status,
                'is_exported': result.is_exported,
                'item_count': item_count,
                'reason': reason
            })
    
    logger.info(f"Found {len(invoices_to_reprocess)} invoices that need reprocessing:")
    for inv in invoices_to_reprocess[:5]:  # Show first 5
        logger.info(f"  - {inv['filename']}: {inv['reason']}")
    if len(invoices_to_reprocess) > 5:
        logger.info(f"  ... and {len(invoices_to_reprocess) - 5} more")
    
    return invoices_to_reprocess


def reprocess_single_invoice(invoice_data: Dict[str, Any], db, dry_run: bool = False) -> Dict[str, Any]:
    """
    Reprocess a single invoice to recover missing invoice items.
    
    Args:
        invoice_data: Invoice metadata dictionary
        db: Database session
        dry_run: If True, only simulate the process
        
    Returns:
        Dictionary with processing results
    """
    invoice_id = invoice_data['id']
    filename = invoice_data['filename']
    supplier_name = invoice_data['supplier_name']
    
    result = {
        'invoice_id': invoice_id,
        'filename': filename,
        'supplier_name': supplier_name,
        'success': False,
        'error': None,
        'items_added': 0,
        'items_skipped': 0
    }
    
    try:
        logger.info(f"Reprocessing invoice: {filename} (ID: {invoice_id})")
        
        # Count existing invoice items before processing (even in dry run)
        existing_items_count = db.query(InvoiceItem).filter(
            InvoiceItem.invoice_id == invoice_id,
            InvoiceItem.is_active == True
        ).count()
        
        logger.info(f"Existing invoice items: {existing_items_count}")
        
        if dry_run:
            logger.info(f"DRY RUN: Would reprocess {filename}")
            result['success'] = True
            result['items_added'] = 0  # Simulated
            result['items_skipped'] = existing_items_count
            return result
        
        # Get supplier info
        supplier = db.query(Supplier).filter(Supplier.id == invoice_data['supplier_id']).first()
        if not supplier:
            result['error'] = f"Supplier not found for ID: {invoice_data['supplier_id']}"
            return result
        
        # Get presigned URL for the invoice file
        invoice_url = get_presigned_url(filename)
        if not invoice_url:
            result['error'] = f"Could not get presigned URL for file: {filename}"
            return result
        
        # Create temporary directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Download the invoice file
            logger.info(f"Downloading invoice from S3: {filename}")
            response = requests.get(invoice_url, timeout=60)
            if response.status_code != 200:
                result['error'] = f"Failed to download invoice: HTTP {response.status_code}"
                return result
            
            # Save file to temporary location
            file_path = os.path.join(temp_dir, filename)
            with open(file_path, 'wb') as file:
                file.write(response.content)
            
            logger.info(f"Downloaded invoice: {filename} ({len(response.content)} bytes)")
            
            
            # Convert PDF to Excel
            logger.info(f"Converting PDF to Excel: {filename}")
            converted_files, failed_files = convert_single_invoice(file_path, supplier_name)
            
            if failed_files:
                result['error'] = f"Failed to convert invoice: {failed_files}"
                return result
            
            if not converted_files:
                result['error'] = "No files were converted"
                return result
            
            # Process extracted data with existing invoice ID
            logger.info(f"Processing extracted data for invoice: {filename}")
            process_results = process_extracted_data(
                converted_files, failed_files, existing_invoice_id=invoice_id
            )
            
            # Count new invoice items after processing
            new_items_count = db.query(InvoiceItem).filter(
                InvoiceItem.invoice_id == invoice_id,
                InvoiceItem.is_active == True
            ).count()
            
            items_added = new_items_count - existing_items_count
            
            logger.info(f"Invoice items after processing: {new_items_count} (+{items_added})")
            
            result['success'] = True
            result['items_added'] = items_added
            result['items_skipped'] = existing_items_count
            
            logger.info(f"Successfully reprocessed invoice: {filename}")
            
    except Exception as e:
        logger.error(f"Error reprocessing invoice {filename}: {str(e)}")
        result['error'] = str(e)
    
    return result


def reprocess_all_invoices(
    dry_run: bool = False,
    batch_size: int = 10,
    supplier_filter: Optional[str] = None,
    from_date: Optional[date] = None,
    max_invoices: Optional[int] = None,
    min_items_threshold: int = 3,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Reprocess invoices that are missing tax lines or have very few items.
    
    Args:
        dry_run: If True, only simulate the process
        batch_size: Number of invoices to process per batch
        supplier_filter: Optional supplier name filter
        from_date: Optional date filter
        max_invoices: Maximum number of invoices to process
        min_items_threshold: Minimum expected items (invoices with fewer need reprocessing)
        verbose: Enable detailed logging
        
    Returns:
        Dictionary with processing statistics
    """
    stats = {
        'total_invoices': 0,
        'processed_invoices': 0,
        'successful_invoices': 0,
        'failed_invoices': 0,
        'total_items_added': 0,
        'total_items_skipped': 0,
        'batches_processed': 0,
        'errors': []
    }
    
    if verbose:
        logger.setLevel(logging.DEBUG)
    
    logger.info("="*80)
    logger.info("STARTING TARGETED INVOICE RECOVERY AND REPROCESSING")
    logger.info("="*80)
    logger.info("Targeting invoices that are missing tax lines or have very few items")
    logger.info(f"Minimum items threshold: {min_items_threshold}")
    
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
    
    try:
        # Create database context manager
        db_context = contextmanager(get_db)
        with db_context() as db:
            # Get invoices that need reprocessing (missing tax or few items)
            invoices = get_invoices_missing_tax_or_items(
                db, supplier_filter, from_date, max_invoices, min_items_threshold
            )
            
            stats['total_invoices'] = len(invoices)
            
            if stats['total_invoices'] == 0:
                logger.info("No invoices found that need reprocessing")
                return stats
            
            logger.info(f"Found {stats['total_invoices']} invoices that need reprocessing")
            
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
                        
                        result = reprocess_single_invoice(invoice_data, db, dry_run)
                        
                        if result['success']:
                            stats['successful_invoices'] += 1
                            stats['total_items_added'] += result['items_added']
                            stats['total_items_skipped'] += result['items_skipped']
                            
                            # Show the reason for reprocessing
                            reason = invoice_data.get('reason', 'Unknown')
                            logger.info(f"✓ {result['filename']}: "
                                      f"+{result['items_added']} items, "
                                      f"{result['items_skipped']} existing "
                                      f"({reason})")
                        else:
                            stats['failed_invoices'] += 1
                            stats['errors'].append({
                                'filename': result['filename'],
                                'error': result['error']
                            })
                            
                            logger.error(f"✗ {result['filename']}: {result['error']}")
                    
                    except Exception as e:
                        stats['failed_invoices'] += 1
                        stats['errors'].append({
                            'filename': invoice_data['filename'],
                            'error': str(e)
                        })
                        
                        logger.error(f"✗ {invoice_data['filename']}: {str(e)}")
                
                logger.info("-" * 60)
                logger.info(f"Batch {stats['batches_processed']} completed: "
                          f"{stats['successful_invoices']}/{stats['processed_invoices']} successful")
            
            logger.info("="*80)
            logger.info("TARGETED INVOICE RECOVERY AND REPROCESSING COMPLETED")
            logger.info("="*80)
            logger.info(f"Total invoices found: {stats['total_invoices']}")
            logger.info(f"Processed invoices: {stats['processed_invoices']}")
            logger.info(f"Successful invoices: {stats['successful_invoices']}")
            logger.info(f"Failed invoices: {stats['failed_invoices']}")
            logger.info(f"Total items {'added' if not dry_run else 'would be added'}: {stats['total_items_added']}")
            logger.info(f"Total items skipped: {stats['total_items_skipped']}")
            logger.info(f"Batches processed: {stats['batches_processed']}")
            
            if stats['errors']:
                logger.info(f"Errors encountered: {len(stats['errors'])}")
                for error in stats['errors'][:5]:  # Show first 5 errors
                    logger.error(f"  - {error['filename']}: {error['error']}")
                if len(stats['errors']) > 5:
                    logger.error(f"  ... and {len(stats['errors']) - 5} more errors")
            
            if dry_run:
                logger.info("DRY RUN COMPLETE - No actual changes were made")
            
            return stats
            
    except Exception as e:
        logger.error(f"Critical error in reprocess_all_invoices: {str(e)}")
        stats['errors'].append({
            'filename': 'SYSTEM_ERROR',
            'error': str(e)
        })
        return stats


def main():
    """Main function with command line argument parsing"""
    parser = argparse.ArgumentParser(description='Reprocess invoices missing tax lines or with very few items')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Preview what would be reprocessed without making changes')
    parser.add_argument('--verbose', action='store_true', 
                       help='Enable detailed logging')
    parser.add_argument('--batch-size', type=int, default=10,
                       help='Number of invoices to process per batch (default: 10)')
    parser.add_argument('--supplier-filter', type=str,
                       help='Only process invoices from specific supplier (partial name match)')
    parser.add_argument('--from-date', type=str,
                       help='Only process invoices from this date onwards (YYYY-MM-DD)')
    parser.add_argument('--max-invoices', type=int,
                       help='Maximum number of invoices to process (for testing)')
    parser.add_argument('--min-items-threshold', type=int, default=3,
                       help='Minimum expected items per invoice (default: 3)')
    
    args = parser.parse_args()
    
    # Parse date if provided
    from_date = None
    if args.from_date:
        try:
            from_date = datetime.strptime(args.from_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid date format: {args.from_date}. Use YYYY-MM-DD")
            return 1
    
    try:
        stats = reprocess_all_invoices(
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            supplier_filter=args.supplier_filter,
            from_date=from_date,
            max_invoices=args.max_invoices,
            min_items_threshold=args.min_items_threshold,
            verbose=args.verbose
        )
        
        # Exit with error code if there were errors
        if stats['errors']:
            logger.error(f"Recovery completed with {len(stats['errors'])} errors")
            return 1
        
        logger.info("Invoice recovery completed successfully")
        return 0
        
    except Exception as e:
        logger.error(f"Script failed: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
