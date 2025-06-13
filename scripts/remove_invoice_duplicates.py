#!/usr/bin/env python3
"""
Simple script to remove duplicate invoice items.
Removes duplicates where ALL fields match exactly.
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Setup environment
script_dir = Path(__file__).parent
project_root = script_dir.parent
os.chdir(project_root)
load_dotenv()
sys.path.insert(0, str(project_root))

from mpi_backend.database import db_context
from sqlalchemy import text

def main():
    print("🧹 Invoice Items Duplicate Removal")
    print("=" * 40)
    
    with db_context() as db:
        # Find duplicates based on specified fields
        print("🔍 Finding duplicates based on your criteria...")
        duplicates = db.execute(text("""
            SELECT 
                item, vendor, description, qty, cost, amount,
                COUNT(*) as count,
                MIN(id) as keep_id,
                ARRAY_AGG(id ORDER BY id) as all_ids
            FROM invoice_items 
            GROUP BY sheet_name, mpi_item, mpi_description, item, description, 
                     qty, cost, amount, date, ref_no, po_number, customer_job, 
                     bill, vendor, class_, buyer, date_added
            HAVING COUNT(*) > 1
            ORDER BY count DESC
        """)).fetchall()
        
        if not duplicates:
            print("✅ No duplicates found based on your criteria!")
            return
        
        total_to_remove = sum(row.count - 1 for row in duplicates)
        print(f"📊 Found {len(duplicates)} duplicate groups")
        print(f"🗑️  Will remove {total_to_remove} duplicate records")
        
        # Show what will be removed
        for i, row in enumerate(duplicates, 1):
            ids_to_remove = [id for id in row.all_ids if id != row.keep_id]
            print(f"{i}. Item: {row.item} | Keep ID: {row.keep_id} | Remove: {ids_to_remove}")
        
        # Confirm removal
        response = input(f"\nRemove {total_to_remove} duplicate records? (yes/no): ").strip().lower()
        
        if response in ['yes', 'y']:
            total_removed = 0
            for row in duplicates:
                ids_to_remove = [id for id in row.all_ids if id != row.keep_id]
                if ids_to_remove:
                    db.execute(text("DELETE FROM invoice_items WHERE id = ANY(:ids)"), 
                             {'ids': ids_to_remove})
                    total_removed += len(ids_to_remove)
            
            db.commit()
            print(f"🎉 Successfully removed {total_removed} duplicate records!")
        else:
            print("❌ Operation cancelled")

if __name__ == "__main__":
    main() 