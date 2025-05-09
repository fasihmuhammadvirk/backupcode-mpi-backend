#!/usr/bin/env python3
import os
import sys
import logging
from datetime import date
from sqlalchemy import create_engine, func
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

# Force output to stdout
print("Starting verification script...")


def verify_updates():
    """
    Verify the updates made by the update_mpi_items_fix.py script.
    This checks that all the correct categorizations were applied.
    """
    try:
        print("Creating database connection...")
        # Create database connection
        engine = create_engine(SQLALCHEMY_DATABASE_URI)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        print("Setting cutoff date...")
        # Set the date boundary used in the update script
        cutoff_date = date(2025, 3, 25)
        
        print("Beginning verification...")
        # Check counts of different MPI items before cutoff date
        print("\n=== Items Before March 25, 2025 ===")
        logger.info("\n=== Items Before March 25, 2025 ===")
        
        # Get counts by MPI item type
        before_counts = db.query(
            InvoiceItem.mpi_item, 
            func.count(InvoiceItem.id).label('count')
        ).filter(
            InvoiceItem.date < cutoff_date
        ).group_by(
            InvoiceItem.mpi_item
        ).all()
        
        for mpi_item, count in before_counts:
            print(f"{mpi_item}: {count} items")
            logger.info(f"{mpi_item}: {count} items")
        
        # Check for any remaining UIDI-Job Material before cutoff
        material_before = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Material",
            InvoiceItem.date < cutoff_date
        ).count()
        
        if material_before > 0:
            logger.warning(
                f"⚠️ Found {material_before} 'UIDI-Job Material' items before "
                f"cutoff that were not updated"
            )
        
        # Check for any UIDI-Job Equipment with cost < 100 before cutoff
        equipment_before = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Equipment",
            InvoiceItem.date < cutoff_date
        ).all()
        
        equipment_issue_count = 0
        for item in equipment_before:
            try:
                cost = float(item.cost) if item.cost else 0
                if cost < 100:
                    equipment_issue_count += 1
                    logger.warning(
                        f"⚠️ Item {item.id} with cost ${cost} is still "
                        f"'UIDI-Job Equipment' before cutoff"
                    )
            except (ValueError, TypeError):
                pass
        
        if equipment_issue_count:
            logger.warning(
                f"⚠️ Found {equipment_issue_count} 'UIDI-Job Equipment' items "
                f"with cost < 100 before cutoff that were not updated"
            )
        
        # Check for any No Match with cost < 100 before cutoff
        nomatch_before = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "No Match",
            InvoiceItem.date < cutoff_date
        ).all()
        
        nomatch_issue_count = 0
        for item in nomatch_before:
            try:
                cost = float(item.cost) if item.cost else 0
                if cost < 100:
                    nomatch_issue_count += 1
                    logger.warning(
                        f"⚠️ Item {item.id} with cost ${cost} is still "
                        f"'No Match' before cutoff"
                    )
            except (ValueError, TypeError):
                pass
        
        if nomatch_issue_count:
            logger.warning(
                f"⚠️ Found {nomatch_issue_count} 'No Match' items with cost "
                f"< 100 before cutoff that were not updated"
            )
        
        # Check counts of different MPI items after cutoff date
        logger.info("\n=== Items After March 25, 2025 ===")
        
        # Get counts by MPI item type
        after_counts = db.query(
            InvoiceItem.mpi_item, 
            func.count(InvoiceItem.id).label('count')
        ).filter(
            InvoiceItem.date >= cutoff_date
        ).group_by(
            InvoiceItem.mpi_item
        ).all()
        
        for mpi_item, count in after_counts:
            logger.info(f"{mpi_item}: {count} items")
        
        # Check for any remaining UIDI-Job Material after cutoff
        material_after = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Material",
            InvoiceItem.date >= cutoff_date
        ).count()
        
        if material_after > 0:
            logger.warning(
                f"⚠️ Found {material_after} 'UIDI-Job Material' items after "
                f"cutoff that were not updated"
            )
        
        # Check for any UIDI-Job Equipment with cost < 100 after cutoff
        equipment_after = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Equipment",
            InvoiceItem.date >= cutoff_date
        ).all()
        
        equipment_issue_count = 0
        for item in equipment_after:
            try:
                cost = float(item.cost) if item.cost else 0
                if cost < 100:
                    equipment_issue_count += 1
                    logger.warning(
                        f"⚠️ Item {item.id} with cost ${cost} is still "
                        f"'UIDI-Job Equipment' after cutoff"
                    )
            except (ValueError, TypeError):
                pass
        
        if equipment_issue_count:
            logger.warning(
                f"⚠️ Found {equipment_issue_count} 'UIDI-Job Equipment' items "
                f"with cost < 100 after cutoff that were not updated"
            )
        
        # Sample some UIDI-Job Material Purchased items
        purchased_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Material Purchased"
        ).limit(5).all()
        
        if purchased_items:
            logger.info("\n=== Sample 'UIDI-Job Material Purchased' Items ===")
            for item in purchased_items:
                desc = item.description
                if desc and len(desc) > 50:
                    desc = desc[:50] + "..."
                logger.info(
                    f"Item ID: {item.id}, Date: {item.date}, Cost: ${item.cost}, "
                    f"Description: {desc}"
                )
        
        # Close the database session
        db.close()
        
    except Exception as e:
        logger.error(f"Error during database operation: {str(e)}")
        logger.error("Please check your database configuration")
        if hasattr(e, '__cause__') and e.__cause__:
            logger.error(f"Cause: {str(e.__cause__)}")


if __name__ == "__main__":
    verify_updates()