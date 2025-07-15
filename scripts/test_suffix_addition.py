#!/usr/bin/env python3
"""
Test script to verify suffix addition functionality.

This script tests that when items are inserted into the database,
they automatically get the correct suffix added based on vendor information.
"""

import sys
import os
import pandas as pd
from datetime import datetime

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpi_backend.database import get_db
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.controllers.invoice import InvoiceController

def test_suffix_addition():
    """Test that items get proper suffixes when inserted."""
    
    print("🧪 Testing Suffix Addition Functionality")
    print("=" * 50)
    
    # Test data with different vendors and items
    test_cases = [
        {
            'vendor': 'BMW Plumbing Supplies',
            'item': 'ABC123',
            'expected_suffix': 'B',
            'expected_result': 'ABC123-B'
        },
        {
            'vendor': 'World Wide Plumbing',
            'item': 'XYZ789',
            'expected_suffix': 'W',
            'expected_result': 'XYZ789-W'
        },
        {
            'vendor': 'Y & S Plumbing Supply',
            'item': 'DEF456',
            'expected_suffix': 'Y',
            'expected_result': 'DEF456-Y'
        },
        {
            'vendor': 'Plumbing Exchange',
            'item': 'GHI789',
            'expected_suffix': None,
            'expected_result': 'GHI789'  # No suffix for Plumbing Exchange
        },
        {
            'vendor': 'BMW Plumbing Supplies',
            'item': 'TAX001',
            'expected_suffix': None,
            'expected_result': 'TAX001'  # Tax items should not get suffixes
        }
    ]
    
    print("Testing suffix addition logic...")
    
    db = next(get_db())
    try:
        controller = InvoiceItemController(db)
        
        for i, test_case in enumerate(test_cases, 1):
            vendor = test_case['vendor']
            item = test_case['item']
            expected_suffix = test_case['expected_suffix']
            expected_result = test_case['expected_result']
            
            # Test the suffix addition method directly
            result = controller._add_suffix_to_item(item, vendor)
            
            # Check if result matches expected
            if result == expected_result:
                status = "✅ PASS"
            else:
                status = "❌ FAIL"
            
            print(f"Test {i}: {vendor} - {item}")
            print(f"  Expected: {expected_result}")
            print(f"  Got:      {result}")
            print(f"  Status:   {status}")
            print()
    finally:
        db.close()
    print("🎉 Suffix addition test completed!")

def test_database_insertion():
    """Test that items are stored with suffixes in the database."""
    print("\n🗄️  Testing Database Insertion with Suffixes")
    print("=" * 50)
    # Create test data
    test_data = {
        'Item': 'TEST123',
        'Description': 'Test Item',
        'Qty': 1,
        'Cost': 10.00,
        'Amount': '10.00',
        'Date': '07/15/2025',
        'Ref NO': 'TEST-REF-001',
        'PO #': 'TEST-PO-001',
        'Customer Job': 'Test Job',
        'Bill': 'Test Bill',
        'Vendor': 'BMW Plumbing Supplies',
        'Class': 'Test Class',
        'Memo': 'Test Memo',
        'Buyer': 'Test Buyer',
        'Sheet Name': 'Test Sheet',
        'MpiItem': 'No Match',
        'MpiDescription': 'No Match',
        'email_date': '2025-07-15'
    }
    try:
        db = next(get_db())
        # Create a test invoice first
        invoice_controller = InvoiceController(db)
        invoice_record = invoice_controller.insert_invoice(
            '07/15/2025', 'test_file.pdf', 1, 'PROCESSING', 'test_file.pdf'
        )
        # Insert test item
        item_controller = InvoiceItemController(db)
        item_controller.insert_invoice_items(
            test_data, 'test_file.pdf', invoice_record.id
        )
        # Retrieve the item to check if suffix was added
        items = item_controller.get_invoice_items(invoice_record.id)
        if items:
            stored_item = items[0].item
            expected_item = 'TEST123-B'  # Should have BMW suffix
            if stored_item == expected_item:
                print("✅ PASS: Item stored with correct suffix")
                print(f"   Stored: {stored_item}")
                print(f"   Expected: {expected_item}")
            else:
                print("❌ FAIL: Item not stored with correct suffix")
                print(f"   Stored: {stored_item}")
                print(f"   Expected: {expected_item}")
            # Clean up - delete test data
            db.query(InvoiceItem).filter_by(invoice_id=invoice_record.id).delete()
            db.query(Invoice).filter_by(id=invoice_record.id).delete()
            db.commit()
        else:
            print("❌ FAIL: No items found after insertion")
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    # Import required models
    from mpi_backend.database.models.InvoiceItems import InvoiceItem
    from mpi_backend.database.models.invoice import Invoice
    
    test_suffix_addition()
    test_database_insertion()
    
    print("\n🎯 All tests completed!") 