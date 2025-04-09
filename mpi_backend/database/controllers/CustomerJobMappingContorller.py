from mpi_backend.database.models import CustomerJobMapping
import pandas as pd
import json
from mpi_backend.utils.customer_job_mapping.update_customer_job_mapping_file import update_customer_job_mappings_json
from mpi_backend.utils.customer_job_mapping.insert_customer_job import insert_customer_job_in_db
from mpi_backend.utils.customer_job_mapping.update_existing_customer_job import update_existing_invoice_items


class CustomerJobMappingController:
    def __init__(self, db):
        self.db_context = db

    def get_customer_job_mappings(self):
        with self.db_context() as db:
            query_result = db.query(CustomerJobMapping).all()

            data = [(item.id, item.customer_job, item.updated_customer_job) for item in query_result]
            columns = ['id', 'customer_job', 'updated_customer_job']
            customer_job_mappings = pd.DataFrame(data, columns=columns)
            return customer_job_mappings

    def update_mappings_table(self, old_customer_job, new_customer_job):
        """
        Updates or inserts a customer job mapping record. This will be used as reference to all future data.
        """
        try:
            # Check if mapping already exists for the original customer_job
            existing_mapping = self.db_context.query(CustomerJobMapping).filter(
                CustomerJobMapping.customer_job == old_customer_job
            ).first()

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

            self.db_context.commit()
        except Exception as e:
            self.db_context.rollback()
            raise Exception(f"Error updating customer job mapping: {str(e)}")

    def add_new_mappings(self, excel_file):
        """
        Processes the Excel file to update customer job mappings.

        :param excel_file: File-like object of the Excel sheet
        :return: Summary message string
        """
        try:
            total_entries = update_customer_job_mappings_json(excel_file)

            insert_customer_job_in_db()

            update_existing_invoice_items(self.db_context)

        except ValueError as ve:
            raise ValueError(f"Invalid data in Excel file: {str(ve)}")

        except FileNotFoundError as fe:
            raise FileNotFoundError(f"File not found or unreadable: {str(fe)}")

        except Exception as e:
            # Catch any unexpected errors
            raise Exception(f"Error updating customer job mapping: {str(e)}")

        return f"Added {total_entries} new customer job mappings and updated existing invoice items"
