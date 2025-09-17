import sys
import logging
from pathlib import Path

# Add the parent directory to the path so we can import mpi_backend
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from mpi_backend.config.logging_config import setup_logging
from mpi_backend.database.models import CustomerJobMapping, InvoiceItem
from mpi_backend.database import SessionLocal

# Setup centralized logging
setup_logging()
logger = logging.getLogger(__name__)


def update_existing_invoice_items(db):
    """
    Update existing invoice items in the database by mapping old customer job
    identifiers to new ones based on the CustomerJobMapping table.

    This function retrieves all customer job mappings and invoice items from the
    database. It updates the `customer_job` field of each invoice item if a new
    mapping exists. After updating, it commits the changes to the database and logs
    the number of updated items. If any error occurs during the process, it logs
    the error and raises an exception.

    Args:
        db: A SQLAlchemy session object for database interaction.

    Raises:
        Exception: If there is an error fetching data, updating items, or committing
        changes to the database.
    """
    try:
        # Fetch customer job mappings
        try:
            mappings = db.query(CustomerJobMapping).all()
            logger.info("Fetched %d customer job mappings.", len(mappings))
        except Exception as e:
            raise Exception(f"Error fetching customer job mappings: {str(e)}")

        mapping_dict = {
            m.customer_job: m.updated_customer_job
            for m in mappings
        }

        # Fetch all invoice items
        try:
            invoice_items = db.query(InvoiceItem).all()
            logger.info("Fetched %d invoice items.", len(invoice_items))
        except Exception as e:
            raise Exception(f"Error fetching invoice items: {str(e)}")

        updated_count = 0

        for item in invoice_items:
            if item.customer_job in mapping_dict:
                new_job = mapping_dict[item.customer_job]
                if new_job != item.customer_job:
                    item.customer_job = new_job
                    updated_count += 1

        # Commit the updates
        try:
            db.commit()
            logger.info("Updated %d invoice items.", updated_count)
        except Exception as e:
            db.rollback()
            raise Exception(f"Error committing updated invoice items: {str(e)}")

    except Exception as e:
        logger.error("Error updating invoice items: %s", str(e))
        raise


def main():
    # Setup DB connection
    db = SessionLocal()

    try:
        update_existing_invoice_items(db)
        logger.info("Invoice update completed successfully.")
    except Exception as e:
        logger.error("Failed in main: %s", str(e))
    finally:
        db.close()
        logger.info("Database session closed.")


if __name__ == "__main__":
    main()
