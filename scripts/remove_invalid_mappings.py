#!/usr/bin/env python3
"""
Intelligent Invalid Mappings Removal Script

This script intelligently identifies and removes invalid mappings by:
1. Extracting current valid mappings from Google Sheets using the updated validation logic
2. Comparing current sheets data with database/JSON to find invalid mappings
3. Removing invalid mappings from database and JSON files
4. Updating items without valid mappings to "No Match"

Usage:
    python scripts/remove_invalid_mappings.py [--dry-run]
"""

import sys
import os
import json
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Set, Tuple

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models import ItemsMapping, Supplier, UnmappedItems
from mpi_backend.utils.mapping_validators import is_temporary_mapping
from mpi_backend.config.logging_config import setup_logging
from mpi_backend.utils.google_sheets import GoogleSheetDataExtractor
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID, GOOGLE_API_KEY, DEFAULT_OUTPUT_FILE, SKIP_SHEETS
)

# Setup logging using existing app configuration
setup_logging()
logger = logging.getLogger('mpi_backend.scripts.intelligent_cleanup')


class IntelligentMappingCleaner:
    """Intelligent cleaner that compares current Google Sheets with database/JSON"""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.extractor = GoogleSheetDataExtractor(
            sheet_id=DEFAULT_SHEET_ID,
            api_key=GOOGLE_API_KEY,
            skip_sheets=SKIP_SHEETS
        )
        
        # Stats tracking
        self.stats = {
            'current_valid_mappings': 0,
            'db_invalid_removed': 0,
            'json_invalid_removed': 0,
            'items_marked_no_match': 0,
            'total_processed': 0
        }
    
    def run_cleanup(self) -> Dict:
        """Main cleanup method"""
        logger.info("Starting intelligent mapping cleanup...")
        
        with SessionLocal() as db:
            try:
                # Step 1: Extract current valid mappings from Google Sheets
                logger.info("Step 1: Extracting current valid mappings from Google Sheets...")
                current_valid_mappings = self._extract_current_valid_mappings()
                self.stats['current_valid_mappings'] = len(current_valid_mappings)
                logger.info(f"Found {len(current_valid_mappings)} currently valid mappings in Google Sheets")
                
                # Step 2: Identify invalid mappings in database
                logger.info("Step 2: Identifying invalid mappings in database...")
                invalid_db_mappings = self._identify_invalid_db_mappings(db, current_valid_mappings)
                logger.info(f"Found {len(invalid_db_mappings)} invalid mappings in database")
                
                # Step 3: Remove invalid mappings from database
                logger.info("Step 3: Removing invalid mappings from database...")
                self.stats['db_invalid_removed'] = self._remove_invalid_db_mappings(db, invalid_db_mappings)
                
                # Step 4: Clean JSON files
                logger.info("Step 4: Cleaning JSON files...")
                self.stats['json_invalid_removed'] = self._clean_json_files(current_valid_mappings)
                
                # Step 5: Mark unmapped items as "No Match"
                logger.info("Step 5: Marking unmapped items as 'No Match'...")
                self.stats['items_marked_no_match'] = self._mark_unmapped_items_no_match(db, current_valid_mappings)
                
                # Generate final report
                self._generate_final_report()
                
                return {
                    'success': True,
                    'stats': self.stats,
                    'dry_run': self.dry_run
                }
                
            except Exception as e:
                logger.error(f"Cleanup failed: {str(e)}")
                return {
                    'success': False,
                    'error': str(e),
                    'stats': self.stats
                }
    
    def _extract_current_valid_mappings(self) -> Set[Tuple[str, int, str]]:
        """Extract current valid mappings from Google Sheets using updated validation logic"""
        logger.info("Extracting from Google Sheets with current validation logic...")
        
        # Extract all current mappings from Google Sheets
        current_mappings = self.extractor.process_all_sheets()
        
        # Convert to set of tuples for easy comparison
        valid_mappings = set()
        for mapping in current_mappings:
            # Create unique key: (mpi_code, supplier_id, supplier_item_ids)
            key = (
                mapping.get('mpi_code', '').strip(),
                mapping.get('supplier_id', 0),
                mapping.get('supplier_item_ids', '').strip()
            )
            
            # Only include if all components are valid
            if key[0] and key[1] and key[2]:
                valid_mappings.add(key)
        
        logger.info(f"Extracted {len(valid_mappings)} valid mapping keys from current Google Sheets")
        return valid_mappings
    
    def _identify_invalid_db_mappings(self, db, current_valid_mappings: Set[Tuple[str, int, str]]) -> List[Dict]:
        """Identify mappings in database that are not in current valid Google Sheets mappings"""
        invalid_mappings = []
        
        # Get all mappings from database
        all_db_mappings = db.query(ItemsMapping).all()
        logger.info(f"Checking {len(all_db_mappings)} database mappings against current Google Sheets...")
        
        for mapping in all_db_mappings:
            # Create the same key format
            mapping_key = (
                mapping.mpi_code.strip() if mapping.mpi_code else '',
                mapping.supplier_id,
                mapping.supplier_item_ids.strip() if mapping.supplier_item_ids else ''
            )
            
            # Check if this mapping exists in current valid Google Sheets mappings
            is_valid = mapping_key in current_valid_mappings
            
            # Also check for temporary mappings (these should be removed)
            is_temporary = is_temporary_mapping(mapping.mpi_code, mapping.description)
            
            # Determine reasons for invalidity
            reasons = []
            if not is_valid:
                reasons.append('not_in_current_sheets')
            if is_temporary:
                reasons.append('temporary_mapping')
            
            # If invalid for any reason, add to removal list
            if reasons:
                invalid_mappings.append({
                    'mapping': mapping,
                    'key': mapping_key,
                    'reasons': reasons
                })
        
        return invalid_mappings
    
    def _remove_invalid_db_mappings(self, db, invalid_mappings: List[Dict]) -> int:
        """Remove invalid mappings from database"""
        removed_count = 0
        
        for item in invalid_mappings:
            mapping = item['mapping']
            reasons = item['reasons']
            
            # Get supplier name for logging
            supplier_name = self._get_supplier_name(db, mapping.supplier_id)
            
            logger.info(
                f"{'[DRY RUN] ' if self.dry_run else ''}Removing DB mapping: "
                f"'{mapping.supplier_item_ids}' -> '{mapping.mpi_code}' "
                f"(Supplier: {supplier_name}) "
                f"Reasons: {', '.join(reasons)}"
            )
            
            if not self.dry_run:
                try:
                    db.delete(mapping)
                    removed_count += 1
                except Exception as e:
                    logger.error(f"Error removing mapping ID {mapping.id}: {e}")
        
        if not self.dry_run and removed_count > 0:
            try:
                db.commit()
                logger.info(f"Successfully removed {removed_count} invalid mappings from database")
            except Exception as e:
                db.rollback()
                logger.error(f"Error committing database changes: {e}")
                removed_count = 0
        else:
            logger.info(f"{'[DRY RUN] Would remove' if self.dry_run else 'No'} {len(invalid_mappings)} invalid mappings from database")
        
        return removed_count
    
    def _clean_json_files(self, current_valid_mappings: Set[Tuple[str, int, str]]) -> int:
        """Clean invalid mappings from JSON files"""
        total_removed = 0
        
        # Process both JSON files
        json_files = [
            DEFAULT_OUTPUT_FILE,
            DEFAULT_OUTPUT_FILE.replace('item-mapping.json', 'temp-item-mapping.json')
        ]
        
        for json_file in json_files:
            if os.path.exists(json_file):
                removed = self._clean_single_json_file(json_file, current_valid_mappings)
                total_removed += removed
            else:
                logger.info(f"JSON file not found: {json_file}")
        
        return total_removed
    
    def _clean_single_json_file(self, json_file: str, current_valid_mappings: Set[Tuple[str, int, str]]) -> int:
        """Clean a single JSON file"""
        logger.info(f"Processing {json_file}...")
        
        try:
            # Create backup
            if not self.dry_run:
                backup_name = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_file = f"{json_file}.backup_{backup_name}"
                os.system(f"cp '{json_file}' '{backup_file}'")
                logger.info(f"Created backup: {backup_file}")
            
            # Read JSON data
            with open(json_file, 'r') as f:
                data = json.load(f)
            
            original_count = len(data)
            cleaned_data = []
            removed_count = 0
            
            for item in data:
                # Create the same key format for comparison
                item_key = (
                    item.get('mpi_code', '').strip(),
                    item.get('supplier_id', 0),
                    item.get('supplier_item_ids', '').strip()
                )
                
                # Check if this mapping is in current valid mappings
                is_valid = item_key in current_valid_mappings
                
                # Also check for temporary mappings
                is_temporary = is_temporary_mapping(item.get('mpi_code', ''), item.get('description', ''))
                
                if is_valid and not is_temporary:
                    cleaned_data.append(item)
                else:
                    removed_count += 1
                    reasons = []
                    if not is_valid:
                        reasons.append('not_in_current_sheets')
                    if is_temporary:
                        reasons.append('temporary_mapping')
                    
                    logger.info(
                        f"{'[DRY RUN] ' if self.dry_run else ''}Removing JSON mapping: "
                        f"'{item.get('supplier_item_ids')}' -> '{item.get('mpi_code')}' "
                        f"Reasons: {', '.join(reasons)}"
                    )
            
            # Save cleaned data
            if not self.dry_run and removed_count > 0:
                with open(json_file, 'w') as f:
                    json.dump(cleaned_data, f, indent=2)
                logger.info(f"Cleaned {json_file}: {original_count} -> {len(cleaned_data)} (removed {removed_count})")
            else:
                logger.info(f"{'[DRY RUN] Would clean' if self.dry_run else 'No changes to'} {json_file}: {removed_count} items would be removed")
            
            return removed_count
            
        except Exception as e:
            logger.error(f"Error processing {json_file}: {e}")
            return 0
    
    def _mark_unmapped_items_no_match(self, db, current_valid_mappings: Set[Tuple[str, int, str]]) -> int:
        """Mark items without valid mappings as 'No Match'"""
        
        # Get all distinct items that should have mappings
        # This would require checking your invoice items or other source data
        # For now, let's focus on items that currently have invalid mappings
        
        marked_count = 0
        
        try:
            # Get unmapped items from the database
            unmapped_items = db.query(UnmappedItems).all()
            
            for item in unmapped_items:
                # Check if this item has any valid mapping
                has_valid_mapping = False
                
                # Check if any mapping exists for this supplier_item_ids
                # This should check supplier_item_ids, not mpi_code!
                for mapping_key in current_valid_mappings:
                    mpi_code, supplier_id, supplier_item_id = mapping_key
                    # Check if the unmapped item's supplier_item_ids matches any valid mapping
                    if (supplier_item_id == item.supplier_item_ids and 
                        supplier_id == item.supplier_id):
                        has_valid_mapping = True
                        break
                
                # If no valid mapping exists, ensure it's marked as "No Match"
                if not has_valid_mapping and item.supplier_item_ids != 'No Match':
                    logger.info(
                        f"{'[DRY RUN] ' if self.dry_run else ''}Marking as No Match: "
                        f"Supplier Item: {item.supplier_item_ids} (Supplier ID: {item.supplier_id}) "
                        f"MPI: {item.mpi_code}"
                    )
                    
                    if not self.dry_run:
                        item.supplier_item_ids = 'No Match'
                        marked_count += 1
            
            if not self.dry_run and marked_count > 0:
                db.commit()
                logger.info(f"Marked {marked_count} items as 'No Match'")
            else:
                logger.info(f"{'[DRY RUN] Would mark' if self.dry_run else 'No items to mark'} as 'No Match'")
            
        except Exception as e:
            logger.error(f"Error marking items as 'No Match': {e}")
            if not self.dry_run:
                db.rollback()
        
        return marked_count
    
    def _get_supplier_name(self, db, supplier_id: int) -> str:
        """Get supplier name by ID"""
        try:
            supplier = db.query(Supplier).filter_by(id=supplier_id).first()
            return supplier.supplier_name if supplier else f"Unknown (ID: {supplier_id})"
        except Exception:
            return f"Unknown (ID: {supplier_id})"
    
    def _generate_final_report(self):
        """Generate final cleanup report"""
        logger.info("\n" + "="*60)
        logger.info("INTELLIGENT CLEANUP REPORT")
        logger.info("="*60)
        logger.info(f"Current valid mappings in Google Sheets: {self.stats['current_valid_mappings']:,}")
        logger.info(f"Invalid mappings removed from database: {self.stats['db_invalid_removed']:,}")
        logger.info(f"Invalid mappings removed from JSON files: {self.stats['json_invalid_removed']:,}")
        logger.info(f"Items marked as 'No Match': {self.stats['items_marked_no_match']:,}")
        logger.info(f"Total cleanup operations: {sum(self.stats.values()):,}")
        logger.info(f"Mode: {'DRY RUN (no changes made)' if self.dry_run else 'LIVE RUN (changes applied)'}")
        logger.info("="*60)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Intelligent Invalid Mappings Cleanup')
    parser.add_argument(
        '--dry-run', 
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    logger.info(f"Starting intelligent cleanup {'(DRY RUN MODE)' if args.dry_run else '(LIVE MODE)'}")
    
    # Run the intelligent cleanup
    cleaner = IntelligentMappingCleaner(dry_run=args.dry_run)
    result = cleaner.run_cleanup()
    
    if result['success']:
        logger.info("Cleanup completed successfully!")
        if args.dry_run:
            logger.info("To apply changes, run without --dry-run flag")
    else:
        logger.error(f"Cleanup failed: {result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    main() 
