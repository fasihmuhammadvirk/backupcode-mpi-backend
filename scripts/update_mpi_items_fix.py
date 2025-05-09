#!/usr/bin/env python3
import os
import sys
import logging
from datetime import date
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


def update_mpi_items():
    """
    Update invoice items based on date, cost, and current MPI item value:
    
    For items BEFORE March 25:
    - Change "UIDI-Job Material" to "UIDI-Job Material Purchased"
    - Change "UIDI-Job Equipment" with cost < 100 to "UIDI-Job Material Purchased"
    - Change "No Match" with cost < 100 to "UIDI-Job Material Purchased"
    
    For items AFTER March 25:
    - Change "UIDI-Job Material" to "No Match"
    - Change "UIDI-Job Equipment" with cost < 100 to "No Match"
    """
    try:
        # Create database connection
        engine = create_engine(SQLALCHEMY_DATABASE_URI)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        # Set the date boundary
        cutoff_date = date(2025, 3, 25)
        
        # BEFORE MARCH 25 UPDATES
        # ----------------------
        
        # 1. Update "UIDI-Job Material" to "UIDI-Job Material Purchased"
        before_material_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Material",
            InvoiceItem.date < cutoff_date
        ).all()
        
        before_material_count = 0
        for item in before_material_items:
            item.mpi_item = "UIDI-Job Material Purchased"
            item.mpi_description = "UIDI-Job Material Purchased"
            db.add(item)
            before_material_count += 1
            
            # Commit every 100 records
            if before_material_count % 100 == 0:
                db.commit()
                logger.info(f"Processed {before_material_count} UIDI-Job Material items (before cutoff)")
        
        # 2. Update "UIDI-Job Equipment" with cost < 100 to "UIDI-Job Material Purchased"
        before_equipment_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Equipment",
            InvoiceItem.date < cutoff_date
        ).all()
        
        before_equipment_count = 0
        before_equipment_updated = 0
        for item in before_equipment_items:
            before_equipment_count += 1
            
            try:
                cost = float(item.cost) if item.cost else 0
                
                if cost < 100:
                    item.mpi_item = "UIDI-Job Material Purchased"
                    item.mpi_description = "UIDI-Job Material Purchased"
                    db.add(item)
                    before_equipment_updated += 1
            except (ValueError, TypeError):
                logger.warning(f"Could not convert cost for item {item.id}: {item.cost}")
            
            # Commit every 100 records
            if before_equipment_count % 100 == 0:
                db.commit()
                logger.info(f"Processed {before_equipment_count} UIDI-Job Equipment items (before cutoff)")
        
        # 3. Update "No Match" with cost < 100 to "UIDI-Job Material Purchased"
        before_nomatch_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "No Match",
            InvoiceItem.date < cutoff_date
        ).all()
        
        before_nomatch_count = 0
        before_nomatch_updated = 0
        for item in before_nomatch_items:
            before_nomatch_count += 1
            
            try:
                cost = float(item.cost) if item.cost else 0
                
                if cost < 100:
                    item.mpi_item = "UIDI-Job Material Purchased"
                    item.mpi_description = "UIDI-Job Material Purchased"
                    db.add(item)
                    before_nomatch_updated += 1
            except (ValueError, TypeError):
                logger.warning(f"Could not convert cost for item {item.id}: {item.cost}")
            
            # Commit every 100 records
            if before_nomatch_count % 100 == 0:
                db.commit()
                logger.info(f"Processed {before_nomatch_count} No Match items (before cutoff)")
        
        # Commit any remaining items from before cutoff date
        db.commit()
        
        # AFTER MARCH 25 UPDATES
        # ---------------------
        
        # 1. Change "UIDI-Job Material" to "No Match"
        after_material_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Material",
            InvoiceItem.date >= cutoff_date
        ).all()
        
        after_material_count = 0
        for item in after_material_items:
            item.mpi_item = "No Match"
            item.mpi_description = "No Match"
            db.add(item)
            after_material_count += 1
            
            # Commit every 100 records
            if after_material_count % 100 == 0:
                db.commit()
                logger.info(f"Processed {after_material_count} UIDI-Job Material items (after cutoff)")
        
        # 2. Change "UIDI-Job Equipment" with cost < 100 to "No Match"
        after_equipment_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI-Job Equipment",
            InvoiceItem.date >= cutoff_date
        ).all()
        
        after_equipment_count = 0
        after_equipment_updated = 0
        for item in after_equipment_items:
            after_equipment_count += 1
            
            try:
                cost = float(item.cost) if item.cost else 0
                
                if cost < 100:
                    item.mpi_item = "No Match"
                    item.mpi_description = "No Match"
                    db.add(item)
                    after_equipment_updated += 1
            except (ValueError, TypeError):
                logger.warning(f"Could not convert cost for item {item.id}: {item.cost}")
            
            # Commit every 100 records
            if after_equipment_count % 100 == 0:
                db.commit()
                logger.info(f"Processed {after_equipment_count} UIDI-Job Equipment items (after cutoff)")
        
        # Commit any remaining items from after cutoff date
        db.commit()
        
        # Print summary of updates
        logger.info("\n=== Update Summary ===")
        
        logger.info("\nBefore March 25, 2025 Updates:")
        logger.info(f"✅ 'UIDI-Job Material' items updated: {before_material_count}")
        logger.info(f"✅ 'UIDI-Job Equipment' items checked: {before_equipment_count}")
        logger.info(f"   - Items with cost < 100 updated: {before_equipment_updated}")
        logger.info(f"✅ 'No Match' items checked: {before_nomatch_count}")
        logger.info(f"   - Items with cost < 100 updated: {before_nomatch_updated}")
        logger.info(f"Total items updated before cutoff: {before_material_count + before_equipment_updated + before_nomatch_updated}")
        
        logger.info("\nAfter March 25, 2025 Updates:")
        logger.info(f"✅ 'UIDI-Job Material' items updated: {after_material_count}")
        logger.info(f"✅ 'UIDI-Job Equipment' items checked: {after_equipment_count}")
        logger.info(f"   - Items with cost < 100 updated: {after_equipment_updated}")
        logger.info(f"Total items updated after cutoff: {after_material_count + after_equipment_updated}")
        
        # Close the database session
        db.close()
        
    except Exception as e:
        logger.error(f"Error during database operation: {str(e)}")
        logger.error("Please check your database configuration")
        if hasattr(e, '__cause__') and e.__cause__:
            logger.error(f"Cause: {str(e.__cause__)}")


if __name__ == "__main__":
    update_mpi_items() 