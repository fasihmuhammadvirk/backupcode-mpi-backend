#!/usr/bin/env python3
import os
import sys
import logging
from datetime import date
from contextlib import contextmanager

# Add the parent directory to the Python path to allow imports to work
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, parent_dir)

# Make sure env variables are set properly before importing database modules
# Fix for the 'None' port issue
if os.environ.get('POSTGRES_PORT') == 'None' or os.environ.get('POSTGRES_PORT') is None:
    os.environ['POSTGRES_PORT'] = '5432'  # Default PostgreSQL port

# Now imports from the project will work
from mpi_backend.database import get_db
from mpi_backend.database.models import InvoiceItem


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_no_match_items():
    """
    Check how many items have 'No Match' as MPI item in the database
    up to March 31, 2025.
    Provides only overall analysis without individual item details.
    """
    db_context = contextmanager(get_db)
    
    # Hardcoded end date - March 31, 2025
    end_date = date(2025, 3, 31)
    
    try:
        with db_context() as db:
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
            
            avg_cost = (total_cost / no_match_count 
                        if no_match_count > 0 else 0)
            
            # Log the results
            logger.info("\n=== 'No Match' Items Analysis (Up to March 31, 2025) ===")
            logger.info(f"Total 'No Match' items: {no_match_count}")
            
            if no_match_count > 0:
                below_pct = below_100/no_match_count*100 if no_match_count > 0 else 0
                above_pct = above_100/no_match_count*100 if no_match_count > 0 else 0
                
                logger.info(f"Items with cost < $100: {below_100} ({below_pct:.1f}%)")
                logger.info(f"Items with cost >= $100: {above_100} ({above_pct:.1f}%)")
                logger.info(f"Total cost of all items: ${total_cost:.2f}")
                logger.info(f"Average cost per item: ${avg_cost:.2f}")
            else:
                logger.info("No 'No Match' items found in the database.")
    
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        logger.error("Check your database connection settings in the .env file")
        logger.error("Make sure POSTGRES_PORT is set to a valid number (default: 5432)")


if __name__ == "__main__":
    check_no_match_items() 