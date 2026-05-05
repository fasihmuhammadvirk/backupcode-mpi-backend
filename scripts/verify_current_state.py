"""Quick verification of current database state."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from sqlalchemy import func

db = SessionLocal()

print("\n" + "=" * 80)
print("CURRENT DATABASE STATE")
print("=" * 80)

# NO-HUB variations
print("\nNO-HUB variations:")
nohub = db.query(
    ItemsMapping.google_sheet_name,
    ItemsMapping.sheet_id,
    func.count(ItemsMapping.id)
).filter(
    ItemsMapping.google_sheet_name.ilike('%NO-HUB%')
).group_by(
    ItemsMapping.google_sheet_name,
    ItemsMapping.sheet_id
).order_by(
    func.count(ItemsMapping.id).desc()
).all()

for name, sid, count in nohub:
    print(f"  {count:5} | sheet_id: {sid or 'NULL':12} | '{name}'")

# COPPER variations
print("\nCOPPER variations:")
copper = db.query(
    ItemsMapping.google_sheet_name,
    ItemsMapping.sheet_id,
    func.count(ItemsMapping.id)
).filter(
    ItemsMapping.google_sheet_name.ilike('%COPPER%')
).group_by(
    ItemsMapping.google_sheet_name,
    ItemsMapping.sheet_id
).order_by(
    func.count(ItemsMapping.id).desc()
).all()

for name, sid, count in copper:
    print(f"  {count:5} | sheet_id: {sid or 'NULL':12} | '{name}'")

# Records without sheet_id
print("\nRecords without sheet_id:")
no_id = db.query(ItemsMapping).filter(ItemsMapping.sheet_id.is_(None)).count()
total = db.query(ItemsMapping).count()
print(f"  {no_id:,} / {total:,}")

print("=" * 80 + "\n")

db.close()

