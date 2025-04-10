import logging
import json
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from mpi_backend.database.models import CustomerJobMapping, InvoiceItem
from mpi_backend.config import SQLALCHEMY_DATABASE_URI

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def update_existing_invoice_items(db, output_file="mpi_backend/storage/fixtures/missing_customer_jobs.json"):
    try:
        # Fetch customer job mappings directly from DB
        mappings = db.query(CustomerJobMapping).all()
        mapping_dict = {
            m.customer_job.lower(): m.updated_customer_job
            for m in mappings
        }

        # Fetch all invoice items
        invoice_items = db.query(InvoiceItem).all()
        updated_count = 0
        missing_customer_jobs = []

        for item in invoice_items:
            # Convert the customer job to lowercase for comparison
            customer_job_normalized = item.customer_job.lower()

            if customer_job_normalized in mapping_dict:
                new_job = mapping_dict[customer_job_normalized]
                if new_job != item.customer_job:
                    item.customer_job = new_job
                    updated_count += 1
            else:
                # If customer job is not in mappings, add it to the missing list
                missing_customer_jobs.append(item.customer_job)

        # Commit changes to DB
        db.commit()
        logger.info(f"✅ Updated {updated_count} invoice items.")

        # Write missing customer jobs to JSON file
        if missing_customer_jobs:
            with open(output_file, mode='w') as file:
                json.dump({"missing_customer_jobs": missing_customer_jobs}, file, indent=4)
            logger.info(f"✅ Missing customer jobs written to {output_file}.")
        else:
            logger.info("No missing customer jobs.")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error updating invoice items: {str(e)}")
        raise


def main():
    engine = create_engine(SQLALCHEMY_DATABASE_URI)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        update_existing_invoice_items(db)
        logger.info("✅ Invoice update completed.")
    except Exception as e:
        logger.error(f"❌ Failed in main: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
