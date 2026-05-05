"""Check for variations EVERYWHERE."""
import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
from sqlalchemy import func

# Try to import InvoiceItem if it exists
try:
    from mpi_backend.database.models.InvoiceItem import InvoiceItem
    HAS_INVOICE_ITEM = True
except ImportError:
    HAS_INVOICE_ITEM = False

db = SessionLocal()

print("\n" + "=" * 100)
print("COMPREHENSIVE CHECK - WHERE ARE THE VARIATIONS?")
print("=" * 100)

# 1. Database - supplier_item_mappings
print("\n1. DATABASE - supplier_item_mappings (google_sheet_name):")
nohub_supplier = db.query(
    ItemsMapping.google_sheet_name
).filter(
    ItemsMapping.google_sheet_name.ilike('%NO-HUB%')
).distinct().all()

variations = sorted(set([n[0] for n in nohub_supplier]))
print(f"   Found {len(variations)} variations:")
for v in variations:
    count = db.query(ItemsMapping).filter(ItemsMapping.google_sheet_name == v).count()
    print(f"     {count:5} | {v}")

# 2. Database - temporary_item_mappings
print("\n2. DATABASE - temporary_item_mappings (sheet_name):")
nohub_temp = db.query(
    TempItemMapping.sheet_name
).filter(
    TempItemMapping.sheet_name.ilike('%NO-HUB%')
).distinct().all()

temp_variations = sorted(set([n[0] for n in nohub_temp if n[0]]))
print(f"   Found {len(temp_variations)} variations:")
for v in temp_variations:
    count = db.query(TempItemMapping).filter(TempItemMapping.sheet_name == v).count()
    print(f"     {count:5} | {v}")

# 3. Database - invoice_items (if it has sheet_name column)
print("\n3. DATABASE - invoice_items:")
if HAS_INVOICE_ITEM:
    try:
        # Check if sheet_name column exists
        has_sheet_name = hasattr(InvoiceItem, 'sheet_name')
        if has_sheet_name:
            nohub_invoice = db.query(
                InvoiceItem.sheet_name
            ).filter(
                InvoiceItem.sheet_name.ilike('%NO-HUB%')
            ).distinct().all()
            invoice_variations = sorted(set([n[0] for n in nohub_invoice if n[0]]))
            print(f"   Found {len(invoice_variations)} variations:")
            for v in invoice_variations:
                count = db.query(InvoiceItem).filter(InvoiceItem.sheet_name == v).count()
                print(f"     {count:5} | {v}")
        else:
            print("   OK: No sheet_name column in invoice_items (expected)")
    except Exception as e:
        print(f"   OK: Error checking invoice_items: {e}")
else:
    print("   OK: InvoiceItem model not found (not applicable)")

# 4. JSON files
print("\n4. JSON FILES in storage/fixtures:")
try:
    from mpi_backend.config.spreadsheet_config import DEFAULT_OUTPUT_FILE
    mapping_export_path = DEFAULT_OUTPUT_FILE
except ImportError:
    mapping_export_path = 'mpi_backend/storage/fixtures/mapping_export.json'
json_files = [
    mapping_export_path,
    'mpi_backend/storage/fixtures/temp-item-mapping.json'
]

for json_file in json_files:
    if os.path.exists(json_file):
        print(f"\n   {os.path.basename(json_file)}:")
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        # Check all possible keys
        all_variations = set()
        for key in ['permanent_mappings', 'temporary_mappings', 'invalid_mappings']:
            if key in data:
                for item in data[key]:
                    # Check both google_sheet_name and sheet_name
                    for name_key in ['google_sheet_name', 'sheet_name']:
                        if name_key in item:
                            name = item[name_key]
                            if 'NO-HUB' in name.upper():
                                all_variations.add(name)
        
        print(f"     Found {len(all_variations)} variations:")
        for v in sorted(all_variations):
            print(f"       - {v}")
    else:
        print(f"   OK: {os.path.basename(json_file)} - not found")

print("\n" + "=" * 100)
print("SUMMARY:")
print("=" * 100)
print(f"Database supplier_item_mappings: {len(variations)} variations")
print(f"Database temporary_item_mappings: {len(temp_variations)} variations")
print("\nIf all show 1 variation, the system is CONSISTENT! ✅")
print("=" * 100 + "\n")

db.close()

