import json
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from mpi_backend.database.models import CustomerJobMapping
from mpi_backend.config import SQLALCHEMY_DATABASE_URI
engine = create_engine(SQLALCHEMY_DATABASE_URI)
session = Session(bind=engine)
with open('mpi_backend/storage/fixtures/customer-job-mapping.json', 'r') as file:
    customer_jobs = json.load(file)

print(customer_jobs[:5])

for job in customer_jobs:
    # print(job)
    new_mapping = CustomerJobMapping(
        customer_job=job.get('customer_job'),
        updated_customer_job=job.get('updated_customer_job')
    )
    session.add(new_mapping)
    session.commit()
#
# session.commit()
print("Data inserted successfully!")
session.close()