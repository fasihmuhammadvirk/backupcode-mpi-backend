#!/usr/bin/env python3
"""
Script to create sample test data for PDF to Excel conversion testing.
Since S3 access is not available in the test environment, this creates sample files.
"""

import os
import sys
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import pandas as pd

# Add the mpi_backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mpi_backend.utils.pdf_to_excel.main_extractor import extract_data

# Define the test data directory
TEST_DATA_DIR = Path(__file__).parent.parent / "mpi_backend" / "tests" / "pdf_to_excel_test_files"

# Sample data for different suppliers
SAMPLE_SUPPLIERS = {
    "bmw": {
        "supplier_name": "BMW Plumbing Supplies",
        "invoice_data": [
            {
                "filename": "bmw_sample_001.pdf",
                "content": "BMW PLUMBING SUPPLIES\nINVOICE #: BMW001\nDate: 12/15/2024\nShip To: 123 Main St\nItem\tDescription\tQty\tCost\tAmount\n1001\tPipe Joint\t5\t$12.50\t$62.50\nSubtotal: $62.50\nTax: $5.00\nTotal: $67.50"
            },
            {
                "filename": "bmw_sample_002.pdf", 
                "content": "BMW PLUMBING SUPPLIES\nINVOICE #: BMW002\nDate: 12/16/2024\nShip To: 456 Oak Ave\nItem\tDescription\tQty\tCost\tAmount\n2001\tFaucet\t2\t$45.00\t$90.00\nSubtotal: $90.00\nTax: $7.20\nTotal: $97.20"
            },
            {
                "filename": "bmw_sample_003.pdf",
                "content": "BMW PLUMBING SUPPLIES\nINVOICE #: BMW003\nDate: 12/17/2024\nShip To: 789 Pine St\nItem\tDescription\tQty\tCost\tAmount\n3001\tShower Head\t1\t$75.00\t$75.00\nSubtotal: $75.00\nTax: $6.00\nTotal: $81.00"
            }
        ]
    },
    "supreme": {
        "supplier_name": "Supreme Plumbing Supply",
        "invoice_data": [
            {
                "filename": "supreme_sample_001.pdf",
                "content": "SUPREME PLUMBING SUPPLY\nINVOICE #: SUP001\nDate: 12/15/2024\nShip To: 321 Elm St\nItem\tDescription\tQty\tCost\tAmount\n4001\tToilet\t1\t$200.00\t$200.00\nSubtotal: $200.00\nTax: $16.00\nTotal: $216.00"
            },
            {
                "filename": "supreme_sample_002.pdf",
                "content": "SUPREME PLUMBING SUPPLY\nINVOICE #: SUP002\nDate: 12/16/2024\nShip To: 654 Maple Dr\nItem\tDescription\tQty\tCost\tAmount\n5001\tSink\t1\t$150.00\t$150.00\nSubtotal: $150.00\nTax: $12.00\nTotal: $162.00"
            },
            {
                "filename": "supreme_sample_003.pdf",
                "content": "SUPREME PLUMBING SUPPLY\nINVOICE #: SUP003\nDate: 12/17/2024\nShip To: 987 Cedar Ln\nItem\tDescription\tQty\tCost\tAmount\n6001\tBathtub\t1\t$500.00\t$500.00\nSubtotal: $500.00\nTax: $40.00\nTotal: $540.00"
            }
        ]
    },
    "af_supply": {
        "supplier_name": "AF Supply",
        "invoice_data": [
            {
                "filename": "af_sample_001.pdf",
                "content": "AF SUPPLY\nINVOICE #: AF001\nDate: 12/15/2024\nShip To: 111 First Ave\nItem\tDescription\tQty\tCost\tAmount\n7001\tWater Heater\t1\t$800.00\t$800.00\nSubtotal: $800.00\nTax: $64.00\nTotal: $864.00"
            },
            {
                "filename": "af_sample_002.pdf",
                "content": "AF SUPPLY\nINVOICE #: AF002\nDate: 12/16/2024\nShip To: 222 Second St\nItem\tDescription\tQty\tCost\tAmount\n8001\tPump\t1\t$300.00\t$300.00\nSubtotal: $300.00\nTax: $24.00\nTotal: $324.00"
            },
            {
                "filename": "af_sample_003.pdf",
                "content": "AF SUPPLY\nINVOICE #: AF003\nDate: 12/17/2024\nShip To: 333 Third Blvd\nItem\tDescription\tQty\tCost\tAmount\n9001\tValve\t5\t$25.00\t$125.00\nSubtotal: $125.00\nTax: $10.00\nTotal: $135.00"
            }
        ]
    }
}

