import json
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from mpi_backend.database.models import CustomerJobMapping
from mpi_backend.config import SQLALCHEMY_DATABASE_URI

# Setup DB connection
engine = create_engine(SQLALCHEMY_DATABASE_URI)
session = Session(bind=engine)

# Load JSON data
with open('mpi_backend/storage/fixtures/customer-job-mapping.json', 'r') as file:
    customer_jobs = json.load(file)

print(f"Loaded {len(customer_jobs)} customer job mappings from JSON.")

# Step 1: Delete existing records
deleted = session.query(CustomerJobMapping).delete()
session.commit()
print(f"Deleted {deleted} existing customer job mappings.")

# Step 2: Insert new records
for job in customer_jobs:
    new_mapping = CustomerJobMapping(
        customer_job=job.get('customer_job'),
        updated_customer_job=job.get('updated_customer_job')
    )
    session.add(new_mapping)
    # Step 3: Commit once after all inserts
    session.commit()

print(f"Inserted {len(customer_jobs)} new customer job mappings successfully!")

customer_count = len(session.query(CustomerJobMapping).all())

print(f"Total Customer Jobs Now: {customer_count}")
# Close session
session.close()
