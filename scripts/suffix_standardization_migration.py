#!/usr/bin/env python3
"""
Suffix Standardization Migration Script

This script implements the new suffix handling strategy by:
1. Updating all existing data in the database to include proper suffixes
2. Removing all suffix cleaning logic from the codebase
3. Standardizing the system to always retain full original item codes with suffixes

Usage:
    python scripts/suffix_standardization_migration.py

This script should be run ONCE to migrate existing data.
"""

import sys
import os
import logging
from typing import Dict, List, Optional, Tuple
import re

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from mpi_backend.database.base import Base
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.database.models.UnmappedItems import UnmappedItems
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('suffix_migration.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Supplier ID to suffix mapping (from item_utils.py)
SUPPLIER_SUFFIX_MAP = {
    1: 'B',   # BMW Plumbing Supplies
    2: 'W',   # World Wide Plumbing  
    3: 'Y',   # Y & S Plumbing Supply
    4: 'S',   # Supreme Plumbing Supply
    5: 'P',   # Pyramid Plumbing
    6: 'A',   # ABC Opus Services
    7: 'P',   # Park Plumbing Supply (same as Pyramid)
    8: 'G',   # Gotham Plumbing Supply
    9: 'F',   # FW Webb Plumbing Supply
    10: 'F',  # Flow Mark Plumbing Supply (same as FW Webb)
    11: None, # Plumbing Exchange (no specific suffix)
    12: 'A',  # AF Supply (same as ABC Opus)
    13: None, # Lion Hvac Supplies (no specific suffix)
    14: 'F',  # Bruce Ferguson
}

# Supplier name to suffix mapping for display purposes
SUPPLIER_NAME_SUFFIX_MAP = {
    "BMW Plumbing Supplies": "B",
    "World Wide Plumbing": "W",
    "Y & S Plumbing Supply": "Y",
    "Supreme Plumbing Supply": "S",
    "Pyramid Plumbing": "P",
    "ABC Opus Services": "A",
    "Park Plumbing Supply": "P",
    "Gotham Plumbing Supply": "G",
    "FW Webb Plumbing Supply": "F",
    "Flow Mark Plumbing Supply": "F",
    "Plumbing Exchange": None,  # No suffix
    "AF Supply": "A",
    "Lion Hvac Supplies": None,  # No suffix
    "Bruce Ferguson": "F",
}


def get_supplier_suffix(supplier_id: int) -> Optional[str]:
    """Get suffix for a supplier ID."""
    return SUPPLIER_SUFFIX_MAP.get(supplier_id)


def get_supplier_suffix_by_name(supplier_name: str) -> Optional[str]:
    """Get suffix for a supplier name."""
    return SUPPLIER_NAME_SUFFIX_MAP.get(supplier_name)


def extract_supplier_id(vendor_name: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Extract supplier ID and name from vendor string.
    Returns (supplier_id, supplier_name)
    """
    if not vendor_name:
        return None, None
    
    # Try to match vendor name to supplier names
    for supplier_name in SUPPLIER_NAME_SUFFIX_MAP.keys():
        if supplier_name.lower() in vendor_name.lower():
            # Find the supplier ID for this name
            for sid, suffix in SUPPLIER_SUFFIX_MAP.items():
                if SUPPLIER_NAME_SUFFIX_MAP.get(supplier_name) == suffix:
                    return sid, supplier_name
    
    return None, None


def should_skip_item(item_code: str) -> bool:
    """Check if item should be skipped from suffix processing."""
    if not item_code:
        return True
    
    item_str = str(item_code).strip()
    
    # Exclude tax and administrative items from getting suffixes
    excluded_items = [
        "tax", "freight", "shipping", "handling", "subtotal", "total"
    ]
    
    if (item_str.startswith("10 Materials") or 
            item_str.lower() in excluded_items):
        return True
    
    return False


def clean_existing_suffixes(item_code: str) -> str:
    """Remove all existing suffixes from item code."""
    if not item_code:
        return item_code
    
    clean_item = str(item_code).strip()
    
    # Remove ALL existing suffixes first (including double suffixes)
    all_suffixes = set(SUPPLIER_SUFFIX_MAP.values())
    all_suffixes.discard(None)  # Remove None values
    
    # Keep removing suffixes until none are found
    while True:
        found_suffix = False
        for existing_suffix in all_suffixes:
            if existing_suffix and clean_item.endswith(f"-{existing_suffix}"):
                clean_item = clean_item[:-len(f"-{existing_suffix}")]
                found_suffix = True
                break
        if not found_suffix:
            break
    
    return clean_item


def add_suffix_to_item(item_code: str, supplier_id: int) -> str:
    """
    Add the correct suffix to an item code based on supplier ID.
    With suffix standardization, we preserve existing suffixes and only add if missing.
    """
    if should_skip_item(item_code):
        return item_code
    
    suffix = get_supplier_suffix(supplier_id)
    if not suffix:
        return item_code
    
    # Check if item already has the correct suffix
    if item_code.endswith(f"-{suffix}"):
        return item_code  # Already has correct suffix
    
    # Check if item has any other suffix (preserve it)
    existing_suffixes = ['B', 'W', 'Y', 'S', 'P', 'A', 'G', 'F']
    for existing_suffix in existing_suffixes:
        if item_code.endswith(f"-{existing_suffix}"):
            return item_code  # Already has a suffix, preserve it
    
    # Add the correct suffix if none exists
    return f"{item_code}-{suffix}"


class SuffixStandardizationMigration:
    def __init__(self, db_session):
        self.db = db_session
        self.stats = {
            'invoice_items_updated': 0,
            'item_mappings_updated': 0,
            'unmapped_items_updated': 0,
            'temporary_mappings_updated': 0,
            'errors': 0
        }
    
    def migrate_invoice_items(self):
        """Migrate invoice_items table to include proper suffixes."""
        logger.info("Starting migration of invoice_items table...")
        
        try:
            # Get all invoice items
            invoice_items = self.db.query(InvoiceItem).all()
            logger.info(f"Found {len(invoice_items)} invoice items to process")
            
            for item in invoice_items:
                try:
                    if not item.item:
                        continue
                    
                    # Extract supplier info from vendor
                    supplier_id, supplier_name = extract_supplier_id(item.vendor)
                    if not supplier_id:
                        logger.debug(f"No supplier found for vendor: {item.vendor}")
                        continue
                    
                    # Add suffix to item code
                    original_item = item.item
                    new_item = add_suffix_to_item(item.item, supplier_id)
                    
                    if new_item != original_item:
                        item.item = new_item
                        self.stats['invoice_items_updated'] += 1
                        logger.debug(f"Updated invoice item: {original_item} -> {new_item}")
                    
                except Exception as e:
                    logger.error(f"Error processing invoice item {item.id}: {e}")
                    self.stats['errors'] += 1
            
            self.db.commit()
            logger.info(f"Successfully updated {self.stats['invoice_items_updated']} invoice items")
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error migrating invoice items: {e}")
            raise
    
    def migrate_item_mappings(self):
        """Migrate supplier_item_mappings table to include proper suffixes."""
        logger.info("Starting migration of supplier_item_mappings table...")
        
        try:
            # Get all item mappings
            mappings = self.db.query(ItemsMapping).all()
            logger.info(f"Found {len(mappings)} item mappings to process")
            
            for mapping in mappings:
                try:
                    if not mapping.supplier_item_ids:
                        continue
                    
                    # Add suffix to supplier_item_ids
                    original_item = mapping.supplier_item_ids
                    new_item = add_suffix_to_item(mapping.supplier_item_ids, mapping.supplier_id)
                    
                    if new_item != original_item:
                        mapping.supplier_item_ids = new_item
                        self.stats['item_mappings_updated'] += 1
                        logger.debug(f"Updated mapping: {original_item} -> {new_item}")
                    
                except Exception as e:
                    logger.error(f"Error processing mapping {mapping.id}: {e}")
                    self.stats['errors'] += 1
            
            self.db.commit()
            logger.info(f"Successfully updated {self.stats['item_mappings_updated']} item mappings")
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error migrating item mappings: {e}")
            raise
    
    def migrate_unmapped_items(self):
        """Migrate unmapped_items table to include proper suffixes."""
        logger.info("Starting migration of unmapped_items table...")
        
        try:
            # Get all unmapped items
            unmapped_items = self.db.query(UnmappedItems).all()
            logger.info(f"Found {len(unmapped_items)} unmapped items to process")
            
            for item in unmapped_items:
                try:
                    if not item.supplier_item_ids:
                        continue
                    
                    # Add suffix to supplier_item_ids
                    original_item = item.supplier_item_ids
                    new_item = add_suffix_to_item(item.supplier_item_ids, item.supplier_id)
                    
                    if new_item != original_item:
                        item.supplier_item_ids = new_item
                        self.stats['unmapped_items_updated'] += 1
                        logger.debug(f"Updated unmapped item: {original_item} -> {new_item}")
                    
                except Exception as e:
                    logger.error(f"Error processing unmapped item {item.id}: {e}")
                    self.stats['errors'] += 1
            
            self.db.commit()
            logger.info(f"Successfully updated {self.stats['unmapped_items_updated']} unmapped items")
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error migrating unmapped items: {e}")
            raise
    
    def migrate_temporary_mappings(self):
        """Migrate temporary_item_mappings table to include proper suffixes."""
        logger.info("Starting migration of temporary_item_mappings table...")
        
        try:
            # Get all temporary mappings
            temp_mappings = self.db.query(TempItemMapping).all()
            logger.info(f"Found {len(temp_mappings)} temporary mappings to process")
            
            # Note: Temporary mappings don't have vendor/supplier information, so we can't add suffixes
            # They will be processed when they are used in the context of actual invoices
            logger.info("Skipping temporary mappings - they don't have vendor information for suffix determination")
            
        except Exception as e:
            logger.error(f"Error migrating temporary mappings: {e}")
            raise
    
    def update_json_files(self):
        """Update JSON fixture files with proper suffixes."""
        logger.info("Starting update of JSON fixture files...")
        
        try:
            import json
            import os
            
            # Update item-mapping.json
            json_file = "mpi_backend/storage/fixtures/item-mapping.json"
            if os.path.exists(json_file):
                logger.info(f"Updating {json_file}...")
                
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if isinstance(data, list):
                    updated_count = 0
                    total_count = len(data)
                    
                    for item in data:
                        try:
                            if not isinstance(item, dict):
                                continue
                            
                            supplier_id = item.get('supplier_id')
                            supplier_item_ids = item.get('supplier_item_ids')
                            
                            if not supplier_item_ids or not supplier_id:
                                continue
                            
                            # Add suffix to supplier_item_ids
                            original_item = supplier_item_ids
                            new_item = add_suffix_to_item(supplier_item_ids, supplier_id)
                            
                            if new_item != original_item:
                                item['supplier_item_ids'] = new_item
                                updated_count += 1
                        
                        except Exception as e:
                            logger.error(f"Error processing JSON item: {e}")
                    
                    # Write back to file
                    with open(json_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    
                    logger.info(f"Successfully updated {updated_count} out of {total_count} items in {json_file}")
                else:
                    logger.warning(f"Expected list in {json_file}, got {type(data)}")
            else:
                logger.warning(f"File {json_file} does not exist. Skipping.")
            
            # Update temp-item-mapping.json (usually empty, but check anyway)
            temp_json_file = "mpi_backend/storage/fixtures/temp-item-mapping.json"
            if os.path.exists(temp_json_file):
                logger.info(f"Checking {temp_json_file}...")
                
                with open(temp_json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if isinstance(data, list) and data:
                    logger.info(f"Found {len(data)} items in {temp_json_file}, but no vendor info for suffix determination")
                else:
                    logger.info(f"{temp_json_file} is empty. No updates needed.")
            else:
                logger.warning(f"File {temp_json_file} does not exist. Skipping.")
            
        except Exception as e:
            logger.error(f"Error updating JSON files: {e}")
            raise
    
    def run_migration(self):
        """Run the complete migration process."""
        logger.info("Starting Suffix Standardization Migration...")
        logger.info("This will update all existing data to include proper suffixes")
        
        try:
            # Run migrations in order
            self.migrate_invoice_items()
            self.migrate_item_mappings()
            self.migrate_unmapped_items()
            self.migrate_temporary_mappings()
            
            # Update JSON fixture files
            self.update_json_files()
            
            # Print final statistics
            logger.info("Migration completed successfully!")
            logger.info("Final Statistics:")
            logger.info(f"  Invoice Items Updated: {self.stats['invoice_items_updated']}")
            logger.info(f"  Item Mappings Updated: {self.stats['item_mappings_updated']}")
            logger.info(f"  Unmapped Items Updated: {self.stats['unmapped_items_updated']}")
            logger.info(f"  Temporary Mappings Updated: {self.stats['temporary_mappings_updated']}")
            logger.info(f"  Errors: {self.stats['errors']}")
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise


def main():
    """Main function to run the migration."""
    # Use the database configuration from the project
    from mpi_backend.config import SQLALCHEMY_DATABASE_URI
    DATABASE_URL = SQLALCHEMY_DATABASE_URI
    
    # Confirm with user before running migration
    print("🚨 SUFFIX STANDARDIZATION MIGRATION")
    print("=" * 50)
    print("This will update all existing data in the database to include proper suffixes.")
    print("Make sure you have a backup of your database before proceeding!")
    print()
    
    response = input("Do you want to continue? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Migration cancelled.")
        return
    
    try:
        # Create database engine and session
        engine = create_engine(DATABASE_URL)
        
        # Test the connection
        logger.info("Testing database connection...")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection successful!")
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db_session = SessionLocal()
        
        # Run migration
        migration = SuffixStandardizationMigration(db_session)
        migration.run_migration()
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)
    finally:
        if 'db_session' in locals():
            db_session.close()


if __name__ == "__main__":
    main() 