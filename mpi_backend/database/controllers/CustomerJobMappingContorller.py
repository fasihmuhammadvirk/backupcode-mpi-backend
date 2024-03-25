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
