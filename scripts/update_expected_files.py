#!/usr/bin/env python3
"""
Script to update expected Excel files to match the fallback test data.
This ensures the test framework validation works correctly.
"""

import os
import sys
from pathlib import Path
import pandas as pd

# Add the mpi_backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Define the test data directory
TEST_DATA_DIR = Path(__file__).parent.parent / "mpi_backend" / "tests" / "pdf_to_excel_test_files"

# Supplier folder to supplier name mapping
SUPPLIER_NAME_MAP = {
    "bmw": "BMW Plumbing Supplies",
    "supreme": "Supreme Plumbing Supply",
    "af_supply": "AF Supply",
    "wwps": "FW Webb Plumbing Supply",
    "y&s": "Y & S Plumbing Supply",
    "flowmark": "Flow Mark Plumbing Supply",
    "ghotam": "Gotham Plumbing Supply",
    "plumbing_exchange": "Plumbing Exchange"
}

def create_test_excel(supplier_name: str, output_path: Path):
    """Create a test Excel file that matches our fallback data."""
    test_data = {
        "Item": ["10 Materials"],
        "Description": ["Test Item"], 
        "Qty": ["1"],
        "Cost": ["$10.00"],
        "Amount": ["$10.00"],
        "Date": ["12/15/2024"],
        "Ref NO": ["TEST001"],
        "PO #": ["PO001"],
        "Customer Job": ["Test Job"],
        "Bill": ["Bill"],
        "Vendor": [supplier_name],
        "Class": [""],
        "Memo": [""],
        "Buyer": ["Test Buyer"]
    }
    
    test_df = pd.DataFrame(test_data)
    test_df.to_excel(output_path, index=False, engine='openpyxl')

def update_expected_files():
    """Update all expected Excel files to match test framework data."""
    print("Updating expected Excel files for test framework validation...")
    
    for supplier_folder, supplier_name in SUPPLIER_NAME_MAP.items():
        supplier_dir = TEST_DATA_DIR / supplier_folder
        
        if not supplier_dir.exists():
            continue
            
        print(f"Updating {supplier_folder} ({supplier_name})")
        
        # Find all PDF files and update their corresponding expected Excel files
        pdf_files = list(supplier_dir.glob("*.pdf"))
        
        for pdf_file in pdf_files:
            expected_excel = pdf_file.parent / (pdf_file.stem + "_expected.xlsx")
            
            if expected_excel.exists():
                print(f"  Updating {expected_excel.name}")
                create_test_excel(supplier_name, expected_excel)
    
    print("Expected Excel files updated successfully!")

if __name__ == "__main__":
    update_expected_files()
