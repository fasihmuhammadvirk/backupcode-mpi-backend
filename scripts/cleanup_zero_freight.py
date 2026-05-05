#!/usr/bin/env python3
"""
Cleanup Zero Freight Script
===========================

This script removes freight rows from invoices where the freight amount is zero.
It identifies freight rows by checking for:
- MpiDescription = 'Freight' (original description)
- Amount = '0' or '0.0' or '0.00' or similar zero values

Usage:
    python scripts/cleanup_zero_freight.py [options]

Options:
    --dry-run                  Preview what would be deleted without making changes
    --verbose                  Enable detailed logging
    --batch-size INT           Number of records to process per batch (default: 1000)
"""

import sys
import argparse
import logging
from pathlib import Path
from sqlalchemy import and_, or_

# Add the parent directory to the path so we can import mpi_backend
sys.path.append(str(Path(__file__).parent.parent))

from mpi_backend.database import get_db
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.config.logging_config import setup_logging
from contextlib import contextmanager

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


def is_zero_amount(amount_str):
    """
    Check if an amount string represents zero.
    
    Args:
        amount_str: String representation of amount
        
    Returns:
        bool: True if amount is zero, False otherwise
    """
    if not amount_str:
        return True
    
    try:
        # Remove common formatting characters
        clean_amount = str(amount_str).replace(',', '').replace('$', '').strip()
        
        # Convert to float and check if zero
        amount_float = float(clean_amount)
        return amount_float == 0.0
        
    except (ValueError, TypeError):
        # If we can't parse it, consider it non-zero to be safe
        return False


def is_freight_row(mpi_description):
    """
    Check if a row represents a freight row based ONLY on the original description.
    
    Args:
        mpi_description: MpiDescription field value (original description)
        
    Returns:
        bool: True if this is a freight row, False otherwise
    """
    # Only check the original description field
    mpi_desc_str = str(mpi_description).strip() if mpi_description else ''
    
    # Only match exact "Freight" in the original description
    return mpi_desc_str == 'Freight'


def cleanup_zero_freight(dry_run=False, batch_size=1000, verbose=False):
    """
    Remove freight rows where amount is zero.
    
    Args:
        dry_run: If True, only preview what would be deleted
        batch_size: Number of records to process per batch
        verbose: Enable detailed logging
        
    Returns:
        dict: Statistics about the cleanup operation
    """
    stats = {
        'total_freight_rows': 0,
        'zero_freight_rows': 0,
        'deleted_rows': 0,
        'errors': 0,
        'batches_processed': 0
    }
    
    if verbose:
        logger.setLevel(logging.DEBUG)
    
    logger.info("="*80)
    logger.info("STARTING ZERO FREIGHT CLEANUP")
    logger.info("="*80)
    
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
    
    try:
        # Create database context manager
        db_context = contextmanager(get_db)
        with db_context() as db:
            # First, count total freight rows (only by original description)
            total_freight_query = db.query(InvoiceItem).filter(
                InvoiceItem.mpi_description == 'Freight'
            )
            stats['total_freight_rows'] = total_freight_query.count()
            logger.info(f"Found {stats['total_freight_rows']} total freight rows")
            
            # Count zero freight rows (only by original description = 'Freight' and amount = 0)
            zero_freight_query = db.query(InvoiceItem).filter(
                and_(
                    InvoiceItem.mpi_description == 'Freight',
                    or_(
                        InvoiceItem.amount == '0',
                        InvoiceItem.amount == '0.0',
                        InvoiceItem.amount == '0.00',
                        InvoiceItem.amount == '0.000',
                        InvoiceItem.amount == '',
                        InvoiceItem.amount.is_(None)
                    )
                )
            )
            stats['zero_freight_rows'] = zero_freight_query.count()
            logger.info(f"Found {stats['zero_freight_rows']} zero freight rows")
            
            if stats['zero_freight_rows'] == 0:
                logger.info("No zero freight rows found. Cleanup complete.")
                return stats
            
            # Process in batches
            offset = 0
            while offset < stats['zero_freight_rows']:
                batch_query = zero_freight_query.offset(offset).limit(batch_size)
                batch_items = batch_query.all()
                
                if not batch_items:
                    break
                
                stats['batches_processed'] += 1
                logger.info(f"Processing batch {stats['batches_processed']}: "
                          f"{len(batch_items)} items (offset: {offset})")
                
                for item in batch_items:
                    try:
                        # Double-check this is a freight row with zero amount
                        if (is_freight_row(item.mpi_description) and 
                            is_zero_amount(item.amount)):
                            
                            if verbose:
                                logger.debug(f"Found zero freight row: "
                                           f"ID={item.id}, Item='{item.item}', "
                                           f"MpiDescription='{item.mpi_description}', "
                                           f"Amount='{item.amount}', "
                                           f"InvoiceID={item.invoice_id}")
                            
                            if not dry_run:
                                db.delete(item)
                                stats['deleted_rows'] += 1
                            else:
                                stats['deleted_rows'] += 1
                                logger.debug(f"DRY RUN: Would delete freight row ID {item.id}")
                        else:
                            logger.warning(f"Row {item.id} doesn't match freight criteria: "
                                         f"MpiDescription='{item.mpi_description}', "
                                         f"Amount='{item.amount}'")
                    
                    except Exception as e:
                        logger.error(f"Error processing item {item.id}: {str(e)}")
                        stats['errors'] += 1
                
                # Commit batch if not dry run
                if not dry_run:
                    try:
                        db.commit()
                        logger.info(f"Batch {stats['batches_processed']} committed successfully")
                    except Exception as e:
                        logger.error(f"Error committing batch {stats['batches_processed']}: {str(e)}")
                        db.rollback()
                        stats['errors'] += 1
                
                offset += batch_size
            
            logger.info("="*80)
            logger.info("ZERO FREIGHT CLEANUP COMPLETED")
            logger.info("="*80)
            logger.info(f"Total freight rows found: {stats['total_freight_rows']}")
            logger.info(f"Zero freight rows found: {stats['zero_freight_rows']}")
            logger.info(f"Rows {'deleted' if not dry_run else 'would be deleted'}: {stats['deleted_rows']}")
            logger.info(f"Batches processed: {stats['batches_processed']}")
            logger.info(f"Errors encountered: {stats['errors']}")
            
            if dry_run:
                logger.info("DRY RUN COMPLETE - No actual changes were made")
            
            return stats
            
    except Exception as e:
        logger.error(f"Critical error in cleanup_zero_freight: {str(e)}")
        stats['errors'] += 1
        return stats


def main():
    """Main function with command line argument parsing"""
    parser = argparse.ArgumentParser(description='Cleanup zero freight rows from invoices')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Preview what would be deleted without making changes')
    parser.add_argument('--verbose', action='store_true', 
                       help='Enable detailed logging')
    parser.add_argument('--batch-size', type=int, default=1000,
                       help='Number of records to process per batch (default: 1000)')
    
    args = parser.parse_args()
    
    try:
        stats = cleanup_zero_freight(
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            verbose=args.verbose
        )
        
        # Exit with error code if there were errors
        if stats['errors'] > 0:
            logger.error(f"Cleanup completed with {stats['errors']} errors")
            return 1
        
        logger.info("Cleanup completed successfully")
        return 0
        
    except Exception as e:
        logger.error(f"Script failed: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
