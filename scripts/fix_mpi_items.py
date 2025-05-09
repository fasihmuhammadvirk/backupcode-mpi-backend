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


def fix_mpi_items():
    """
    Fix MPI items:
    1. Change "UIDI-Job Material Purchased" to "UIDI-Job Materials Purchased"
       and set mpi_description to "No Match"
    2. For "UIDI-Job Equipment" items where mpi_description is "UIDI-Job Equipment",
       change mpi_description to "No Match"
    """
    try:
        # Create database connection
        engine = create_engine(SQLALCHEMY_DATABASE_URI)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        # Fix 1: Change "UIDI-Job Material Purchased" to "UIDI-Job Materials Purchased"
        logger.info("Fixing UIDI-Job Material Purchased items...")
        
        material_purchased_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Material Purchased"
        ).all()
        
        material_count = len(material_purchased_items)
        logger.info(f"Found {material_count} items with 'UIDI-Job Material Purchased'")
        
        for item in material_purchased_items:
            item.mpi_item = "UIDI-Job Materials Purchased"
            item.mpi_description = "No Match"
            db.add(item)
        
        db.commit()
        logger.info(f"Updated {material_count} items to 'UIDI-Job Materials Purchased'")
        
        # Fix 2: Update mpi_description for "UIDI-Job Equipment" items
        logger.info("Fixing UIDI-Job Equipment mpi_descriptions...")
        
        equipment_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Equipment",
            InvoiceItem.mpi_description == "UIDI-Job Equipment"
        ).all()
        
        equipment_count = len(equipment_items)
        logger.info(f"Found {equipment_count} 'UIDI-Job Equipment' items with matching mpi_description")
        
        for item in equipment_items:
            item.mpi_description = "No Match"
            db.add(item)
        
        db.commit()
        logger.info(f"Updated {equipment_count} 'UIDI-Job Equipment' mpi_descriptions to 'No Match'")
        
        # Verification
        logger.info("\n=== Verification Results ===")
        
        # Check for any remaining "UIDI-Job Material Purchased" items
        remaining_material = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Material Purchased"
        ).count()
        
        logger.info(f"'UIDI-Job Material Purchased' items remaining: {remaining_material}")
        
        # Check for any "UIDI-Job Equipment" with "UIDI-Job Equipment" mpi_description
        equipment_wrong_desc = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Equipment",
            InvoiceItem.mpi_description == "UIDI-Job Equipment"
        ).count()
        
        logger.info(f"'UIDI-Job Equipment' items with mpi_description 'UIDI-Job Equipment': {equipment_wrong_desc}")
        
        # Close the database session
        db.close()
        
    except Exception as e:
        logger.error(f"Error during database operation: {str(e)}")
        logger.error("Please check your database configuration")
        if hasattr(e, '__cause__') and e.__cause__:
            logger.error(f"Cause: {str(e.__cause__)}")


if __name__ == "__main__":
    fix_mpi_items() 