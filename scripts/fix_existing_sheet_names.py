#!/usr/bin/env python3
"""
Script to fix existing incorrect sheet names in the database and JSON files.

This script uses the new sheet name extraction logic to update:
1. supplier_item_mappings table in the database
2. item-mapping.json file
3. Any other files with google_sheet_name references

The script will identify problematic sheet names like "(MBST7-1 1/4-O) (GAS)" 
and update them to clean names like "(GAS)".
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Set
from sqlalchemy.orm import Session

# Add the parent directory to sys.path to allow imports from mpi_backend
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

# Change to project root to load .env file
original_cwd = os.getcwd()
os.chdir(project_root)

# Import database components
from mpi_backend.database import SessionLocal
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.UnmappedItems import UnmappedItems
from mpi_backend.utils.google_sheets.sheet_data_extractor import GoogleSheetDataExtractor

# Set up logging
log_filename = f'sheet_name_fix_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class SheetNameFixer:
    """Class to handle fixing sheet names across the system"""
    
    def __init__(self):
        """Initialize the sheet name fixer"""
        self.extractor = GoogleSheetDataExtractor()
        self.fixed_mappings = {}  # Cache of old_name -> new_name
        self.stats = {
            'database_updates': 0,
            'json_updates': 0,
            'problematic_found': 0,
            'successfully_fixed': 0,
            'errors': 0
        }
    
    def is_problematic_sheet_name(self, sheet_name: str) -> bool:
        """
        Check if a sheet name is problematic (contains multiple parentheses groups)
        
        Args:
            sheet_name: Sheet name to check
            
        Returns:
            True if problematic, False otherwise
        """
        if not sheet_name or not isinstance(sheet_name, str):
            return False
        
        # Count parentheses groups
        parentheses_count = sheet_name.count('(')
        return parentheses_count > 1
    
    def get_fixed_sheet_name(self, original_name: str) -> str:
        """
        Get the fixed sheet name, using cache if available
        
        Args:
            original_name: Original sheet name
            
        Returns:
            Fixed sheet name
        """
        if original_name in self.fixed_mappings:
            return self.fixed_mappings[original_name]
        
        # Use the new extraction logic
        fixed_name = self.extractor._extract_clean_sheet_name(original_name)
        
        # Cache the result
        self.fixed_mappings[original_name] = fixed_name
        
        return fixed_name
    
    def analyze_database_issues(self, db: Session) -> Dict[str, int]:
        """
        Analyze problematic sheet names in the database
        
        Args:
            db: Database session
            
        Returns:
            Dictionary with analysis results
        """
        logger.info("🔍 Analyzing database for problematic sheet names...")
        
        # Check supplier_item_mappings table
        mappings = db.query(ItemsMapping).all()
        problematic_mappings = []
        clean_mappings = []
        
        for mapping in mappings:
            if mapping.google_sheet_name:
                if self.is_problematic_sheet_name(mapping.google_sheet_name):
                    problematic_mappings.append(mapping)
                else:
                    clean_mappings.append(mapping)
        
        # Check unmapped_items table
        unmapped_items = db.query(UnmappedItems).all()
        problematic_unmapped = []
        clean_unmapped = []
        
        for item in unmapped_items:
            if item.google_sheet_name:
                if self.is_problematic_sheet_name(item.google_sheet_name):
                    problematic_unmapped.append(item)
                else:
                    clean_unmapped.append(item)
        
        analysis = {
            'total_mappings': len(mappings),
            'problematic_mappings': len(problematic_mappings),
            'clean_mappings': len(clean_mappings),
            'total_unmapped': len(unmapped_items),
            'problematic_unmapped': len(problematic_unmapped),
            'clean_unmapped': len(clean_unmapped)
        }
        
        logger.info(f"📊 Database Analysis:")
        logger.info(f"   Supplier Item Mappings: {analysis['total_mappings']} total")
        logger.info(f"   - Problematic: {analysis['problematic_mappings']}")
        logger.info(f"   - Clean: {analysis['clean_mappings']}")
        logger.info(f"   Unmapped Items: {analysis['total_unmapped']} total")
        logger.info(f"   - Problematic: {analysis['problematic_unmapped']}")
        logger.info(f"   - Clean: {analysis['clean_unmapped']}")
        
        return analysis
    
    def fix_database_sheet_names(self, db: Session, dry_run: bool = True) -> int:
        """
        Fix problematic sheet names in the database
        
        Args:
            db: Database session
            dry_run: If True, only log what would be changed
            
        Returns:
            Number of records updated
        """
        logger.info(f"🔧 {'[DRY RUN] ' if dry_run else ''}Fixing database sheet names...")
        
        updated_count = 0
        
        # Fix supplier_item_mappings table
        mappings = db.query(ItemsMapping).all()
        
        for mapping in mappings:
            if mapping.google_sheet_name and self.is_problematic_sheet_name(mapping.google_sheet_name):
                original_name = mapping.google_sheet_name
                fixed_name = self.get_fixed_sheet_name(original_name)
                
                if fixed_name != original_name:
                    logger.info(f"   Mapping ID {mapping.id}: '{original_name}' → '{fixed_name}'")
                    
                    if not dry_run:
                        mapping.google_sheet_name = fixed_name
                    
                    updated_count += 1
                    self.stats['successfully_fixed'] += 1
        
        # Fix unmapped_items table
        unmapped_items = db.query(UnmappedItems).all()
        
        for item in unmapped_items:
            if item.google_sheet_name and self.is_problematic_sheet_name(item.google_sheet_name):
                original_name = item.google_sheet_name
                fixed_name = self.get_fixed_sheet_name(original_name)
                
                if fixed_name != original_name:
                    logger.info(f"   Unmapped ID {item.id}: '{original_name}' → '{fixed_name}'")
                    
                    if not dry_run:
                        item.google_sheet_name = fixed_name
                    
                    updated_count += 1
                    self.stats['successfully_fixed'] += 1
        
        if not dry_run and updated_count > 0:
            try:
                db.commit()
                logger.info(f"✅ Successfully updated {updated_count} database records")
                self.stats['database_updates'] = updated_count
            except Exception as e:
                db.rollback()
                logger.error(f"❌ Error committing database changes: {e}")
                self.stats['errors'] += 1
                raise
        elif dry_run:
            logger.info(f"📋 Would update {updated_count} database records")
        
        return updated_count
    
    def analyze_json_files(self) -> Dict[str, Dict]:
        """
        Analyze JSON files for problematic sheet names
        
        Returns:
            Dictionary with file analysis results
        """
        logger.info("🔍 Analyzing JSON files for problematic sheet names...")
        
        json_files = [
            'mpi_backend/storage/fixtures/item-mapping.json',
            'mpi_backend/storage/fixtures/temp-item-mapping.json'
        ]
        
        results = {}
        
        for file_path in json_files:
            if not os.path.exists(file_path):
                logger.warning(f"⚠️  File not found: {file_path}")
                continue
            
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                problematic_count = 0
                clean_count = 0
                
                for item in data:
                    if 'google_sheet_name' in item and item['google_sheet_name']:
                        if self.is_problematic_sheet_name(item['google_sheet_name']):
                            problematic_count += 1
                        else:
                            clean_count += 1
                
                results[file_path] = {
                    'total_items': len(data),
                    'problematic_count': problematic_count,
                    'clean_count': clean_count
                }
                
                logger.info(f"📊 {file_path}:")
                logger.info(f"   Total items: {len(data)}")
                logger.info(f"   Problematic: {problematic_count}")
                logger.info(f"   Clean: {clean_count}")
                
            except Exception as e:
                logger.error(f"❌ Error analyzing {file_path}: {e}")
                self.stats['errors'] += 1
        
        return results
    
    def fix_json_files(self, dry_run: bool = True) -> int:
        """
        Fix problematic sheet names in JSON files
        
        Args:
            dry_run: If True, only log what would be changed
            
        Returns:
            Number of files updated
        """
        logger.info(f"🔧 {'[DRY RUN] ' if dry_run else ''}Fixing JSON files...")
        
        json_files = [
            'mpi_backend/storage/fixtures/item-mapping.json',
            'mpi_backend/storage/fixtures/temp-item-mapping.json'
        ]
        
        files_updated = 0
        
        for file_path in json_files:
            if not os.path.exists(file_path):
                continue
            
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                updated_items = 0
                
                for item in data:
                    if 'google_sheet_name' in item and item['google_sheet_name']:
                        original_name = item['google_sheet_name']
                        
                        if self.is_problematic_sheet_name(original_name):
                            fixed_name = self.get_fixed_sheet_name(original_name)
                            
                            if fixed_name != original_name:
                                logger.info(f"   {file_path}: '{original_name}' → '{fixed_name}'")
                                
                                if not dry_run:
                                    item['google_sheet_name'] = fixed_name
                                
                                updated_items += 1
                
                if updated_items > 0:
                    if not dry_run:
                        # Create backup
                        backup_path = f"{file_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        with open(backup_path, 'w') as f:
                            json.dump(data, f, indent=2)
                        logger.info(f"📁 Created backup: {backup_path}")
                        
                        # Save updated file
                        with open(file_path, 'w') as f:
                            json.dump(data, f, indent=2)
                        
                        logger.info(f"✅ Updated {updated_items} items in {file_path}")
                        files_updated += 1
                        self.stats['json_updates'] += updated_items
                    else:
                        logger.info(f"📋 Would update {updated_items} items in {file_path}")
                
            except Exception as e:
                logger.error(f"❌ Error processing {file_path}: {e}")
                self.stats['errors'] += 1
        
        return files_updated
    
    def run_complete_fix(self, dry_run: bool = True) -> Dict:
        """
        Run the complete sheet name fix process
        
        Args:
            dry_run: If True, only analyze and log what would be changed
            
        Returns:
            Dictionary with operation results
        """
        logger.info("🚀 Starting Complete Sheet Name Fix Process")
        logger.info("="*60)
        
        try:
            # Test database connection first
            logger.info("🔍 Testing database connection...")
            try:
                from sqlalchemy import text
                with SessionLocal() as test_db:
                    test_db.execute(text("SELECT 1"))
                logger.info("✅ Database connection successful")
            except Exception as e:
                logger.error(f"❌ Database connection failed: {e}")
                return {
                    'success': False,
                    'error': f"Database connection failed: {e}",
                    'stats': self.stats
                }
            
            # Step 1: Database analysis and fixes
            with SessionLocal() as db:
                db_analysis = self.analyze_database_issues(db)
                self.stats['problematic_found'] += db_analysis['problematic_mappings'] + db_analysis['problematic_unmapped']
                
                db_updates = self.fix_database_sheet_names(db, dry_run)
            
            # Step 2: JSON file analysis and fixes
            json_analysis = self.analyze_json_files()
            json_updates = self.fix_json_files(dry_run)
            
            # Step 3: Summary
            total_fixed = self.stats['successfully_fixed']
            
            logger.info("\n" + "="*60)
            logger.info("📊 OPERATION SUMMARY")
            logger.info("="*60)
            logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE RUN'}")
            logger.info(f"Problematic sheet names found: {self.stats['problematic_found']}")
            logger.info(f"Successfully fixed: {self.stats['successfully_fixed']}")
            logger.info(f"Database records updated: {self.stats['database_updates']}")
            logger.info(f"JSON items updated: {self.stats['json_updates']}")
            logger.info(f"Errors encountered: {self.stats['errors']}")
            
            if dry_run:
                logger.info("\n🔍 This was a DRY RUN. No changes were made.")
                logger.info("To apply the fixes, run with --live flag")
            else:
                logger.info(f"\n✅ Sheet name fix completed successfully!")
                logger.info(f"Your QuickBooks export should now work properly.")
            
            return {
                'success': self.stats['errors'] == 0,
                'dry_run': dry_run,
                'stats': self.stats,
                'db_analysis': db_analysis,
                'json_analysis': json_analysis
            }
            
        except Exception as e:
            logger.error(f"❌ Critical error during fix process: {e}")
            return {
                'success': False,
                'error': str(e),
                'stats': self.stats
            }


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Fix incorrect sheet names in database and files')
    parser.add_argument(
        '--live', 
        action='store_true', 
        help='Apply fixes (default is dry run)'
    )
    parser.add_argument(
        '--force', 
        action='store_true', 
        help='Skip confirmation prompt for live run'
    )
    
    args = parser.parse_args()
    
    dry_run = not args.live
    
    print("🛠️  Sheet Name Fix Script")
    print("="*60)
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE RUN (will make changes)'}")
    
    if not dry_run and not args.force:
        print("\n⚠️  WARNING: This will modify your database and JSON files!")
        print("Make sure you have backups before proceeding.")
        
        confirm = input("\nDo you want to continue? (yes/no): ").lower().strip()
        if confirm != 'yes':
            print("❌ Operation cancelled.")
            return
    
    # Run the fix
    fixer = SheetNameFixer()
    result = fixer.run_complete_fix(dry_run)
    
    if result['success']:
        print(f"\n🎉 Operation completed successfully!")
        if dry_run:
            print("Run with --live to apply the fixes.")
    else:
        print(f"\n❌ Operation failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main() 