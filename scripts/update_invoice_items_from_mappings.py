"""
Script to mark invoice items as "No Match" if they don't exist in any mapping table.

LOGIC:
1. Check if item exists in supplier_item_mappings
   ✅ If found → LEAVE AS IS (no changes)
   
2. If not in supplier_item_mappings, check temporary_item_mappings
   ✅ If found → LEAVE AS IS (no changes)
   
3. If NOT in EITHER table
   ❌ Mark as "No Match" with empty sheet_name

IMPORTANT: This script ONLY updates items that have NO mapping!
- Items in supplier_item_mappings → LEFT AS IS (no changes)
- Items in temporary_item_mappings → LEFT AS IS (no changes)
- Items in NEITHER table → Marked as "No Match" + "No Match" + empty sheet_name

This ensures:
- ✅ Items with permanent mappings are NOT touched
- ✅ Items with temporary mappings are NOT touched
- ✅ Only truly unmatched items get marked "No Match"

Usage:
    # Dry run (preview only):
    python scripts/update_invoice_items_from_mappings.py
    
    # Live update (with confirmation):
    python scripts/update_invoice_items_from_mappings.py --confirm
    
    # Live update (skip confirmation):
    python scripts/update_invoice_items_from_mappings.py --yes
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
from sqlalchemy import func
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def build_mapping_cache(db):
    """Build a cache of all mappings for fast lookup."""
    logger.info("\n" + "=" * 100)
    logger.info("BUILDING MAPPING CACHE")
    logger.info("=" * 100)
    
    # Build permanent mappings cache
    # Key: (supplier_item_id, supplier_id) -> (mpi_code, description, sheet_name)
    permanent_cache = {}
    
    permanent_mappings = db.query(ItemsMapping).all()
    
    for mapping in permanent_mappings:
        # Split supplier_item_ids if multiple exist (comma-separated)
        item_ids = mapping.supplier_item_ids.split(',') if mapping.supplier_item_ids else []
        
        for item_id in item_ids:
            item_id = item_id.strip()
            if item_id:
                key = (item_id, mapping.supplier_id)
                # Include sheet_name in the cached data
                permanent_cache[key] = (
                    mapping.mpi_code, 
                    mapping.description,
                    mapping.google_sheet_name or ''
                )
    
    logger.info(f"Loaded {len(permanent_mappings)} permanent mappings")
    logger.info(f"Created {len(permanent_cache)} lookup keys (including split items)")
    
    # Build temporary mappings cache
    # Key: original_item -> (mpi_code, description, sheet_name)
    # Temporary items show as "No Match" but include sheet_name
    temp_cache = {}
    
    temp_mappings = db.query(TempItemMapping).all()
    
    for mapping in temp_mappings:
        if mapping.original_item:
            # Temporary mappings: No MPI code yet, but have sheet info
            temp_cache[mapping.original_item] = (
                'No Match',  # Temp items don't have MPI codes yet
                mapping.original_description or 'No Match',
                mapping.sheet_name or ''
            )
    
    logger.info(f"Loaded {len(temp_mappings)} temporary mappings")
    logger.info("=" * 100)
    
    return permanent_cache, temp_cache


def lookup_mapping(item_code, supplier_id, permanent_cache, temp_cache):
    """
    Look up mapping for an item.
    
    Returns:
        tuple: (mpi_code, description, sheet_name, mapping_type)
        - mapping_type: 'permanent', 'temporary', 'skip', or 'no_match'
        
    Logic:
        1. Check supplier_item_mappings first → If found, return 'skip' (leave as is)
        2. Check temporary_item_mappings → If found, return 'skip' (leave as is)
        3. Not in either → Return 'no_match' (mark as "No Match")
    """
    if not item_code:
        return (None, None, None, 'skip')  # Skip empty items
    
    # STEP 1: Check permanent mapping (with supplier_id)
    key = (item_code, supplier_id)
    if key in permanent_cache:
        # Found in supplier_item_mappings → LEAVE AS IS
        return (None, None, None, 'skip')
    
    # Check permanent mapping without supplier_id (match any supplier)
    for (cached_item, cached_supplier_id), (mpi_code, description, sheet_name) in permanent_cache.items():
        if cached_item == item_code:
            # Found in supplier_item_mappings → LEAVE AS IS
            return (None, None, None, 'skip')
    
    # STEP 2: Check temporary mapping
    if item_code in temp_cache:
        # Found in temporary_item_mappings → LEAVE AS IS
        return (None, None, None, 'skip')
    
    # STEP 3: Not in EITHER table - mark as No Match with empty sheet
    return ('No Match', 'No Match', '', 'no_match')


def update_invoice_items(db, permanent_cache, temp_cache, dry_run=True):
    """Update all invoice items based on current mappings."""
    logger.info("\n" + "=" * 100)
    logger.info("UPDATING INVOICE ITEMS")
    logger.info("=" * 100)
    
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
    else:
        logger.warning("LIVE MODE - Records will be UPDATED!")
    
    # Get all active invoice items
    logger.info("\nQuerying all invoice items...")
    invoice_items = db.query(InvoiceItem).execution_options(include_all=True).all()
    
    logger.info(f"Found {len(invoice_items):,} invoice items to process")
    
    # Statistics
    stats = {
        'total': len(invoice_items),
        'permanent_match': 0,
        'temporary_match': 0,
        'no_match': 0,
        'already_correct': 0,
        'updated': 0,
        'marked_no_match': 0
    }
    
    # Get supplier_id from invoice relationship
    logger.info("\nProcessing items...")
    
    for i, item in enumerate(invoice_items, 1):
        # Get supplier_id from the invoice
        supplier_id = None
        if item.invoice:
            supplier_id = item.invoice.supplier_id
        
        # Look up mapping (returns: mpi_code, description, sheet_name, mapping_type)
        mpi_code, description, sheet_name, mapping_type = lookup_mapping(
            item.item, 
            supplier_id, 
            permanent_cache, 
            temp_cache
        )
        
        # Track statistics
        if mapping_type == 'skip':
            # Item exists in supplier_item_mappings OR temporary_item_mappings
            # Count which one it's in for statistics
            key = (item.item, supplier_id)
            if key in permanent_cache or any(cached_item == item.item for (cached_item, _) in permanent_cache.keys()):
                stats['permanent_match'] += 1
            else:
                stats['temporary_match'] += 1
            
            # LEAVE AS IS - no changes
            stats['already_correct'] += 1
        elif mapping_type == 'no_match':
            # Item NOT in either table - mark as No Match
            stats['no_match'] += 1
            
            # Check if update is needed
            needs_update = (
                item.mpi_item != 'No Match' or 
                item.mpi_description != 'No Match' or
                item.sheet_name != ''
            )
            
            if needs_update:
                if not dry_run:
                    # Mark as No Match
                    item.mpi_item = 'No Match'
                    item.mpi_description = 'No Match'
                    item.sheet_name = ''
                
                stats['updated'] += 1
                stats['marked_no_match'] += 1
            else:
                stats['already_correct'] += 1
        
        # Progress indicator
        if i % 50000 == 0:
            logger.info(f"  Processed {i:,} / {len(invoice_items):,} items...")
    
    # Commit if not dry run
    if not dry_run:
        logger.info("\nCommitting changes...")
        db.commit()
        logger.info("✅ Changes committed to database")
    
    # Display statistics
    logger.info("\n" + "=" * 100)
    logger.info("STATISTICS")
    logger.info("=" * 100)
    logger.info(f"Total items processed:        {stats['total']:,}")
    logger.info(f"")
    logger.info(f"Mapping results:")
    logger.info(f"  ✅ In supplier_item_mappings:  {stats['permanent_match']:,} ({stats['permanent_match']/stats['total']*100:.1f}%)")
    logger.info(f"     → LEFT AS IS (no changes)")
    logger.info(f"  ✅ In temporary_item_mappings: {stats['temporary_match']:,} ({stats['temporary_match']/stats['total']*100:.1f}%)")
    logger.info(f"     → LEFT AS IS (no changes)")
    logger.info(f"  ❌ Not in EITHER table:        {stats['no_match']:,} ({stats['no_match']/stats['total']*100:.1f}%)")
    logger.info(f"     → Will be marked 'No Match' + empty sheet_name")
    logger.info(f"")
    logger.info(f"Update actions:")
    logger.info(f"  Already correct:            {stats['already_correct']:,}")
    logger.info(f"  Need updating:              {stats['updated']:,}")
    logger.info(f"    - Will mark as 'No Match': {stats['marked_no_match']:,}")
    logger.info("=" * 100)
    
    return stats


def verify_updates(db):
    """Verify the updates by checking distribution of mpi_item values."""
    logger.info("\n" + "=" * 100)
    logger.info("VERIFICATION - MPI_ITEM DISTRIBUTION")
    logger.info("=" * 100)
    
    # Get distribution of mpi_item values
    distribution = db.query(
        InvoiceItem.mpi_item,
        func.count(InvoiceItem.id).label('count')
    ).execution_options(include_all=True).group_by(
        InvoiceItem.mpi_item
    ).order_by(
        func.count(InvoiceItem.id).desc()
    ).limit(20).all()
    
    logger.info("\nTop 20 MPI items:")
    for mpi_item, count in distribution:
        display = mpi_item if mpi_item else '(NULL)'
        logger.info(f"  {count:8,} | {display}")
    
    # Count "No Match" items
    no_match_count = db.query(InvoiceItem).execution_options(include_all=True).filter(
        InvoiceItem.mpi_item == 'No Match'
    ).count()
    
    total = db.query(InvoiceItem).execution_options(include_all=True).count()
    
    logger.info(f"\n'No Match' items: {no_match_count:,} / {total:,} ({no_match_count/total*100:.1f}%)")
    logger.info("=" * 100)


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Update invoice items from current mappings')
    parser.add_argument('--yes', action='store_true', 
                       help='Skip confirmation and proceed with update')
    parser.add_argument('--confirm', action='store_true',
                       help='Enable confirmation prompt for update')
    args = parser.parse_args()
    
    logger.info("\n" + "=" * 100)
    logger.info("UPDATE INVOICE ITEMS FROM CURRENT MAPPINGS")
    logger.info("=" * 100)
    
    db = SessionLocal()
    
    try:
        # Build mapping cache
        permanent_cache, temp_cache = build_mapping_cache(db)
        
        # Run in DRY RUN mode first
        stats = update_invoice_items(db, permanent_cache, temp_cache, dry_run=True)
        
        # Ask for confirmation
        if stats['updated'] > 0:
            logger.info("\n" + "=" * 100)
            logger.info(f"CONFIRMATION REQUIRED")
            logger.info("=" * 100)
            logger.info(f"This will mark {stats['updated']:,} invoice items as 'No Match'")
            logger.info(f"  - These items are NOT in supplier_item_mappings")
            logger.info(f"  - AND NOT in temporary_item_mappings")
            logger.info(f"\nItems that will be LEFT AS IS:")
            logger.info(f"  - {stats['permanent_match']:,} items in supplier_item_mappings")
            logger.info(f"  - {stats['temporary_match']:,} items in temporary_item_mappings")
            
            # Determine if we should proceed
            should_proceed = False
            
            if args.yes:
                logger.info("\n--yes flag provided, proceeding with update...")
                should_proceed = True
            elif args.confirm:
                try:
                    response = input("\nDo you want to UPDATE these records? (yes/no): ")
                    should_proceed = response.lower() == 'yes'
                except EOFError:
                    logger.error("\nCannot read input in non-interactive mode. Use --yes flag.")
                    should_proceed = False
            else:
                logger.info("\nDRY RUN COMPLETE - No changes made")
                logger.info("To proceed with update, use:")
                logger.info("  --confirm  (with confirmation prompt)")
                logger.info("  --yes      (skip confirmation)")
            
            if should_proceed:
                logger.info("\nProceeding with LIVE update...")
                update_invoice_items(db, permanent_cache, temp_cache, dry_run=False)
                
                # Verify updates
                verify_updates(db)
                
                logger.info("\n✅ UPDATE COMPLETE!")
            elif args.confirm or args.yes:
                logger.info("\n❌ UPDATE CANCELLED - No changes made")
        else:
            logger.info("\n✅ All invoice items are already up to date!")
        
        logger.info("=" * 100 + "\n")
        
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()

