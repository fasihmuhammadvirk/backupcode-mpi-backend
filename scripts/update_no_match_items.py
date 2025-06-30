#!/usr/bin/env python3
import os
import sys
import logging
from sqlalchemy import create_engine
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


def update_no_match_items():
    """
    Update invoice items with 'No Match' MPI items based on their cost:
    - If cost < 100: Set to 'UIDI-Job Material'
    - If cost >= 100: Set to 'UIDI-Job Equipment'
    
    After updating, verify the results.
    """
    try:
        # Create database connection directly
        engine = create_engine(SQLALCHEMY_DATABASE_URI)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        # Query directly from the database for 'No Match' items
        no_match_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "No Match"
        ).all()
        
        initial_count = len(no_match_items)
        logger.info(
            f"Found {initial_count} items with 'No Match' MPI item"
        )
        
        updated_count = 0
        material_count = 0
        equipment_count = 0
        error_count = 0
        
        for item in no_match_items:
            try:
                # Get the cost value
                cost = float(item.cost) if item.cost else 0
                
                # Determine the new MPI item based on cost
                if cost < 100:
                    new_mpi_item = "UIDI-Job Material"
                    material_count += 1
                else:
                    new_mpi_item = "UIDI-Job Equipment"
                    equipment_count += 1
                
                # Update the item in the database
                item.mpi_item = new_mpi_item
                item.mpi_description = new_mpi_item
                db.add(item)
                
                updated_count += 1
                
                # Commit every 100 records to avoid large transactions
                if updated_count % 100 == 0:
                    db.commit()
                    logger.info(f"Updated {updated_count} items so far")
                
            except Exception as e:
                logger.error(f"Error updating item {item.id}: {str(e)}")
                error_count += 1
        
        # Final commit for remaining records
        db.commit()
        
        # Print update summary
        logger.info("\n=== Update Summary ===")
        logger.info(f" Successfully updated: {updated_count} items")
        logger.info(
            f"  - Items as 'UIDI-Job Material': {material_count}"
        )
        logger.info(
            f"  - Items as 'UIDI-Job Equipment': {equipment_count}"
        )
        if error_count:
            logger.warning(f"ERROR: Items with errors: {error_count}")
        
        # VERIFICATION SECTION
        # Verify the results by checking for remaining 'No Match' items
        # and sampling the updated items
        
        remaining = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "No Match"
        ).count()
        
        material_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Material"
        ).count()
        
        equipment_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Equipment"
        ).count()
        
        logger.info("\n=== Verification Results ===")
        logger.info(f"'No Match' items remaining: {remaining}")
        logger.info(
            f"'UIDI-Job Material' items in database: {material_items}"
        )
        logger.info(
            f"'UIDI-Job Equipment' items in database: {equipment_items}"
        )
        
        # Sample some items to verify proper categorization
        material_samples = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Material"
        ).limit(3).all()
        
        equipment_samples = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Equipment"
        ).limit(3).all()
        
        if material_samples:
            logger.info(
                "\n--- Sample 'UIDI-Job Material' Items (cost < 100) ---"
            )
            for item in material_samples:
                desc = item.description
                if desc and len(desc) > 50:
                    desc = desc[:50] + "..."
                logger.info(
                    f"Item ID: {item.id}, Cost: ${item.cost:.2f}, "
                    f"Description: {desc}"
                )
        
        if equipment_samples:
            logger.info(
                "\n--- Sample 'UIDI-Job Equipment' Items (cost >= 100) ---"
            )
            for item in equipment_samples:
                desc = item.description
                if desc and len(desc) > 50:
                    desc = desc[:50] + "..."
                logger.info(
                    f"Item ID: {item.id}, Cost: ${item.cost:.2f}, "
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
    update_no_match_items() 