"""
Script to remove database mappings that don't exist in the JSON files.

This script:
1. Loads all mappings from mapping_export.json (or MAPPING_OUTPUT_FILE) and temp-item-mapping.json
2. Queries all mappings from the database
3. Removes database records that are NOT in the JSON files

Usage:
    cd mpi-backend
    conda activate mpi-backend
    python scripts/cleanup_mappings_not_in_json.py
"""

import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
from mpi_backend.config.spreadsheet_config import DEFAULT_OUTPUT_FILE
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def load_json_mappings():
    """Load all mappings from JSON files."""
    logger.info("\n" + "=" * 100)
    logger.info("LOADING JSON FILES")
    logger.info("=" * 100)

    item_mapping_path = DEFAULT_OUTPUT_FILE
    temp_mapping_path = 'mpi_backend/storage/fixtures/temp-item-mapping.json'
    
    permanent_mappings = []
    temporary_mappings = []
    
    # Load permanent mappings
    if os.path.exists(item_mapping_path):
        with open(item_mapping_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'permanent_mappings' in data:
                permanent_mappings = data['permanent_mappings']
        logger.info(f"Loaded {len(permanent_mappings)} permanent mappings from JSON")
    else:
        logger.warning(f"File not found: {item_mapping_path}")
    
    # Load temporary mappings
    if os.path.exists(temp_mapping_path):
        with open(temp_mapping_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'temporary_mappings' in data:
                temporary_mappings = data['temporary_mappings']
        logger.info(f"Loaded {len(temporary_mappings)} temporary mappings from JSON")
    else:
        logger.warning(f"File not found: {temp_mapping_path}")
    
    return permanent_mappings, temporary_mappings


def create_mapping_keys(permanent_mappings, temporary_mappings):
    """Create unique keys for each mapping to compare with database."""
    logger.info("\n" + "=" * 100)
    logger.info("CREATING MAPPING KEYS")
    logger.info("=" * 100)
    
    # For permanent mappings: (mpi_code, supplier_id, supplier_item_ids)
    permanent_keys = set()
    for mapping in permanent_mappings:
        key = (
            mapping.get('mpi_code'),
            mapping.get('supplier_id'),
            mapping.get('supplier_item_ids')
        )
        if all(key):  # Only add if all parts are present
            permanent_keys.add(key)
    
    logger.info(f"Created {len(permanent_keys)} unique keys from permanent mappings")
    
    # For temporary mappings: (original_item, sheet_name)
    temporary_keys = set()
    for mapping in temporary_mappings:
        key = (
            mapping.get('original_item'),
            mapping.get('sheet_name')
        )
        if all(key):  # Only add if all parts are present
            temporary_keys.add(key)
    
    logger.info(f"Created {len(temporary_keys)} unique keys from temporary mappings")
    
    return permanent_keys, temporary_keys


def cleanup_database(db, permanent_keys, temporary_keys, dry_run=True):
    """Remove mappings from database that are not in JSON files."""
    logger.info("\n" + "=" * 100)
    logger.info("CLEANING UP DATABASE")
    logger.info("=" * 100)
    
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
    else:
        logger.warning("LIVE MODE - Records will be DELETED!")
    
    # Check permanent mappings
    logger.info("\nChecking supplier_item_mappings...")
    supplier_records = db.query(ItemsMapping).all()
    records_to_delete = []
    
    for record in supplier_records:
        key = (record.mpi_code, record.supplier_id, record.supplier_item_ids)
        if key not in permanent_keys:
            records_to_delete.append(record)
    
    logger.info(f"Found {len(records_to_delete)} records NOT in JSON (out of {len(supplier_records)} total)")
    
    if records_to_delete:
        logger.info("\nSample records to be deleted (first 10):")
        for i, record in enumerate(records_to_delete[:10], 1):
            logger.info(f"  {i}. MPI: {record.mpi_code}, Supplier: {record.supplier_id}, "
                       f"Item: {record.supplier_item_ids}, Sheet: {record.google_sheet_name}")
    
    # Check temporary mappings
    logger.info("\nChecking temporary_item_mappings...")
    temp_records = db.query(TempItemMapping).all()
    temp_records_to_delete = []
    
    for record in temp_records:
        key = (record.original_item, record.sheet_name)
        if key not in temporary_keys:
            temp_records_to_delete.append(record)
    
    logger.info(f"Found {temp_records_to_delete.__len__()} temp records NOT in JSON "
                f"(out of {len(temp_records)} total)")
    
    if temp_records_to_delete:
        logger.info("\nSample temp records to be deleted (first 10):")
        for i, record in enumerate(temp_records_to_delete[:10], 1):
            logger.info(f"  {i}. Original: {record.original_item}, Sheet: {record.sheet_name}")
    
    # Delete if not dry run
    if not dry_run:
        logger.info("\n" + "=" * 100)
        logger.info("DELETING RECORDS...")
        logger.info("=" * 100)
        
        deleted_count = 0
        for record in records_to_delete:
            db.delete(record)
            deleted_count += 1
        
        temp_deleted_count = 0
        for record in temp_records_to_delete:
            db.delete(record)
            temp_deleted_count += 1
        
        db.commit()
        
        logger.info(f"\n✅ Deleted {deleted_count} supplier mappings")
        logger.info(f"✅ Deleted {temp_deleted_count} temporary mappings")
    
    return len(records_to_delete), len(temp_records_to_delete)


def main():
    logger.info("\n" + "=" * 100)
    logger.info("CLEANUP MAPPINGS NOT IN JSON FILES")
    logger.info("=" * 100)
    
    # Load JSON mappings
    permanent_mappings, temporary_mappings = load_json_mappings()
    
    # Create mapping keys
    permanent_keys, temporary_keys = create_mapping_keys(permanent_mappings, temporary_mappings)
    
    # Connect to database
    db = SessionLocal()
    
    try:
        # First run in DRY RUN mode
        supplier_to_delete, temp_to_delete = cleanup_database(db, permanent_keys, temporary_keys, dry_run=True)
        
        # Ask for confirmation
        logger.info("\n" + "=" * 100)
        logger.info("SUMMARY")
        logger.info("=" * 100)
        logger.info(f"Records to delete from supplier_item_mappings: {supplier_to_delete}")
        logger.info(f"Records to delete from temporary_item_mappings: {temp_to_delete}")
        logger.info(f"Total records to delete: {supplier_to_delete + temp_to_delete}")
        
        if supplier_to_delete > 0 or temp_to_delete > 0:
            logger.info("\n" + "=" * 100)
            response = input("\nDo you want to DELETE these records? (yes/no): ")
            
            if response.lower() == 'yes':
                cleanup_database(db, permanent_keys, temporary_keys, dry_run=False)
                logger.info("\n✅ CLEANUP COMPLETE!")
            else:
                logger.info("\n❌ CLEANUP CANCELLED - No changes made")
        else:
            logger.info("\n✅ All database records are present in JSON files - Nothing to delete!")
        
        logger.info("=" * 100 + "\n")
        
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()

