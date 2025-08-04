#!/usr/bin/env python3
"""
Final script to clean up duplicate invoices on Windows server.
This script finds and removes exact duplicates based on ref_no, vendor, date, and total amount.
"""

import sys
from pathlib import Path

# Add the parent directory to the path
sys.path.append(str(Path(__file__).parent.parent))

from mpi_backend.database import get_db
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from collections import defaultdict


def find_all_duplicates(db):
    """Find all duplicate invoices in the database"""
    print("Scanning database for duplicate invoices...")
    
    # Get all active invoice items
    items = db.query(InvoiceItem).filter(
        InvoiceItem.is_active.is_(True),
        InvoiceItem.ref_no.isnot(None),
        InvoiceItem.ref_no != '',
        InvoiceItem.vendor.isnot(None),
        InvoiceItem.vendor != ''
    ).all()
    
    print(f"Total active items: {len(items)}")
    
    # Group by ref_no and vendor
    ref_vendor_groups = defaultdict(list)
    for item in items:
        key = (item.ref_no, item.vendor)
        ref_vendor_groups[key].append(item)
    
    # Find groups with multiple invoice_ids
    duplicates = []
    for (ref_no, vendor), group_items in ref_vendor_groups.items():
        invoice_ids = set(item.invoice_id for item in group_items)
        if len(invoice_ids) > 1:
            # Calculate total amount for each invoice
            invoice_totals = defaultdict(float)
            invoice_dates = {}
            
            for item in group_items:
                invoice_id = item.invoice_id
                try:
                    amount = float(item.amount) if item.amount else 0.0
                    invoice_totals[invoice_id] += amount
                    invoice_dates[invoice_id] = item.date
                except (ValueError, TypeError):
                    continue
            
            # Group by date and total amount
            date_amount_groups = defaultdict(list)
            for invoice_id, total_amount in invoice_totals.items():
                date = invoice_dates[invoice_id]
                key = (date, round(total_amount, 2))
                date_amount_groups[key].append(invoice_id)
            
            # Find exact duplicates
            for (date, total_amount), duplicate_invoice_ids in date_amount_groups.items():
                if len(duplicate_invoice_ids) > 1:
                    duplicates.append({
                        'ref_no': ref_no,
                        'vendor': vendor,
                        'date': date,
                        'total_amount': total_amount,
                        'invoice_ids': duplicate_invoice_ids,
                        'count': len(duplicate_invoice_ids)
                    })
    
    return duplicates


def cleanup_duplicates(db, duplicates):
    """Clean up duplicates by keeping the most recent invoice"""
    print(f"\nFound {len(duplicates)} duplicate groups")
    
    if not duplicates:
        print("No duplicates found!")
        return
    
    # Show duplicates
    for i, dup in enumerate(duplicates, 1):
        print(f"{i}. Ref: {dup['ref_no']}")
        print(f"   Vendor: {dup['vendor']}")
        print(f"   Date: {dup['date']}")
        print(f"   Total Amount: {dup['total_amount']}")
        print(f"   Invoice Count: {dup['count']}")
        print(f"   Invoice IDs: {', '.join(str(id) for id in dup['invoice_ids'])}")
        print()
    
    # Ask for confirmation
    response = input("Delete all duplicates? (yes/no): ").lower().strip()
    if response != 'yes':
        print("Cancelled.")
        return
    
    # Clean up each duplicate group
    cleaned_count = 0
    
    for dup in duplicates:
        try:
            # Keep the most recent invoice (highest invoice_id)
            keep_invoice_id = max(dup['invoice_ids'])
            
            # Mark other invoices as inactive
            for invoice_id in dup['invoice_ids']:
                if invoice_id != keep_invoice_id:
                    items_to_deactivate = db.query(InvoiceItem).filter(
                        InvoiceItem.invoice_id == invoice_id,
                        InvoiceItem.is_active.is_(True)
                    ).all()
                    
                    for item in items_to_deactivate:
                        item.is_active = False
                    
                    print(f"Marked invoice {invoice_id} as inactive")
            
            db.commit()
            cleaned_count += 1
            print(f"Cleaned: {dup['ref_no']} - {dup['vendor']}")
            print(f"Kept invoice: {keep_invoice_id}")
                
        except Exception as e:
            print(f"Error cleaning {dup['ref_no']}: {str(e)}")
            db.rollback()
    
    print(f"\nCleaned {cleaned_count} duplicate groups!")


def main():
    """Main function"""
    print("=== Duplicate Invoice Cleanup (Windows) ===\n")
    
    try:
        db = next(get_db())
        
        # Find duplicates
        duplicates = find_all_duplicates(db)
        
        # Clean up
        cleanup_duplicates(db, duplicates)
        
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        if 'db' in locals():
            db.close()


if __name__ == "__main__":
    main() 