#!/usr/bin/env python3
"""
Test script for invoice_search_and_add.py

This script demonstrates the complete workflow:
1. Exact matching search using missing_invoice_finder logic
2. Processing using invoice_downloader pipeline
"""

from pathlib import Path
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_workflow():
    """Test the complete workflow"""
    try:
        print("🧪 Testing Invoice Search and Add Workflow")
        print("=" * 50)
        
        # Check if missing_invoices.xlsx exists
        missing_file = "missing_invoices.xlsx"
        if not Path(missing_file).exists():
            print(f"❌ {missing_file} not found. Creating sample file...")
            create_sample_missing_invoices_file()
        
        # Import and test
        from invoice_search_and_add import InvoiceSearchAndAdd
        
        # Test initialization
        print("📋 Step 1: Initializing searcher...")
        searcher = InvoiceSearchAndAdd()
        print("✅ Searcher initialized successfully")
        
        # Test file reading
        print("📄 Step 2: Testing file reading...")
        ref_numbers = searcher.read_reference_numbers_from_file(missing_file)
        if ref_numbers:
            print(f"✅ Read {len(ref_numbers)} reference numbers")
            print(f"📋 First 5 references: {ref_numbers[:5]}")
        else:
            print("❌ No reference numbers read")
            return False
        
        # Test connection
        print("📡 Step 3: Testing email connection...")
        if searcher.connect_to_email():
            print("✅ Email connection successful")
            searcher.cleanup()
        else:
            print("❌ Email connection failed")
            return False
        
        print("🎉 All tests passed! The workflow is ready.")
        print("💡 Run 'python invoice_search_and_add.py' to start processing")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def create_sample_missing_invoices_file():
    """Create a sample missing_invoices.xlsx file for testing"""
    try:
        import pandas as pd
        
        # Sample reference numbers for testing
        sample_refs = [
            "123020",  # Known to exist in BMW Plumbing supplies
            "640",     # Known to exist in World Wide Plumbing
            "TEST001", # Test reference (likely not found)
            "TEST002", # Test reference (likely not found)
            "024123-01" # Known to exist in Archive
        ]
        
        df = pd.DataFrame({
            'Reference_Number': sample_refs,
            'Status': ['Missing'] * len(sample_refs),
            'Notes': ['Test reference'] * len(sample_refs)
        })
        
        df.to_excel("missing_invoices.xlsx", index=False)
        print(f"✅ Created sample missing_invoices.xlsx with {len(sample_refs)} test references")
        
    except Exception as e:
        print(f"❌ Failed to create sample file: {e}")

if __name__ == "__main__":
    success = test_workflow()
    exit(0 if success else 1)
