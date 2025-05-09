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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


try:
    # Import database models and config
    from mpi_backend.database.models import InvoiceItem
    from mpi_backend.config import SQLALCHEMY_DATABASE_URI
except Exception as e:
    logger.error(f"Failed to import database modules: {str(e)}")
    sys.exit(1)


def check_no_match_items():
    """
    Check how many items have 'No Match' as MPI item in the database
    up to March 31, 2025.
    Provides only overall analysis without individual item details.
    """
    # Hardcoded end date - March 31, 2025
    end_date = date(2025, 3, 31)
    
    try:
        # Create database connection directly
        engine = create_engine(SQLALCHEMY_DATABASE_URI)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        # Query for 'No Match' items up to the end date
        query = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "No Match",
            InvoiceItem.date <= end_date
        )
            
        # Get count directly from the database
        no_match_count = query.count()
        
        # For cost analysis, we need to fetch the actual items
        no_match_items = query.all()
        
        # Calculate cost statistics
        below_100 = 0
        above_100 = 0
        total_cost = 0
        
        for item in no_match_items:
            cost = float(item.cost or 0)
            total_cost += cost
            
            if cost < 100:
                below_100 += 1
            else:
                above_100 += 1
        
        # Calculate average cost if there are items
        if no_match_count > 0:
            avg_cost = total_cost / no_match_count
            below_pct = below_100 / no_match_count * 100
            above_pct = above_100 / no_match_count * 100
        else:
            avg_cost = 0
            below_pct = 0
            above_pct = 0
        
        # Log the results
        title = "'No Match' Items Analysis (Up to March 31, 2025)"
        logger.info(f"\n=== {title} ===")
        logger.info(f"Total 'No Match' items: {no_match_count}")
        
        if no_match_count > 0:
            logger.info(
                f"Items with cost < $100: {below_100} ({below_pct:.1f}%)"
            )
            logger.info(
                f"Items with cost >= $100: {above_100} ({above_pct:.1f}%)"
            )
            logger.info(f"Total cost of all items: ${total_cost:.2f}")
            logger.info(f"Average cost per item: ${avg_cost:.2f}")
        else:
            logger.info("No 'No Match' items found in the database.")
        
        # Close the session when done
        db.close()
    
    except Exception as e:
        logger.error(f"Error during database operation: {str(e)}")
        logger.error("Please check your database configuration")
        if hasattr(e, '__cause__') and e.__cause__:
            logger.error(f"Cause: {str(e.__cause__)}")


if __name__ == "__main__":
    check_no_match_items() 