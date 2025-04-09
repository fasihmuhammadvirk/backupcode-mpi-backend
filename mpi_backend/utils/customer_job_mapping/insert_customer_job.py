import json
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from mpi_backend.database.models import CustomerJobMapping
from mpi_backend.config import SQLALCHEMY_DATABASE_URI
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup DB connection
engine = create_engine(SQLALCHEMY_DATABASE_URI)
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()


def insert_customer_job_in_db():
    """
    Inserts new customer job mappings into the database from a JSON file.

    This function reads customer job mappings from a specified JSON file and inserts
    only the new mappings into the database. It first loads the JSON data, then
    compares it with existing mappings in the database to identify new entries.
    New mappings are added in bulk to the database. If any errors occur during
    the process, the transaction is rolled back. Finally, the database session
    is closed.

    Raises:
        FileNotFoundError: If the JSON file is not found.
        ValueError: If the JSON file is corrupted or contains invalid syntax, or
                    if expected fields are missing in the JSON data.
        Exception: If there is an error fetching existing mappings from the database
                   or inserting new mappings.
    """
    try:
        # Load JSON data
        try:
            with open('../../storage/fixtures/customer-job-mapping.json', 'r') as file:
                json_mappings = json.load(file)
        except FileNotFoundError:
            logger.error("❌ Mapping JSON file not found at expected location.")
            raise
        except json.JSONDecodeError:
            logger.error("❌ JSON file is corrupted or contains invalid syntax.")
            raise ValueError("JSON file is corrupted or contains invalid syntax.")

        logger.info("📥 Loaded %d customer job mappings from JSON.", len(json_mappings))

        # Fetch all existing mappings from the DB
        try:
            existing_mappings = session.query(CustomerJobMapping).all()
        except Exception as e:
            logger.error("❌ Error fetching existing mappings from DB: %s", str(e))
            raise

        # Build a set of (customer_job, updated_customer_job) pairs for quick lookup
        existing_set = set(
            (mapping.customer_job.strip().lower(), mapping.updated_customer_job.strip().lower())
            for mapping in existing_mappings
        )

        # Filter only the new ones
        new_entries = []
        for mapping in json_mappings:
            try:
                pair = (
                    str(mapping['customer_job']).strip().lower(),
                    str(mapping['updated_customer_job']).strip().lower()
                )
                if pair not in existing_set:
                    new_entries.append(CustomerJobMapping(
                        customer_job=mapping['customer_job'],
                        updated_customer_job=mapping['updated_customer_job']
                    ))
            except KeyError as ke:
                logger.error("❌ Missing expected fields in JSON: %s", str(ke))
                raise ValueError(f"Missing expected fields in JSON: {str(ke)}")

        # Bulk insert all new mappings
        if new_entries:
            session.add_all(new_entries)
            session.commit()
            logger.info("✅ Inserted %d new customer job mappings.", len(new_entries))
        else:
            logger.info("✅ No new customer job mappings to insert.")

        # Count total mappings now
        total_count = session.query(CustomerJobMapping).count()
        logger.info("📊 Total Customer Job Mappings in DB: %d", total_count)

    except Exception as e:
        session.rollback()
        logger.error("❌ Error inserting customer job mappings into DB: %s", str(e))
        raise

    finally:
        session.close()


if __name__ == "__main__":
    insert_customer_job_in_db()

# # Step 1: Delete existing records, only if necessary
# deleted = session.query(CustomerJobMapping).delete()
# session.commit()
# print(f"Deleted {deleted} existing customer job mappings.")
#
# # Step 2: Insert new records
# for job in customer_jobs:
#     new_mapping = CustomerJobMapping(
#         customer_job=job.get('customer_job'),
#         updated_customer_job=job.get('updated_customer_job')
#     )
#     session.add(new_mapping)
#     # Step 3: Commit once after all inserts
#     session.commit()
#
# print(f"Inserted {len(customer_jobs)} new customer job mappings successfully!")
#
# customer_count = len(session.query(CustomerJobMapping).all())
#
# print(f"Total Customer Jobs Now: {customer_count}")
# # Close session
# session.close()
