"""
Script to query supplier item mappings in the database.

This script searches for mappings by supplier item IDs and shows all matching records.

Usage:
    cd mpi-backend
    conda activate mpi-backend
    python scripts/query_supplier_item_mapping.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
from sqlalchemy import or_
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def query_supplier_item(db, supplier_item_id):
    """Query for a specific supplier item ID."""
    logger.info("\n" + "=" * 100)
    logger.info(f"SEARCHING FOR: {supplier_item_id}")
    logger.info("=" * 100)
    
    # Search in supplier_item_mappings
    logger.info("\n1. Searching in supplier_item_mappings...")
    
    # Try exact match
    exact_matches = db.query(ItemsMapping).filter(
        ItemsMapping.supplier_item_ids == supplier_item_id
    ).all()
    
    # Try partial match (contains)
    partial_matches = db.query(ItemsMapping).filter(
        ItemsMapping.supplier_item_ids.ilike(f"%{supplier_item_id}%")
    ).all()
    
    # Remove duplicates (items in exact_matches that are also in partial_matches)
    partial_only = [m for m in partial_matches if m not in exact_matches]
    
    if exact_matches:
        logger.info(f"\n✅ Found {len(exact_matches)} EXACT match(es):")
        for i, mapping in enumerate(exact_matches, 1):
            logger.info(f"\n  Match {i}:")
            logger.info(f"    ID: {mapping.id}")
            logger.info(f"    MPI Code: {mapping.mpi_code}")
            logger.info(f"    Description: {mapping.description}")
            logger.info(f"    Supplier ID: {mapping.supplier_id}")
            logger.info(f"    Supplier Item IDs: {mapping.supplier_item_ids}")
            logger.info(f"    Sheet Name: {mapping.google_sheet_name}")
            logger.info(f"    Sheet ID: {mapping.sheet_id}")
    else:
        logger.info("  ❌ No exact matches found")
    
    if partial_only:
        logger.info(f"\n🔍 Found {len(partial_only)} PARTIAL match(es) (contains the search term):")
        for i, mapping in enumerate(partial_only, 1):
            logger.info(f"\n  Match {i}:")
            logger.info(f"    ID: {mapping.id}")
            logger.info(f"    MPI Code: {mapping.mpi_code}")
            logger.info(f"    Description: {mapping.description}")
            logger.info(f"    Supplier ID: {mapping.supplier_id}")
            logger.info(f"    Supplier Item IDs: {mapping.supplier_item_ids}")
            logger.info(f"    Sheet Name: {mapping.google_sheet_name}")
            logger.info(f"    Sheet ID: {mapping.sheet_id}")
    elif not exact_matches:
        logger.info("  ❌ No partial matches found either")
    
    # Search in temporary_item_mappings
    logger.info("\n2. Searching in temporary_item_mappings...")
    
    temp_matches = db.query(TempItemMapping).filter(
        or_(
            TempItemMapping.original_item == supplier_item_id,
            TempItemMapping.original_item.ilike(f"%{supplier_item_id}%")
        )
    ).all()
    
    if temp_matches:
        logger.info(f"\n✅ Found {len(temp_matches)} match(es) in temporary mappings:")
        for i, mapping in enumerate(temp_matches, 1):
            logger.info(f"\n  Match {i}:")
            logger.info(f"    ID: {mapping.id}")
            logger.info(f"    Original Item: {mapping.original_item}")
            logger.info(f"    Original Description: {mapping.original_description}")
            logger.info(f"    Sheet Name: {mapping.sheet_name}")
            logger.info(f"    Sheet ID: {mapping.sheet_id}")
            logger.info(f"    Created At: {mapping.created_at}")
            logger.info(f"    Updated At: {mapping.updated_at}")
    else:
        logger.info("  ❌ No matches found in temporary mappings")
    
    # Summary
    total_found = len(exact_matches) + len(partial_only) + len(temp_matches)
    
    logger.info("\n" + "-" * 100)
    logger.info("SUMMARY:")
    logger.info(f"  Exact matches in supplier_item_mappings: {len(exact_matches)}")
    logger.info(f"  Partial matches in supplier_item_mappings: {len(partial_only)}")
    logger.info(f"  Matches in temporary_item_mappings: {len(temp_matches)}")
    logger.info(f"  Total matches: {total_found}")
    
    if total_found == 0:
        logger.info(f"\n❌ NO MAPPING FOUND for '{supplier_item_id}'")
    else:
        logger.info(f"\n✅ MAPPING(S) FOUND for '{supplier_item_id}'")
    
    logger.info("=" * 100)
    
    return total_found


def main():
    logger.info("\n" + "=" * 100)
    logger.info("SUPPLIER ITEM MAPPING QUERY TOOL")
    logger.info("=" * 100)
    
    # Connect to database
    db = SessionLocal()
    
    try:
        # Query specific supplier item IDs
        supplier_items = [
            "SP*00011889-W",
            "LC110-50DWB2-UM-W"
        ]
        
        total_results = 0
        
        for supplier_item in supplier_items:
            results = query_supplier_item(db, supplier_item)
            total_results += results
        
        # Final summary
        logger.info("\n" + "=" * 100)
        logger.info("FINAL SUMMARY")
        logger.info("=" * 100)
        logger.info(f"Items searched: {len(supplier_items)}")
        logger.info(f"Total matches found: {total_results}")
        
        if total_results == 0:
            logger.info("\n❌ No mappings found for any of the searched items")
        else:
            logger.info(f"\n✅ Found mappings for the searched items")
        
        logger.info("=" * 100 + "\n")
        
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()

