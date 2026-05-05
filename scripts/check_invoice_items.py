"""Check invoice_items table for sheet name variations."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from sqlalchemy import func

db = SessionLocal()

print("\n" + "=" * 100)
print("INVOICE_ITEMS TABLE - SHEET NAME CHECK")
print("=" * 100)

# Total records
total = db.query(InvoiceItem).execution_options(include_all=True).count()
print(f"\nTotal invoice_items: {total:,}")

# NO-HUB variations
print("\nNO-HUB variations in invoice_items:")
nohub_variations = db.query(
    InvoiceItem.sheet_name,
    func.count(InvoiceItem.id)
).execution_options(include_all=True).filter(
    InvoiceItem.sheet_name.ilike('%NO-HUB%')
).group_by(
    InvoiceItem.sheet_name
).order_by(
    func.count(InvoiceItem.id).desc()
).all()

if nohub_variations:
    print(f"Found {len(nohub_variations)} variations:")
    for name, count in nohub_variations:
        print(f"  {count:6} records | '{name}'")
else:
    print("  No NO-HUB records found")

# COPPER variations
print("\nCOPPER variations in invoice_items:")
copper_variations = db.query(
    InvoiceItem.sheet_name,
    func.count(InvoiceItem.id)
).execution_options(include_all=True).filter(
    InvoiceItem.sheet_name.ilike('%COPPER%')
).group_by(
    InvoiceItem.sheet_name
).order_by(
    func.count(InvoiceItem.id).desc()
).all()

if copper_variations:
    print(f"Found {len(copper_variations)} variations:")
    for name, count in copper_variations:
        print(f"  {count:6} records | '{name}'")
else:
    print("  No COPPER records found")

# All unique sheet names (top 20)
print("\nAll unique sheet names (top 20):")
all_names = db.query(
    InvoiceItem.sheet_name,
    func.count(InvoiceItem.id)
).execution_options(include_all=True).group_by(
    InvoiceItem.sheet_name
).order_by(
    func.count(InvoiceItem.id).desc()
).limit(20).all()

for name, count in all_names:
    display_name = name if name else '(NULL)'
    print(f"  {count:6} | {display_name}")

print("\n" + "=" * 100)
print("DIAGNOSIS:")
print("=" * 100)

if len(nohub_variations) > 1:
    print("ISSUE FOUND: Multiple NO-HUB variations exist in invoice_items!")
    print("ACTION: Need to update invoice_items table to use canonical names")
else:
    print("OK: NO-HUB variations are consistent (or don't exist)")

if len(copper_variations) > 2:
    print("ISSUE FOUND: Multiple COPPER variations exist in invoice_items!")
    print("ACTION: Need to update invoice_items table to use canonical names")
else:
    print("OK: COPPER variations are consistent")

print("=" * 100 + "\n")

db.close()

