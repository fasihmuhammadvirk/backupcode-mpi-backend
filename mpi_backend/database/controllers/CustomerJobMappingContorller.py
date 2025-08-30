from mpi_backend.database.models import CustomerJobMapping
import pandas as pd
from sqlalchemy import select
from mpi_backend.utils.customer_job_mapping.update_customer_job_mapping_file import (
    update_customer_job_mappings_json
)
from mpi_backend.utils.customer_job_mapping.insert_customer_job import (
    insert_customer_job_in_db
)
# Removed incorrect import - function doesn't exist


class CustomerJobMappingController:
    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self):
        """Get a database session object, whether db_context is a factory or session."""
        # Check if it's already a session instance (has query, add, commit methods)
        if (hasattr(self.db_context, 'query') and 
            hasattr(self.db_context, 'commit')):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

    async def get_customer_job_mappings(self):
        db = self._get_db_session()
        result = await db.execute(select(CustomerJobMapping))
        query_result = result.scalars().all()

        # Process mappings to fix whitespace
        processed_data = []
        for item in query_result:
            cust_job = item.customer_job
            updated_job = item.updated_customer_job
            
            # Trim whitespace
            if cust_job:
                cust_job = cust_job.strip()
            if updated_job:
                updated_job = updated_job.strip()

            processed_data.append((item.id, cust_job, updated_job))
            
        columns = ['id', 'customer_job', 'updated_customer_job']
        customer_job_mappings = pd.DataFrame(processed_data, columns=columns)
        return customer_job_mappings

    async def update_mappings_table(self, old_customer_job, new_customer_job):
        """
        Updates or inserts a customer job mapping record.
        Used as reference for all future data.
        """
        try:
            # Clean inputs - trim whitespace
            if old_customer_job:
                old_customer_job = old_customer_job.strip()
            if new_customer_job:
                new_customer_job = new_customer_job.strip()
            
            # Check if mapping already exists for the original customer_job
            result = await self.db_context.execute(
                select(CustomerJobMapping).where(
                    CustomerJobMapping.customer_job == old_customer_job
                )
            )
            existing_mapping = result.scalar_one_or_none()

            if existing_mapping:
                # Update existing mapping
                existing_mapping.updated_customer_job = new_customer_job
                self.db_context.add(existing_mapping)
            else:
                # Create new mapping
                new_mapping = CustomerJobMapping(
                    customer_job=old_customer_job,
                    updated_customer_job=new_customer_job
                )
                self.db_context.add(new_mapping)

            await self.db_context.commit()
        except Exception as e:
            await self.db_context.rollback()
            raise Exception(f"Error updating customer job mapping: {str(e)}")

    @staticmethod
    async def add_new_mappings(excel_file, db):
        """
                Processes the Excel file to update customer job mappings.

                :param excel_file: File-like object of the Excel sheet
                :return: Summary message string
                """
        try:

            total_entries = update_customer_job_mappings_json(excel_file)

            insert_customer_job_in_db(db)

            # Removed call to non-existent function

        except ValueError as ve:
            raise ValueError(f"Invalid data in Excel file: {str(ve)}")

        except FileNotFoundError as fe:
            raise FileNotFoundError(f"File not found or unreadable: {str(fe)}")

        except Exception as e:
            # Catch any unexpected errors
            raise Exception(f"Error updating customer job mapping: {str(e)}")

        return f"Added {total_entries} new customer job mappings and updated existing invoice items"

