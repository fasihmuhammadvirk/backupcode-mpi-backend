#!/usr/bin/env python3
import os
import sys
import logging
import re
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add the parent directory to the Python path to allow imports to work
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, parent_dir)

# Import database models and configuration
try:
    from mpi_backend.database.models import InvoiceItem
    from mpi_backend.config import SQLALCHEMY_DATABASE_URI
except Exception as e:
    print(f"Failed to import database modules: {str(e)}")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def clean_item_code(item_code):
    """
    Clean item codes by removing spaces around hyphens and other common patterns.
    Also removes invalid information like numbers in the middle of item codes.
    
    Examples:
    - "BVC114 -F" -> "BVC114-F"
    - "ABC123 - XYZ" -> "ABC123-XYZ"
    - "ITEM 456 - 789" -> "ITEM456-789"
    - "PART A - B" -> "PART A-B"
    - "PFS453 2389-F" -> "PFS453-F"
    - "ABC123 456 XYZ-F" -> "ABC123 XYZ-F"
    """
    if not item_code or not isinstance(item_code, str):
        return item_code
    
    # Remove spaces around hyphens
    cleaned = re.sub(r'\s*-\s*', '-', item_code)
    # Remove spaces around forward slashes
    cleaned = re.sub(r'\s*/\s*', '/', cleaned)
    # Remove spaces around backslashes
    cleaned = re.sub(r'\s*\\\s*', r'\\', cleaned)
    # Remove multiple consecutive spaces
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.strip()

    # Remove any numbers with 4 or more digits that are between the main code and the suffix
    # e.g., 'PFS453 2389-F' -> 'PFS453-F', 'ABC123 4567 XYZ-F' -> 'ABC123 XYZ-F'
    # This will remove any group of 4+ digits surrounded by spaces, before a hyphen and suffix
    cleaned = re.sub(r' (\d{4,})(?=-[A-Za-z])', '', cleaned)
    # Also remove 4+ digit numbers at the end if not part of the suffix
    cleaned = re.sub(r' (\d{4,})$', '', cleaned)
    # Remove 4+ digit numbers between words, e.g., 'ABC123 4567 XYZ-F' -> 'ABC123 XYZ-F'
    cleaned = re.sub(r' (\d{4,}) ', ' ', cleaned)

    return cleaned


def remove_spaces_from_invoice_items():
    """
    Remove spaces from invoice items in the database.
    Specifically targets patterns like "BVC114 -F" to become "BVC114-F"
    """
    try:
        # Create database connection
        engine = create_engine(SQLALCHEMY_DATABASE_URI)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        # Get all invoice items that need cleaning
        # We'll look for items that contain spaces around hyphens, slashes, etc.
        # Also look for items with potential invalid numbers in the middle
        items_to_clean = db.query(InvoiceItem).filter(
            InvoiceItem.item.isnot(None),
            InvoiceItem.item != '',
            (
                InvoiceItem.item.like('%-%') |  # Contains hyphens
                InvoiceItem.item.like('% %')   # Contains spaces (potential invalid numbers)
            )
        ).all()
        
        logger.info(f"Found {len(items_to_clean)} items to potentially clean")
        
        updated_count = 0
        skipped_count = 0
        
        for item in items_to_clean:
            original_item = item.item
            cleaned_item = clean_item_code(original_item)
            
            # Only update if the item actually changed
            if cleaned_item != original_item:
                logger.info(f"Updating item {item.id}: '{original_item}' -> '{cleaned_item}'")
                item.item = cleaned_item
                db.add(item)
                updated_count += 1
                
                # Commit every 100 records to avoid long transactions
                if updated_count % 100 == 0:
                    db.commit()
                    logger.info(f"Processed {updated_count} items so far...")
            else:
                skipped_count += 1
        
        # Commit any remaining items
        if updated_count % 100 != 0:
            db.commit()
        
        # Print summary
        logger.info("\n=== Space Removal Summary ===")
        logger.info(f"Total items checked: {len(items_to_clean)}")
        logger.info(f"Items updated: {updated_count}")
        logger.info(f"Items skipped (no changes needed): {skipped_count}")
        
        # Close the database session
        db.close()
        
        return updated_count
        
    except Exception as e:
        logger.error(f"Error during database operation: {str(e)}")
        logger.error("Please check your database configuration")
        if hasattr(e, '__cause__') and e.__cause__:
            logger.error(f"Cause: {str(e.__cause__)}")
        return 0


def preview_changes():
    """
    Preview what changes would be made without actually updating the database.
    This is useful for testing and verification.
    """
    try:
        # Create database connection
        engine = create_engine(SQLALCHEMY_DATABASE_URI)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        # Get sample items that would be affected
        items_to_preview = db.query(InvoiceItem).filter(
            InvoiceItem.item.isnot(None),
            InvoiceItem.item != '',
            (
                InvoiceItem.item.like('%-%') |  # Contains hyphens
                InvoiceItem.item.like('% %')   # Contains spaces (potential invalid numbers)
            )
        ).limit(20).all()
        
        logger.info(f"Previewing changes for {len(items_to_preview)} sample items:")
        logger.info("=" * 60)
        
        preview_count = 0
        for item in items_to_preview:
            original_item = item.item
            cleaned_item = clean_item_code(original_item)
            
            if cleaned_item != original_item:
                logger.info(f"ID {item.id}: '{original_item}' -> '{cleaned_item}'")
                preview_count += 1
        
        if preview_count == 0:
            logger.info("No items would be changed in this sample.")
        else:
            logger.info(f"\n{preview_count} items would be updated in this sample.")
        
        # Close the database session
        db.close()
        
    except Exception as e:
        logger.error(f"Error during preview: {str(e)}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Remove spaces from invoice items')
    parser.add_argument('--preview', action='store_true', 
                       help='Preview changes without making them')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be changed without making changes')
    
    args = parser.parse_args()
    
    if args.preview or args.dry_run:
        logger.info("Running in preview mode - no changes will be made")
        preview_changes()
    else:
        logger.info("Starting space removal process...")
        updated_count = remove_spaces_from_invoice_items()
        logger.info(f"Process completed. {updated_count} items were updated.") 