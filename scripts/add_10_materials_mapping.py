"""
Script to create mapping for "10 Materials" item and update all invoice items.

This script:
1. Creates a new mapping in supplier_item_mappings table:
   - supplier_item_ids: "10 Materials"
   - mpi_code: "10 Materials"
   - description: "Tax"
   - google_sheet_name: "(TAX)"
   
2. Updates all invoice items with item = "10 Materials":
   - mpi_item: "10 Materials"
   - mpi_description: "Tax"
   - sheet_name: "(TAX)"

Usage:
    # Preview (dry run):
    python scripts/add_10_materials_mapping.py
    
    # Create mapping and update items:
    python scripts/add_10_materials_mapping.py --yes
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from sqlalchemy import func
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def check_existing_mapping(db):
    """Check if mapping for '10 Materials' already exists."""
    existing = db.query(ItemsMapping).filter(
        ItemsMapping.supplier_item_ids == "10 Materials"
    ).first()
    
    return existing


def create_mapping(db, dry_run=True):
    """Create the mapping for '10 Materials'."""
    logger.info("\n" + "=" * 100)
    logger.info("STEP 1: CREATE MAPPING IN DATABASE")
    logger.info("=" * 100)
    
    # Check if already exists
    existing = check_existing_mapping(db)
    
    if existing:
        logger.info("\n⚠️  Mapping already exists!")
        logger.info(f"  ID: {existing.id}")
        logger.info(f"  Supplier Item IDs: {existing.supplier_item_ids}")
        logger.info(f"  MPI Code: {existing.mpi_code}")
        logger.info(f"  Description: {existing.description}")
        logger.info(f"  Sheet Name: {existing.google_sheet_name}")
        logger.info(f"  Supplier ID: {existing.supplier_id}")
        logger.info("\nUsing existing mapping...")
        return existing
    
    # Create new mapping
    logger.info("\nCreating new mapping:")
    logger.info("  Supplier Item IDs: '10 Materials'")
    logger.info("  MPI Code: '10 Materials'")
    logger.info("  Description: 'Tax'")
    logger.info("  Sheet Name: '(TAX)'")
    
    if dry_run:
        logger.info("\nDRY RUN: Mapping would be created but not committed")
        return None
    else:
        new_mapping = ItemsMapping(
            supplier_item_ids="10 Materials",
            mpi_code="10 Materials",
            description="Tax",
            google_sheet_name="(TAX)",
            supplier_id=None,  # Generic mapping for all suppliers
            sheet_id=None  # Will be populated by sheet sync if needed
        )
        
        db.add(new_mapping)
        db.commit()
        db.refresh(new_mapping)
        
        logger.info(f"\n✅ Mapping created with ID: {new_mapping.id}")
        return new_mapping


def update_invoice_items(db, dry_run=True):
    """Update all invoice items with item = '10 Materials'."""
    logger.info("\n" + "=" * 100)
    logger.info("STEP 2: UPDATE INVOICE ITEMS")
    logger.info("=" * 100)
    
    # Find all invoice items with item = "10 Materials"
    items_to_update = db.query(InvoiceItem).execution_options(include_all=True).filter(
        InvoiceItem.item == "10 Materials"
    ).all()
    
    total_items = len(items_to_update)
    logger.info(f"\nFound {total_items:,} invoice items with item = '10 Materials'")
    
    if total_items == 0:
        logger.info("\n✅ No items to update")
        return {'total': 0, 'updated': 0, 'already_correct': 0}
    
    # Check current state
    already_correct = 0
    needs_update = 0
    
    for item in items_to_update:
        if (item.mpi_item == "10 Materials" and 
            item.mpi_description == "Tax" and 
            item.sheet_name == "(TAX)"):
            already_correct += 1
        else:
            needs_update += 1
    
    logger.info(f"\nCurrent state:")
    logger.info(f"  Already correct: {already_correct:,}")
    logger.info(f"  Need updating:   {needs_update:,}")
    
    if needs_update == 0:
        logger.info("\n✅ All items already have correct mapping")
        return {'total': total_items, 'updated': 0, 'already_correct': already_correct}
    
    # Show sample of items to be updated
    logger.info(f"\nSample of items to update (first 5):")
    for i, item in enumerate(items_to_update[:5], 1):
        logger.info(f"\n  Item {i}:")
        logger.info(f"    Current mpi_item: '{item.mpi_item}'")
        logger.info(f"    Current mpi_description: '{item.mpi_description}'")
        logger.info(f"    Current sheet_name: '{item.sheet_name}'")
        logger.info(f"    → Will update to: mpi_item='10 Materials', mpi_description='Tax', sheet_name='(TAX)'")
    
    if total_items > 5:
        logger.info(f"\n  ... and {total_items - 5:,} more items")
    
    if dry_run:
        logger.info(f"\nDRY RUN: {needs_update:,} items would be updated")
        return {'total': total_items, 'updated': needs_update, 'already_correct': already_correct}
    else:
        # Perform update
        updated_count = 0
        for item in items_to_update:
            if not (item.mpi_item == "10 Materials" and 
                    item.mpi_description == "Tax" and 
                    item.sheet_name == "(TAX)"):
                item.mpi_item = "10 Materials"
                item.mpi_description = "Tax"
                item.sheet_name = "(TAX)"
                updated_count += 1
        
        db.commit()
        logger.info(f"\n✅ Updated {updated_count:,} invoice items")
        return {'total': total_items, 'updated': updated_count, 'already_correct': already_correct}


def verify_updates(db):
    """Verify the updates were successful."""
    logger.info("\n" + "=" * 100)
    logger.info("VERIFICATION")
    logger.info("=" * 100)
    
    # Check mapping exists
    mapping = check_existing_mapping(db)
    if mapping:
        logger.info("\n✅ Mapping exists in database:")
        logger.info(f"  ID: {mapping.id}")
        logger.info(f"  Supplier Item IDs: {mapping.supplier_item_ids}")
        logger.info(f"  MPI Code: {mapping.mpi_code}")
        logger.info(f"  Description: {mapping.description}")
        logger.info(f"  Sheet Name: {mapping.google_sheet_name}")
    else:
        logger.warning("\n⚠️  Mapping not found in database")
    
    # Check invoice items
    total_items = db.query(InvoiceItem).execution_options(include_all=True).filter(
        InvoiceItem.item == "10 Materials"
    ).count()
    
    correct_items = db.query(InvoiceItem).execution_options(include_all=True).filter(
        InvoiceItem.item == "10 Materials",
        InvoiceItem.mpi_item == "10 Materials",
        InvoiceItem.mpi_description == "Tax",
        InvoiceItem.sheet_name == "(TAX)"
    ).count()
    
    logger.info(f"\n✅ Invoice items with '10 Materials':")
    logger.info(f"  Total: {total_items:,}")
    logger.info(f"  With correct mapping: {correct_items:,}")
    
    if total_items > 0 and correct_items == total_items:
        logger.info(f"\n✅ All items have correct mapping!")
    elif total_items > 0 and correct_items < total_items:
        logger.warning(f"\n⚠️  {total_items - correct_items:,} items still need updating")
    
    logger.info("=" * 100)


def main():
    parser = argparse.ArgumentParser(
        description='Create mapping for "10 Materials" and update invoice items'
    )
    parser.add_argument('--yes', action='store_true', 
                       help='Create mapping and update items (skip confirmation)')
    args = parser.parse_args()
    
    logger.info("\n" + "=" * 100)
    logger.info("ADD '10 MATERIALS' MAPPING AND UPDATE INVOICE ITEMS")
    logger.info("=" * 100)
    
    db = SessionLocal()
    
    try:
        if args.yes:
            # Live mode - create and update
            logger.info("\nLIVE MODE - Changes will be committed")
            
            # Step 1: Create mapping
            mapping = create_mapping(db, dry_run=False)
            
            # Step 2: Update invoice items
            stats = update_invoice_items(db, dry_run=False)
            
            # Step 3: Verify
            verify_updates(db)
            
            logger.info("\n" + "=" * 100)
            logger.info("✅ COMPLETE!")
            logger.info("=" * 100)
            logger.info(f"Mapping created for '10 Materials'")
            logger.info(f"Updated {stats['updated']:,} invoice items")
            logger.info("=" * 100 + "\n")
            
        else:
            # Dry run mode
            logger.info("\nDRY RUN MODE - No changes will be made")
            
            # Step 1: Check/preview mapping
            create_mapping(db, dry_run=True)
            
            # Step 2: Preview invoice item updates
            stats = update_invoice_items(db, dry_run=True)
            
            logger.info("\n" + "=" * 100)
            logger.info("DRY RUN COMPLETE")
            logger.info("=" * 100)
            logger.info(f"Would update {stats['updated']:,} invoice items")
            logger.info("\nTo proceed with changes, run:")
            logger.info("  python scripts/add_10_materials_mapping.py --yes")
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

