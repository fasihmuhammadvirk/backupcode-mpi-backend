"""
Diagnostic script to see what's actually happening with sheet names.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.GoogleSheetMetadata import GoogleSheetMetadata
from sqlalchemy import func

db = SessionLocal()

print("\n" + "=" * 80)
print("1. GOOGLE SHEET METADATA TABLE")
print("=" * 80)

metadata_sheets = db.query(GoogleSheetMetadata).all()
print(f"Total sheets in metadata: {len(metadata_sheets)}")

if len(metadata_sheets) == 0:
    print("⚠️  PROBLEM: google_sheet_metadata table is EMPTY!")
    print("   You need to run: python scripts/sync_google_sheet_metadata.py")
else:
    print("\nSheets in metadata:")
    for sheet in sorted(metadata_sheets, key=lambda x: x.sheet_name):
        print(f"  {sheet.sheet_id:12} | {sheet.sheet_name}")

print("\n" + "=" * 80)
print("2. NO-HUB VARIATIONS IN DATABASE")
print("=" * 80)

nohub_query = db.query(
    ItemsMapping.google_sheet_name,
    ItemsMapping.sheet_id,
    func.count(ItemsMapping.id).label('count')
).filter(
    ItemsMapping.google_sheet_name.ilike('%NO-HUB%')
).group_by(
    ItemsMapping.google_sheet_name,
    ItemsMapping.sheet_id
).order_by(
    func.count(ItemsMapping.id).desc()
)

nohub_variations = nohub_query.all()
print(f"Found {len(nohub_variations)} NO-HUB variations:\n")

for name, sheet_id, count in nohub_variations:
    id_str = str(sheet_id) if sheet_id else "NULL"
    print(f"  {count:4} records | sheet_id: {id_str:12} | '{name}'")

print("\n" + "=" * 80)
print("3. COPPER VARIATIONS IN DATABASE")
print("=" * 80)

copper_query = db.query(
    ItemsMapping.google_sheet_name,
    ItemsMapping.sheet_id,
    func.count(ItemsMapping.id).label('count')
).filter(
    ItemsMapping.google_sheet_name.ilike('%COPPER%')
).group_by(
    ItemsMapping.google_sheet_name,
    ItemsMapping.sheet_id
).order_by(
    func.count(ItemsMapping.id).desc()
)

copper_variations = copper_query.all()
print(f"Found {len(copper_variations)} COPPER variations:\n")

for name, sheet_id, count in copper_variations:
    id_str = str(sheet_id) if sheet_id else "NULL"
    print(f"  {count:4} records | sheet_id: {id_str:12} | '{name}'")

print("\n" + "=" * 80)
print("4. RECORDS WITHOUT SHEET_ID")
print("=" * 80)

total = db.query(ItemsMapping).count()
no_id = db.query(ItemsMapping).filter(ItemsMapping.sheet_id.is_(None)).count()

print(f"Total records: {total:,}")
print(f"Records WITHOUT sheet_id: {no_id:,}")
print(f"Records WITH sheet_id: {total - no_id:,}")

if no_id > 0:
    print(f"\n⚠️  {no_id:,} records don't have sheet_id - they CAN'T be updated!")
    
    # Show sample of records without sheet_id
    print("\nSample records without sheet_id:")
    samples = db.query(ItemsMapping.google_sheet_name, func.count(ItemsMapping.id).label('count')).filter(
        ItemsMapping.sheet_id.is_(None)
    ).group_by(
        ItemsMapping.google_sheet_name
    ).order_by(
        func.count(ItemsMapping.id).desc()
    ).limit(10).all()
    
    for name, count in samples:
        print(f"  {count:4} records | '{name}'")

print("\n" + "=" * 80)
print("5. DIAGNOSIS")
print("=" * 80)

if len(metadata_sheets) == 0:
    print("❌ ISSUE: google_sheet_metadata table is empty")
    print("   FIX: Run 'python scripts/sync_google_sheet_metadata.py'")
elif no_id > 0:
    print(f"❌ ISSUE: {no_id:,} records don't have sheet_id")
    print("   FIX: Fuzzy matching is not working correctly")
    print("   The script needs to be improved")
elif len(nohub_variations) > 1 or len(copper_variations) > 1:
    print("❌ ISSUE: Multiple variations exist even with sheet_ids")
    print("   FIX: Records WITH sheet_id need to be updated to canonical names")
else:
    print("✅ Everything looks good!")

print("=" * 80 + "\n")

db.close()

