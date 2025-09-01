import json
from mpi_backend.database.models import CustomerJobMapping
import logging
from mpi_backend.database import get_async_db
from contextlib import asynccontextmanager
import sys
from pathlib import Path
from sqlalchemy import select

# Add the parent directory to the path so we can import mpi_backend
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from mpi_backend.config.logging_config import setup_logging

# Setup centralized logging
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_db_session():
    """Get database session for customer job mapping operations"""
    async for db in get_async_db():
        try:
            yield db
        finally:
            await db.close()


async def insert_customer_job_in_db():
    """
    Inserts new customer job mappings into the database from a JSON file.

    This function reads customer job mappings from a specified JSON file and inserts
    only the new mappings into the database. It first loads the JSON data, then
    compares it with existing mappings in the database to identify new entries.
    New mappings are added in bulk to the database. If any errors occur during
    the process, the transaction is rolled back.

    Raises:
        FileNotFoundError: If the JSON file is not found.
        ValueError: If the JSON file is corrupted or contains invalid syntax, or
                    if expected fields are missing in the JSON data.
        Exception: If there is an error fetching existing mappings from the database
                   or inserting new mappings.
    """
    async with get_db_session() as session:
        try:
            # Load JSON data
            try:
                with open('mpi_backend/storage/fixtures/customer-job-mapping.json', 'r') as file:
                    json_mappings = json.load(file)
            except FileNotFoundError:
                logger.error("Mapping JSON file not found at expected location.")
                raise
            except json.JSONDecodeError:
                logger.error("JSON file is corrupted or contains invalid syntax.")
                raise ValueError("JSON file is corrupted or contains invalid syntax.")

            logger.info("Loaded %d customer job mappings from JSON.", len(json_mappings))

            # Fetch all existing mappings from the DB
            try:
                result = await session.execute(
                    select(CustomerJobMapping)
                )
                existing_mappings = result.scalars().all()
            except Exception as e:
                logger.error("Error fetching existing mappings from DB: %s", str(e))
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
                    logger.error("Missing expected fields in JSON: %s", str(ke))
                    raise ValueError(f"Missing expected fields in JSON: {str(ke)}")

            # Bulk insert all new mappings
            if new_entries:
                session.add_all(new_entries)
                await session.commit()
                logger.info("Inserted %d new customer job mappings.", len(new_entries))
            else:
                logger.info("No new customer job mappings to insert.")

            # Count total mappings now
            result = await session.execute(
                select(CustomerJobMapping)
            )
            total_count = result.scalar()
            logger.info("Total Customer Job Mappings in DB: %d", total_count)

        except Exception as e:
            await session.rollback()
            logger.error("Error inserting customer job mappings into DB: %s", str(e))
            raise


# Legacy sync wrapper for backward compatibility
def insert_customer_job_in_db_sync():
    """Synchronous wrapper for backward compatibility"""
    import asyncio
    return asyncio.run(insert_customer_job_in_db())


if __name__ == "__main__":
    import asyncio
    asyncio.run(insert_customer_job_in_db())
