"""
Sync Google Sheet Metadata Script

This script syncs sheet metadata (sheet_id and sheet_name) from Google Sheets
into the google_sheet_metadata table.

Usage:
    # From within mpi-backend directory with activated conda environment:
    cd mpi-backend
    conda activate mpi-backend
    python scripts/sync_google_sheet_metadata.py
    
    # Or import and use in Python:
    from scripts.sync_google_sheet_metadata import sync_metadata
    sync_metadata()
"""

import sys
import os
import logging
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.utils.sheet_name_manager import SheetNameManager
from mpi_backend.config.spreadsheet_config import DEFAULT_SHEET_ID, GOOGLE_API_KEY
from mpi_backend.database.models.GoogleSheetMetadata import GoogleSheetMetadata

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def show_current_metadata(db):
    """Display current metadata in the table."""
    logger.info("\n" + "=" * 80)
    logger.info("CURRENT GOOGLE SHEET METADATA")
    logger.info("=" * 80)
    
    count = db.query(GoogleSheetMetadata).count()
    logger.info(f"Total sheets in metadata table: {count}")
    
    if count > 0:
        sheets = db.query(GoogleSheetMetadata).order_by(
            GoogleSheetMetadata.sheet_name
        ).all()
        
        logger.info("\nSheets currently stored:")
        for sheet in sheets:
            logger.info(
                f"  sheet_id: {sheet.sheet_id:12} | "
                f"name: {sheet.sheet_name}"
            )
    else:
        logger.warning("  ⚠️  No metadata found - table is empty")
    
    logger.info("=" * 80)
    return count


def sync_metadata_from_google(db, spreadsheet_id=None, api_key=None):
    """Sync metadata from Google Sheets."""
    logger.info("\n" + "=" * 80)
    logger.info("SYNCING FROM GOOGLE SHEETS")
    logger.info("=" * 80)
    
    spreadsheet_id = spreadsheet_id or DEFAULT_SHEET_ID
    api_key = api_key or GOOGLE_API_KEY
    
    logger.info(f"Spreadsheet ID: {spreadsheet_id}")
    logger.info(f"API Key: {'*' * 20}{api_key[-10:] if api_key else 'NOT SET'}")
    
    # Create sheet manager
    sheet_manager = SheetNameManager(db, spreadsheet_id, api_key)
    
    # Sync from Google
    logger.info("\nFetching sheets from Google Sheets API...")
    result = sheet_manager.sync_sheet_metadata_from_google()
    
    if not result['success']:
        logger.error(f"❌ Failed to sync: {result['message']}")
        return False
    
    logger.info(f"\n✅ Successfully synced {result['synced_count']} sheets!")
    
    # Show what was synced
    if 'sheets' in result and result['sheets']:
        logger.info("\nSheets synced from Google:")
        for sheet in result['sheets']:
            logger.info(
                f"  sheet_id: {sheet['gid']:12} | name: {sheet['title']}"
            )
    
    logger.info("=" * 80)
    
    return True


def verify_sync(db, before_count):
    """Verify the sync was successful."""
    logger.info("\n" + "=" * 80)
    logger.info("VERIFICATION")
    logger.info("=" * 80)
    
    after_count = db.query(GoogleSheetMetadata).count()
    
    logger.info(f"Sheets before sync: {before_count}")
    logger.info(f"Sheets after sync:  {after_count}")
    
    if after_count > before_count:
        logger.info(f"\n✅ Added {after_count - before_count} new sheets")
    elif after_count == before_count:
        logger.info("\n✅ All sheets were already up to date")
    
    logger.info("=" * 80)
    
    return after_count > 0


def main():
    """Main function."""
    logger.info("\n" + "=" * 100)
    logger.info("GOOGLE SHEET METADATA SYNC")
    logger.info(f"Started at: {datetime.now()}")
    logger.info("=" * 100)
    
    db = SessionLocal()
    
    try:
        # Show current state
        before_count = show_current_metadata(db)
        
        # Sync from Google
        success = sync_metadata_from_google(db)
        
        if not success:
            logger.error("\n❌ Sync failed!")
            return False
        
        # Verify
        verify_sync(db, before_count)
        
        # Final message
        logger.info("\n" + "=" * 100)
        logger.info("✅ SYNC COMPLETE!")
        logger.info("=" * 100)
        logger.info("\n📋 What this did:")
        logger.info("  ✓ Fetched all sheets from Google Sheets")
        logger.info("  ✓ Updated google_sheet_metadata table")
        logger.info("  ✓ Each sheet now has canonical ID and name")
        logger.info("\n🎯 Next steps:")
        logger.info("  → Run setup_sheet_name_sync.py to update all records")
        logger.info("  → Or just extract data - it will use canonical names")
        logger.info(f"\n⏱️  Completed at: {datetime.now()}")
        logger.info("=" * 100 + "\n")
        
        return True
        
    except Exception as e:
        logger.error(f"\n❌ Error during sync: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        db.close()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

