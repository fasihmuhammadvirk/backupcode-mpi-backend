#!/usr/bin/env python3
"""
Fix Invoice Item Duplicates Script
==================================

This script identifies and fixes duplicate InvoiceItem records that are causing
duplicates to appear in the web interface. It keeps the most recent record
and deletes older duplicates.

Usage:
    python scripts/fix_invoice_item_duplicates.py [options]

Options:
    --dry-run               Preview what would be deleted without actually deleting
    --supplier TEXT         Filter by specific supplier name
    --ref-no TEXT           Fix specific invoice number
    --verbose               Enable detailed logging
    --confirm               Skip confirmation prompt
"""

import sys
import os
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Any
from collections import defaultdict
from pathlib import Path

# Add the parent directory to the path so we can import mpi_backend
sys.path.append(str(Path(__file__).parent.parent))

from mpi_backend.config.logging_config import setup_logging
from mpi_backend.database import get_db
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.Invoice import Invoice
from mpi_backend.database.models.Suppliers import Supplier
from sqlalchemy.orm import joinedload

# Setup centralized logging
setup_logging()
logger = logging.getLogger(__name__)


class InvoiceItemDuplicateFixer:
    """Fixer for duplicate InvoiceItem records"""
    
    def __init__(self, dry_run=False, supplier_filter=None, verbose=False):
        self.dry_run = dry_run
        self.supplier_filter = supplier_filter
        self.verbose = verbose
        
        # Statistics tracking
        self.stats = {
            'total_items': 0,
            'duplicate_groups': 0,
            'items_to_delete': 0,
            'items_deleted': 0,
            'errors': 0
        }
        
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
    
    def find_duplicate_invoice_items(self, db, ref_no=None) -> Dict[tuple, List[InvoiceItem]]:
        """
        Find duplicate invoice items based on (ref_no, vendor, amount, date)
        
        Returns:
            Dict with (ref_no, vendor, amount, date) as key and list of items as value
        """
        try:
            logger.info("Searching for duplicate invoice items...")
            
            # Build query
            query = db.query(InvoiceItem).options(
                joinedload(InvoiceItem.invoice).joinedload(Invoice.supplier_fk)
            )
            
            # Apply filters
            if ref_no:
                query = query.filter(InvoiceItem.ref_no == ref_no)
                logger.info(f"Filtering by ref_no: {ref_no}")
            
            if self.supplier_filter:
                query = query.join(Invoice).join(Supplier).filter(
                    Supplier.supplier_name.ilike(f"%{self.supplier_filter}%")
                )
                logger.info(f"Filtering by supplier: {self.supplier_filter}")
            
            # Get all invoice items
            invoice_items = query.all()
            self.stats['total_items'] = len(invoice_items)
            
            logger.info(f"Found {len(invoice_items)} total invoice items")
            
            # Group by (ref_no, vendor, amount, date)
            duplicate_groups = defaultdict(list)
            for item in invoice_items:
                if item.ref_no and item.vendor and item.amount and item.date:
                    # Normalize values for comparison
                    ref_no_str = str(item.ref_no).strip()
                    vendor_str = str(item.vendor).strip()
                    amount_str = str(item.amount).strip()
                    date_str = str(item.date)
                    
                    key = (ref_no_str, vendor_str, amount_str, date_str)
                    duplicate_groups[key].append(item)
            
            # Filter to only groups with duplicates
            duplicate_groups = {
                key: items_list 
                for key, items_list in duplicate_groups.items() 
                if len(items_list) > 1
            }
            
            self.stats['duplicate_groups'] = len(duplicate_groups)
            
            logger.info(f"Found {len(duplicate_groups)} duplicate invoice item groups")
            
            return duplicate_groups
            
        except Exception as e:
            logger.error(f"Error finding duplicate invoice items: {str(e)}")
            self.stats['errors'] += 1
            return {}
    
    def analyze_duplicates(self, db, duplicate_groups: Dict[tuple, List[InvoiceItem]]) -> List[Dict[str, Any]]:
        """
        Analyze duplicate groups and determine which to keep/delete
        
        Returns:
            List of analysis results for each duplicate group
        """
        analysis_results = []
        
        for (ref_no, vendor, amount, date), items in duplicate_groups.items():
            try:
                # Sort by date_added (most recent first), then by ID
                sorted_items = sorted(
                    items, 
                    key=lambda item: (item.date_added or datetime.min, item.id),
                    reverse=True
                )
                
                # Keep the most recent (first after sorting)
                keep_item = sorted_items[0]
                delete_items = sorted_items[1:]
                
                analysis_result = {
                    'ref_no': ref_no,
                    'vendor': vendor,
                    'amount': amount,
                    'date': date,
                    'keep_item': keep_item,
                    'delete_items': delete_items,
                    'invoice_id': keep_item.invoice_id
                }
                
                analysis_results.append(analysis_result)
                
                # Update statistics
                self.stats['items_to_delete'] += len(delete_items)
                
                if self.verbose:
                    logger.debug(f"Duplicate group: {ref_no}")
                    logger.debug(f"  Keep: Item {keep_item.id} "
                               f"({keep_item.date_added}) - {keep_item.vendor}")
                    for delete_item in delete_items:
                        logger.debug(f"  Delete: Item {delete_item.id} "
                                   f"({delete_item.date_added})")
                
            except Exception as e:
                logger.error(f"Error analyzing duplicates for {ref_no}: {str(e)}")
                self.stats['errors'] += 1
                continue
        
        return analysis_results
    
    def delete_duplicates(self, db, analysis_results: List[Dict[str, Any]]) -> bool:
        """
        Delete duplicate invoice items
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Starting deletion of {len(analysis_results)} duplicate groups...")
            
            for analysis in analysis_results:
                try:
                    ref_no = analysis['ref_no']
                    delete_items = analysis['delete_items']
                    keep_item = analysis['keep_item']
                    
                    logger.info(f"Processing duplicates for: {ref_no}")
                    logger.info(f"  Keeping: Item {keep_item.id} "
                               f"({keep_item.date_added}) - {keep_item.vendor}")
                    logger.info(f"  Deleting: {len(delete_items)} duplicate items")
                    
                    if self.dry_run:
                        logger.info(f"[DRY RUN] Would delete {len(delete_items)} duplicate items")
                        continue
                    
                    # Delete the duplicate items
                    for delete_item in delete_items:
                        db.delete(delete_item)
                        self.stats['items_deleted'] += 1
                        logger.debug(f"  Deleted invoice item {delete_item.id}")
                    
                    # Commit after each group to avoid large transactions
                    db.commit()
                    logger.info(f"  Successfully deleted duplicates for {ref_no}")
                    
                except Exception as e:
                    logger.error(f"Error deleting duplicates for {analysis['ref_no']}: {str(e)}")
                    db.rollback()
                    self.stats['errors'] += 1
                    continue
            
            logger.info("Duplicate deletion completed")
            return True
            
        except Exception as e:
            logger.error(f"Error in delete_duplicates: {str(e)}")
            self.stats['errors'] += 1
            return False
    
    def print_analysis(self, analysis_results: List[Dict[str, Any]]):
        """Print analysis of duplicates"""
        print("\n" + "="*80)
        print("INVOICE ITEM DUPLICATE ANALYSIS")
        print("="*80)
        
        if not analysis_results:
            print("✅ No duplicate invoice items found!")
            return
        
        print(f"Found {len(analysis_results)} duplicate groups:")
        print()
        
        for i, analysis in enumerate(analysis_results, 1):
            ref_no = analysis['ref_no']
            keep_item = analysis['keep_item']
            delete_count = len(analysis['delete_items'])
            vendor = analysis['vendor']
            amount = analysis['amount']
            date = analysis['date']
            
            print(f"{i}. Ref No: {ref_no}")
            print(f"   Vendor: {vendor}")
            print(f"   Amount: {amount}")
            print(f"   Date: {date}")
            print(f"   Keep: Item {keep_item.id} ({keep_item.date_added})")
            print(f"   Delete: {delete_count} duplicate items")
            print()
        
        print("="*80)
        print("SUMMARY:")
        print(f"  Total invoice items to keep: {len(analysis_results)}")
        print(f"  Total invoice items to delete: {self.stats['items_to_delete']}")
        print("="*80)
    
    def print_summary(self):
        """Print summary of the operation"""
        print("\n" + "="*60)
        print("INVOICE ITEM DUPLICATE FIX SUMMARY")
        print("="*60)
        print(f"Total invoice items scanned: {self.stats['total_items']:,}")
        print(f"Duplicate groups found:      {self.stats['duplicate_groups']:,}")
        print(f"Invoice items deleted:       {self.stats['items_deleted']:,}")
        print(f"Errors:                      {self.stats['errors']:,}")
        print("="*60)
        
        if self.dry_run:
            print("⚠️  DRY RUN MODE - No actual deletions performed")
        else:
            print("✅ Duplicate cleanup completed successfully")
        print("="*60)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Fix duplicate invoice item records",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview duplicates without deleting
  python scripts/fix_invoice_item_duplicates.py --dry-run
  
  # Fix duplicates for all suppliers
  python scripts/fix_invoice_item_duplicates.py --confirm
  
  # Fix duplicates for specific supplier
  python scripts/fix_invoice_item_duplicates.py --supplier "Y & S Plumbing Supply" --confirm
  
  # Fix specific invoice number
  python scripts/fix_invoice_item_duplicates.py --ref-no "151253" --confirm
  
  # Verbose mode with confirmation
  python scripts/fix_invoice_item_duplicates.py --verbose --confirm
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what would be deleted without actually deleting'
    )
    parser.add_argument(
        '--supplier',
        type=str,
        help='Filter by specific supplier name'
    )
    parser.add_argument(
        '--ref-no',
        type=str,
        help='Fix specific invoice number'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable detailed logging'
    )
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Skip confirmation prompt'
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    print("🔧 Invoice Item Duplicate Fixer")
    print("="*50)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No actual deletions will be performed")
    else:
        print("⚠️  WARNING: This will permanently delete duplicate invoice items!")
        print("   Only the most recent items will be kept.")
        
        if not args.confirm:
            confirmation = input(
                "\nAre you sure you want to continue? (y/N): "
            )
            if confirmation.lower() != 'y':
                print("Operation cancelled.")
                return 0
    
    # Create fixer and run
    try:
        fixer = InvoiceItemDuplicateFixer(
            dry_run=args.dry_run,
            supplier_filter=args.supplier,
            verbose=args.verbose
        )
        
        # Get database session
        db = next(get_db())
        
        try:
            # Find duplicates
            duplicate_groups = fixer.find_duplicate_invoice_items(db, args.ref_no)
            
            if duplicate_groups:
                # Analyze duplicates
                analysis_results = fixer.analyze_duplicates(db, duplicate_groups)
                
                # Print analysis
                fixer.print_analysis(analysis_results)
                
                if not args.dry_run:
                    # Perform deletion
                    success = fixer.delete_duplicates(db, analysis_results)
                    if not success:
                        print("\n❌ Duplicate cleanup failed!")
                        return 1
            else:
                print("✅ No duplicate invoice items found!")
            
            if args.dry_run:
                print("🔍 Dry run completed. Use --confirm to perform actual deletion.")
                return 0
            
            # Print final summary
            fixer.print_summary()
            print("\n✅ Duplicate cleanup completed successfully!")
                
        finally:
            db.close()
            
    except KeyboardInterrupt:
        print("\n⚠️  Operation interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        print(f"\n❌ Critical error: {str(e)}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main()) 