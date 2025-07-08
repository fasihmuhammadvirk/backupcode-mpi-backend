import json
from sqlalchemy import create_engine
from mpi_backend.database.models import ItemsMapping
from mpi_backend.config import SQLALCHEMY_DATABASE_URI
from mpi_backend.database import SessionLocal

engine = create_engine(SQLALCHEMY_DATABASE_URI)
session = SessionLocal()

insertion_count = 0

with open('../mpi_backend/storage/fixtures/item-mapping.json', 'r') as file:
    temp_items = json.load(file)

for job in temp_items:
    exists = session.query(ItemsMapping).filter_by(supplier_item_ids=job['supplier_item_ids']).first()
    if exists:
        print(f"Skipping: {job['supplier_item_ids']} already exists in the database.")
        continue

    new_mapping = ItemsMapping(
        google_sheet_name=job['google_sheet_name'],
        mpi_code=job['mpi_code'],
        description=job['description'],
        supplier_item_ids=job['supplier_item_ids'],
        supplier_id=job['supplier_id']
    )
    session.add(new_mapping)
    insertion_count+=1

session.commit()
print(
    f"Inserted {insertion_count} records into ItemsMapping table."
)
session.close()