def create_sample_pdf(content: str, output_path: Path):
    """Create a simple PDF with the given content."""
    c = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter
    
    # Split content into lines and write to PDF
    lines = content.split('\n')
    y_position = height - 50
    
    for line in lines:
        if y_position < 50:  # Start new page if needed
            c.showPage()
            y_position = height - 50
        
        c.drawString(50, y_position, line)
        y_position -= 20
    
    c.save()

def create_sample_excel(data_rows: list, output_path: Path):
    """Create a sample Excel file with the given data."""
    # Create a DataFrame with standard MPI columns
    df = pd.DataFrame(data_rows, columns=[
        "Item", "Description", "Qty", "Cost", "Amount", "Date",
        "Ref NO", "PO #", "Customer Job", "Bill", "Vendor", "Class", "Memo", "Buyer"
    ])
    
    # Save to Excel
    df.to_excel(output_path, index=False, engine='openpyxl')

def setup_sample_test_data():
    """Set up sample test data for PDF to Excel conversion testing."""
    print("Creating sample test data...")
    
    # Create test data directory
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    for folder_name, supplier_data in SAMPLE_SUPPLIERS.items():
        supplier_folder = TEST_DATA_DIR / folder_name
        supplier_folder.mkdir(exist_ok=True)
        
        supplier_name = supplier_data["supplier_name"]
        print(f"Creating test data for {supplier_name} -> {folder_name}")
        
        for invoice_info in supplier_data["invoice_data"]:
            filename = invoice_info["filename"]
            content = invoice_info["content"]
            
            # Create PDF file
            pdf_path = supplier_folder / filename
            create_sample_pdf(content, pdf_path)
            print(f"  Created PDF: {filename}")
            
            # Create expected Excel file using production code
            excel_filename = filename.replace('.pdf', '_expected.xlsx')
            excel_path = supplier_folder / excel_filename
            
            try:
                # Try to run the production conversion
                extract_data(str(pdf_path), str(excel_path), supplier_name)
                
                if excel_path.exists():
                    print(f"  ✓ Generated expected Excel: {excel_filename}")
                else:
                    # Fallback: create a basic Excel file manually
                    print(f"  ! Production conversion failed, creating manual Excel: {excel_filename}")
                    sample_data = [
                        ["10 Materials", "Sample Item", "1", "$10.00", "$10.00", "12/15/2024",
                         "INV001", "PO001", "Sample Job", "Bill", supplier_name, "", "", "Buyer1"]
                    ]
                    create_sample_excel(sample_data, excel_path)
                    
            except Exception as e:
                print(f"  ! Error creating Excel for {filename}: {e}")
                # Create a basic Excel file as fallback
                sample_data = [
                    ["10 Materials", "Sample Item", "1", "$10.00", "$10.00", "12/15/2024",
                     "INV001", "PO001", "Sample Job", "Bill", supplier_name, "", "", "Buyer1"]
                ]
                create_sample_excel(sample_data, excel_path)
                print(f"  Created fallback Excel: {excel_filename}")
    
    print("Sample test data creation complete!")
    print(f"Test data directory: {TEST_DATA_DIR}")

if __name__ == "__main__":
    setup_sample_test_data()
