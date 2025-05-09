import logging
import json
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, func
from mpi_backend.database.models import CustomerJobMapping, InvoiceItem
from mpi_backend.config import SQLALCHEMY_DATABASE_URI

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def update_existing_invoice_items(db, output_file="mpi_backend/storage/fixtures/missing_customer_jobs.json"):
    try:
        # Fetch customer job mappings directly from DB
        mappings = db.query(CustomerJobMapping).all()
        mapping_dict = {}
        
        # Process mappings to handle whitespace
        for m in mappings:
            customer_job = m.customer_job
            updated_job = m.updated_customer_job
            
            # Clean whitespace
            if customer_job:
                customer_job = customer_job.strip()
            if updated_job:
                updated_job = updated_job.strip()
                
            # Use lowercase for comparison but keep original for replacement
            mapping_dict[customer_job.lower()] = updated_job

        # Fetch all invoice items
        invoice_items = db.query(InvoiceItem).all()
        updated_count = 0
        missing_customer_jobs = []

        for item in invoice_items:
            # Skip items without customer job
            if not item.customer_job:
                continue
                
            # Clean whitespace in customer job
            original_job = item.customer_job
            clean_job = original_job.strip()
            
            # Update if just whitespace was the issue
            if original_job != clean_job:
                item.customer_job = clean_job
                updated_count += 1
                logger.info(f"Fixed whitespace: '{original_job}' -> '{clean_job}'")
            
            # Convert the customer job to lowercase for comparison
            customer_job_normalized = clean_job.lower()

            if customer_job_normalized in mapping_dict:
                new_job = mapping_dict[customer_job_normalized]
                
                # Only update if different
                if new_job != item.customer_job:
                    logger.info(f"Updating job: '{item.customer_job}' -> '{new_job}'")
                    item.customer_job = new_job
                    updated_count += 1
            else:
                # If customer job is not in mappings, add it to the missing list
                if clean_job in missing_customer_jobs:
                    pass
                elif clean_job in mapping_dict.values():
                    pass
                else:
                    missing_customer_jobs.append(clean_job)

        # Commit changes to DB
        db.commit()
        logger.info(f"✅ Updated {updated_count} invoice items.")

        # Write missing customer jobs to JSON file
        if missing_customer_jobs:
            with open(output_file, mode='w') as file:
                json.dump({"missing_customer_jobs": missing_customer_jobs}, 
                          file, indent=4)
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
