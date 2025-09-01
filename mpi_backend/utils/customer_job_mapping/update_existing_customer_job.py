import json
import logging
from mpi_backend.database import get_async_db
from mpi_backend.database.models import CustomerJobMapping
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


async def update_existing_customer_job_in_db():
    """
    Updates existing customer job mappings in the database from a JSON file.

    This function reads customer job mappings from a specified JSON file and updates
    existing mappings in the database. It first loads the JSON data, then compares
    it with existing mappings to identify entries that need updating.
    Updates are applied in bulk to the database. If any errors occur during
    the process, the transaction is rolled back.

    Raises:
        FileNotFoundError: If the JSON file is not found.
        ValueError: If the JSON file is corrupted or contains invalid syntax, or
                    if expected fields are missing in the JSON data.
        Exception: If there is an error fetching existing mappings from the database
                   or updating mappings.
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

            # Build a dictionary for quick lookup
            existing_dict = {
                mapping.customer_job.strip().lower(): mapping
                for mapping in existing_mappings
            }

            # Update existing mappings
            updated_count = 0
            for mapping in json_mappings:
                try:
                    customer_job = str(mapping['customer_job']).strip().lower()
                    if customer_job in existing_dict:
                        existing_mapping = existing_dict[customer_job]
                        existing_mapping.updated_customer_job = mapping['updated_customer_job']
                        updated_count += 1
                except KeyError as ke:
                    logger.error("Missing expected fields in JSON: %s", str(ke))
                    raise ValueError(f"Missing expected fields in JSON: {str(ke)}")

            # Commit updates
            if updated_count > 0:
                await session.commit()
                logger.info("Updated %d existing customer job mappings.", updated_count)
            else:
                logger.info("No existing customer job mappings to update.")

            # Count total mappings now
            result = await session.execute(
                select(CustomerJobMapping)
            )
            total_count = result.scalar()
            logger.info("Total Customer Job Mappings in DB: %d", total_count)

        except Exception as e:
            await session.rollback()
            logger.error("Error updating customer job mappings in DB: %s", str(e))
            raise


# Legacy sync wrapper for backward compatibility
def update_existing_customer_job_in_db_sync():
    """Synchronous wrapper for backward compatibility"""
    import asyncio
    return asyncio.run(update_existing_customer_job_in_db())


if __name__ == "__main__":
    import asyncio
    asyncio.run(update_existing_customer_job_in_db())
