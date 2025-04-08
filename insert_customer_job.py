import json
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from mpi_backend.database.models import CustomerJobMapping
from mpi_backend.config import SQLALCHEMY_DATABASE_URI

# Setup DB connection
engine = create_engine(SQLALCHEMY_DATABASE_URI)
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

# Load JSON data
with open('mpi_backend/storage/fixtures/customer-job-mapping.json', 'r') as file:
    json_mappings = json.load(file)

print(f"📥 Loaded {len(json_mappings)} customer job mappings from JSON.")

# Fetch all existing mappings from the DB
existing_mappings = session.query(CustomerJobMapping).all()

# Build a set of (customer_job, updated_customer_job) pairs for quick lookup
existing_set = set(
    (mapping.customer_job.strip().lower(), mapping.updated_customer_job.strip().lower())
    for mapping in existing_mappings
)

# Filter only the new ones
new_entries = []
for mapping in json_mappings:
    pair = (
        str(mapping['customer_job']).strip().lower(),
        str(mapping['updated_customer_job']).strip().lower()
    )
    if pair not in existing_set:
        new_entries.append(CustomerJobMapping(
            customer_job=mapping['customer_job'],
            updated_customer_job=mapping['updated_customer_job']
        ))

# Bulk insert all new mappings
session.add_all(new_entries)
session.commit()

print(f"✅ Inserted {len(new_entries)} new customer job mappings.")

# Count total mappings now
total_count = session.query(CustomerJobMapping).count()
print(f"📊 Total Customer Job Mappings in DB: {total_count}")

# Close session
session.close()


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
