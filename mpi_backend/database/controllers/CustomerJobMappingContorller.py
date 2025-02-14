from mpi_backend.database.models import CustomerJobMapping
import pandas as pd


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

    def update_mappings_table(self, old_customer_job,new_customer_job):
        """
        Updates or inserts a customer job mapping record. This will be used as reference to all future data.
        """
        try:
            # Check if mapping already exists for the original customer_job
            existing_mapping =  self.db_context.query(CustomerJobMapping).filter(
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