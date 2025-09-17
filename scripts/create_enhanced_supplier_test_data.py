#!/usr/bin/env python3
"""
Enhanced script to create realistic test data for missing important suppliers:
WWPS (FW Webb), Y&S, FlowMark, and others.
Since S3 access is not available, this creates comprehensive sample files.
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

# Enhanced comprehensive supplier data for missing important suppliers
ENHANCED_SUPPLIERS = {
    "wwps": {
        "supplier_name": "FW Webb Plumbing Supply",
        "invoice_data": [
            {
                "filename": "wwps_invoice_001.pdf",
                "content": "FW WEBB PLUMBING SUPPLY\nINVOICE NO: WWP001\nDate: 12/01/2024\nShip To: 123 Industrial Ave\nNew York, NY 10001\n\nItem    Description               Qty    Cost     Amount\n1001    Copper Pipe 1/2\"         10     $8.50    $85.00\n2002    PVC Elbow Joint          15     $2.25    $33.75\n3003    Ball Valve 3/4\"          5      $12.00   $60.00\n\nSubtotal: $178.75\nTax: $14.30\nShipping: $15.00\nTotal: $208.05"
            },
            {
                "filename": "wwps_invoice_002.pdf",
                "content": "FW WEBB PLUMBING SUPPLY\nINVOICE NO: WWP002\nDate: 12/02/2024\nShip To: 456 Construction Blvd\nBrooklyn, NY 11201\n\nItem    Description               Qty    Cost     Amount\n4001    Water Heater Element      2      $45.00   $90.00\n5002    Pipe Insulation 6ft       8      $3.75    $30.00\n6003    Shut-off Valve            4      $18.50   $74.00\n\nSubtotal: $194.00\nTax: $15.52\nShipping: $12.50\nTotal: $222.02"
            },
            {
                "filename": "wwps_invoice_003.pdf",
                "content": "FW WEBB PLUMBING SUPPLY\nINVOICE NO: WWP003\nDate: 12/03/2024\nShip To: 789 Residential St\nQueens, NY 11375\n\nItem    Description               Qty    Cost     Amount\n7001    Toilet Flange             3      $25.00   $75.00\n8002    Wax Ring Seal             6      $4.50    $27.00\n9003    Supply Line 12\"           4      $8.75    $35.00\n\nSubtotal: $137.00\nTax: $10.96\nShipping: $8.00\nTotal: $155.96"
            },
            {
                "filename": "wwps_invoice_004.pdf", 
                "content": "FW WEBB PLUMBING SUPPLY\nINVOICE NO: WWP004\nDate: 12/04/2024\nShip To: 321 Commercial Dr\nManhattan, NY 10013\n\nItem    Description               Qty    Cost     Amount\n1101    Pressure Regulator        1      $85.00   $85.00\n1202    Backflow Preventer        1      $120.00  $120.00\n1303    Water Meter 5/8\"          1      $95.00   $95.00\n\nSubtotal: $300.00\nTax: $24.00\nShipping: $20.00\nTotal: $344.00"
            },
            {
                "filename": "wwps_invoice_005.pdf",
                "content": "FW WEBB PLUMBING SUPPLY\nINVOICE NO: WWP005\nDate: 12/05/2024\nShip To: 654 Housing Complex\nBronx, NY 10451\n\nItem    Description               Qty    Cost     Amount\n2201    Drain Snake 25ft          1      $45.00   $45.00\n2302    Pipe Joint Compound       3      $12.00   $36.00\n2403    Teflon Tape Roll          10     $2.50    $25.00\n\nSubtotal: $106.00\nTax: $8.48\nShipping: $10.00\nTotal: $124.48"
            }
        ]
    },
    "y&s": {
        "supplier_name": "Y & S Plumbing Supply",
        "invoice_data": [
            {
                "filename": "ys_invoice_001.pdf",
                "content": "Y & S PLUMBING SUPPLY\nINVOICE #: YS-001\nDate: 12/01/2024\nShip To: 111 Main Street\nBrooklyn, NY 11205\n\nItem    Description               Qty    Cost     Amount\n3001    Chrome Faucet Set         2      $125.00  $250.00\n3002    Aerator 1.5 GPM          4      $8.50    $34.00\n3003    Supply Hose 18\"           6      $15.00   $90.00\n\nSubtotal: $374.00\nTax: $29.92\nTotal: $403.92"
            },
            {
                "filename": "ys_invoice_002.pdf", 
                "content": "Y & S PLUMBING SUPPLY\nINVOICE #: YS-002\nDate: 12/02/2024\nShip To: 222 Oak Avenue\nQueens, NY 11354\n\nItem    Description               Qty    Cost     Amount\n4001    Shower Head Premium       1      $85.00   $85.00\n4002    Shower Arm Extension      2      $25.00   $50.00\n4003    Drain Assembly            1      $35.00   $35.00\n\nSubtotal: $170.00\nTax: $13.60\nTotal: $183.60"
            },
            {
                "filename": "ys_invoice_003.pdf",
                "content": "Y & S PLUMBING SUPPLY\nINVOICE #: YS-003\nDate: 12/03/2024\nShip To: 333 Pine Street\nManhattan, NY 10001\n\nItem    Description               Qty    Cost     Amount\n5001    Basin Wrench              1      $35.00   $35.00\n5002    Pipe Cutter 1\"            1      $45.00   $45.00\n5003    Plumber's Putty           2      $8.00    $16.00\n\nSubtotal: $96.00\nTax: $7.68\nTotal: $103.68"
            },
            {
                "filename": "ys_invoice_004.pdf",
                "content": "Y & S PLUMBING SUPPLY\nINVOICE #: YS-004\nDate: 12/04/2024\nShip To: 444 Cedar Lane\nBronx, NY 10468\n\nItem    Description               Qty    Cost     Amount\n6001    Toilet Tank Parts Kit     1      $55.00   $55.00\n6002    Flapper Valve 2\"          3      $12.00   $36.00\n6003    Fill Valve Universal      2      $18.00   $36.00\n\nSubtotal: $127.00\nTax: $10.16\nTotal: $137.16"
            },
            {
                "filename": "ys_invoice_005.pdf",
                "content": "Y & S PLUMBING SUPPLY\nINVOICE #: YS-005\nDate: 12/05/2024\nShip To: 555 Elm Street\nStaten Island, NY 10301\n\nItem    Description               Qty    Cost     Amount\n7001    Garbage Disposal 1/2 HP   1      $185.00  $185.00\n7002    Disposal Flange Kit       1      $25.00   $25.00\n7003    Power Cord 3ft            1      $15.00   $15.00\n\nSubtotal: $225.00\nTax: $18.00\nTotal: $243.00"
            }
        ]
    },
    "flowmark": {
        "supplier_name": "Flow Mark Plumbing Supply",
        "invoice_data": [
            {
                "filename": "flowmark_invoice_001.pdf",
                "content": "FLOW MARK PLUMBING SUPPLY\nINVOICE: FM-001\nDate: 12/01/2024\nShip To: 777 Water Street\nNew York, NY 10005\n\nItem    Description               Qty    Cost     Amount\n8001    Flow Restrictor 1.5 GPM   5      $12.00   $60.00\n8002    Water Filter Cartridge    4      $22.50   $90.00\n8003    Pressure Gauge 0-60 PSI   2      $35.00   $70.00\n\nSubtotal: $220.00\nTax: $17.60\nTotal: $237.60"
            },
            {
                "filename": "flowmark_invoice_002.pdf",
                "content": "FLOW MARK PLUMBING SUPPLY\nINVOICE: FM-002\nDate: 12/02/2024\nShip To: 888 Flow Avenue\nBrooklyn, NY 11215\n\nItem    Description               Qty    Cost     Amount\n9001    Mixing Valve Thermostatic 1      $165.00  $165.00\n9002    Temperature Gauge         1      $45.00   $45.00\n9003    Balancing Valve           2      $85.00   $170.00\n\nSubtotal: $380.00\nTax: $30.40\nTotal: $410.40"
            },
            {
                "filename": "flowmark_invoice_003.pdf",
                "content": "FLOW MARK PLUMBING SUPPLY\nINVOICE: FM-003\nDate: 12/03/2024\nShip To: 999 Control Lane\nQueens, NY 11411\n\nItem    Description               Qty    Cost     Amount\n1501    Flow Control Valve 3/4\"   3      $55.00   $165.00\n1502    Check Valve Spring        6      $18.00   $108.00\n1503    Ball Valve Full Port      4      $28.00   $112.00\n\nSubtotal: $385.00\nTax: $30.80\nTotal: $415.80"
            },
            {
                "filename": "flowmark_invoice_004.pdf",
                "content": "FLOW MARK PLUMBING SUPPLY\nINVOICE: FM-004\nDate: 12/04/2024\nShip To: 101 Industrial Park\nBronx, NY 10474\n\nItem    Description               Qty    Cost     Amount\n2001    Expansion Tank 2 Gallon   1      $75.00   $75.00\n2002    Relief Valve 150 PSI      1      $35.00   $35.00\n2003    Pressure Switch           1      $45.00   $45.00\n\nSubtotal: $155.00\nTax: $12.40\nTotal: $167.40"
            },
            {
                "filename": "flowmark_invoice_005.pdf",
                "content": "FLOW MARK PLUMBING SUPPLY\nINVOICE: FM-005\nDate: 12/05/2024\nShip To: 202 Plumbing Row\nManhattan, NY 10014\n\nItem    Description               Qty    Cost     Amount\n2501    Water Softener Salt 40lb  5      $8.00    $40.00\n2502    Resin Cleaner 16oz        2      $15.00   $30.00\n2503    Test Strips Hardness      1      $12.00   $12.00\n\nSubtotal: $82.00\nTax: $6.56\nTotal: $88.56"
            }
        ]
    },
    "ghotam": {
        "supplier_name": "Gotham Plumbing Supply",
        "invoice_data": [
            {
                "filename": "gotham_invoice_001.pdf",
                "content": "GOTHAM PLUMBING SUPPLY\nINVOICE NO: GP-001\nDate: 12/01/2024\nShip To: 1 Gotham Plaza\nNew York, NY 10001\n\nItem    Description               Qty    Cost     Amount\n3501    Emergency Shut-off Valve  1      $125.00  $125.00\n3502    Leak Detection Sensor     2      $65.00   $130.00\n3503    Smart Water Monitor       1      $185.00  $185.00\n\nSubtotal: $440.00\nTax: $35.20\nTotal: $475.20"
            },
            {
                "filename": "gotham_invoice_002.pdf",
                "content": "GOTHAM PLUMBING SUPPLY\nINVOICE NO: GP-002\nDate: 12/02/2024\nShip To: 2 Wayne Tower\nNew York, NY 10002\n\nItem    Description               Qty    Cost     Amount\n4501    High-Pressure Nozzle      3      $45.00   $135.00\n4502    Industrial Hose 50ft      1      $85.00   $85.00\n4503    Quick Connect Fitting     8      $12.50   $100.00\n\nSubtotal: $320.00\nTax: $25.60\nTotal: $345.60"
            },
            {
                "filename": "gotham_invoice_003.pdf",
                "content": "GOTHAM PLUMBING SUPPLY\nINVOICE NO: GP-003\nDate: 12/03/2024\nShip To: 3 City Hall\nNew York, NY 10003\n\nItem    Description               Qty    Cost     Amount\n5501    Commercial Drain Cleaner  2      $95.00   $190.00\n5502    Heavy Duty Plunger        4      $25.00   $100.00\n5503    Pipe Inspection Camera    1      $285.00  $285.00\n\nSubtotal: $575.00\nTax: $46.00\nTotal: $621.00"
            }
        ]
    },
    "plumbing_exchange": {
        "supplier_name": "Plumbing Exchange",
        "invoice_data": [
            {
                "filename": "exchange_invoice_001.pdf",
                "content": "PLUMBING EXCHANGE\nINVOICE ID: PX-001\nDate: 12/01/2024\nShip To: 500 Exchange Street\nNew York, NY 10010\n\nItem    Description               Qty    Cost     Amount\n6501    Vintage Brass Faucet      1      $225.00  $225.00\n6502    Classic Drain Stopper     2      $35.00   $70.00\n6503    Heritage Pipe Fittings    5      $18.00   $90.00\n\nSubtotal: $385.00\nTax: $30.80\nTotal: $415.80"
            },
            {
                "filename": "exchange_invoice_002.pdf",
                "content": "PLUMBING EXCHANGE\nINVOICE ID: PX-002\nDate: 12/02/2024\nShip To: 600 Trade Avenue\nBrooklyn, NY 11201\n\nItem    Description               Qty    Cost     Amount\n7501    Reclaimed Copper Pipe     10     $15.00   $150.00\n7502    Restored Valve Handle     4      $45.00   $180.00\n7503    Antique Pipe Wrench       1      $85.00   $85.00\n\nSubtotal: $415.00\nTax: $33.20\nTotal: $448.20"
            },
            {
                "filename": "exchange_invoice_003.pdf",
                "content": "PLUMBING EXCHANGE\nINVOICE ID: PX-003\nDate: 12/03/2024\nShip To: 700 Collector Lane\nQueens, NY 11375\n\nItem    Description               Qty    Cost     Amount\n8501    Historic Radiator Valve   3      $65.00   $195.00\n8502    Period Fixture Mount      2      $55.00   $110.00\n8503    Original Gasket Set       1      $35.00   $35.00\n\nSubtotal: $340.00\nTax: $27.20\nTotal: $367.20"
            }
        ]
    }
}

def create_realistic_pdf(content: str, output_path: Path):
    """Create a more realistic PDF with proper formatting."""
    c = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter
    
    # Parse content into sections
    lines = content.split('\n')
    y_position = height - 50
    
    # Header formatting
    header_found = False
    for i, line in enumerate(lines):
        if y_position < 50:  # Start new page if needed
            c.showPage()
            y_position = height - 50
        
        # Format based on content type
        if not header_found and any(word in line.upper() for word in ['SUPPLY', 'PLUMBING']):
            # Supplier header - larger font
            c.setFont("Helvetica-Bold", 16)
            header_found = True
        elif 'INVOICE' in line.upper():
            # Invoice number - medium font
            c.setFont("Helvetica-Bold", 12)
        elif line.startswith('Item') and 'Description' in line:
            # Table header - bold
            c.setFont("Helvetica-Bold", 10)
        elif any(char.isdigit() for char in line) and '$' in line:
            # Table data - monospace for alignment
            c.setFont("Courier", 9)
        elif line.startswith(('Subtotal:', 'Tax:', 'Total:', 'Shipping:')):
            # Summary lines - bold
            c.setFont("Helvetica-Bold", 10)
        else:
            # Regular text
            c.setFont("Helvetica", 10)
        
        c.drawString(50, y_position, line)
        y_position -= 20
    
    c.save()

def create_comprehensive_excel(supplier_name: str, invoice_data: dict, output_path: Path):
    """Create realistic Excel file based on invoice content."""
    # Parse the invoice content to extract items
    content = invoice_data["content"]
    lines = content.split('\n')
    
    items = []
    in_items_section = False
    
    # Extract invoice metadata
    invoice_date = "12/15/2024"
    invoice_ref = "TEST001"
    customer_job = "Test Location"
    
    for line in lines:
        if 'Date:' in line:
            try:
                invoice_date = line.split('Date:')[1].strip()
            except:
                pass
        elif any(word in line.upper() for word in ['INVOICE', '#', 'NO']):
            try:
                parts = line.split()
                for part in parts:
                    if any(char.isdigit() for char in part) and len(part) > 2:
                        invoice_ref = part
                        break
            except:
                pass
        elif 'Ship To:' in line:
            try:
                customer_job = line.split('Ship To:')[1].strip()
            except:
                pass
        elif line.startswith('Item') and 'Description' in line:
            in_items_section = True
            continue
        elif in_items_section and line.strip():
            # Parse item line
            if line.startswith(('Subtotal:', 'Tax:', 'Total:', 'Shipping:')):
                # Add tax/total lines
                line_type = line.split(':')[0].strip()
                amount = line.split(':')[1].strip() if ':' in line else ""
                items.append({
                    "Item": "10 Materials",
                    "Description": line_type,
                    "Qty": "",
                    "Cost": "",
                    "Amount": amount,
                    "Date": invoice_date,
                    "Ref NO": invoice_ref,
                    "PO #": "PO001",
                    "Customer Job": customer_job,
                    "Bill": "Bill",
                    "Vendor": supplier_name,
                    "Class": "",
                    "Memo": "",
                    "Buyer": "Test Buyer"
                })
                break
            else:
                # Parse regular item line
                parts = line.split()
                if len(parts) >= 4:
                    item_code = parts[0] if parts[0].isdigit() else "1001"
                    description = " ".join(parts[1:-3]) if len(parts) > 4 else "Test Item"
                    qty = parts[-3] if len(parts) >= 3 else "1"
                    cost = parts[-2] if len(parts) >= 2 else "$10.00"
                    amount = parts[-1] if len(parts) >= 1 else "$10.00"
                    
                    items.append({
                        "Item": item_code,
                        "Description": description,
                        "Qty": qty,
                        "Cost": cost,
                        "Amount": amount,
                        "Date": invoice_date,
                        "Ref NO": invoice_ref,
                        "PO #": "PO001",
                        "Customer Job": customer_job,
                        "Bill": "Bill",
                        "Vendor": supplier_name,
                        "Class": "",
                        "Memo": "",
                        "Buyer": "Test Buyer"
                    })
    
    # If no items were parsed, create a default item
    if not items:
        items.append({
            "Item": "10 Materials",
            "Description": "Sample Item",
            "Qty": "1",
            "Cost": "$10.00",
            "Amount": "$10.00",
            "Date": invoice_date,
            "Ref NO": invoice_ref,
            "PO #": "PO001",
            "Customer Job": customer_job,
            "Bill": "Bill",
            "Vendor": supplier_name,
            "Class": "",
            "Memo": "",
            "Buyer": "Test Buyer"
        })
    
    # Create DataFrame and save to Excel
    df = pd.DataFrame(items)
    df.to_excel(output_path, index=False, engine='openpyxl')

def setup_enhanced_supplier_data():
    """Set up enhanced test data for missing important suppliers."""
    print("🚀 Creating enhanced test data for missing important suppliers...")
    
    # Create test data directory
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    total_invoices = 0
    total_suppliers = 0
    
    for folder_name, supplier_data in ENHANCED_SUPPLIERS.items():
        supplier_name = supplier_data["supplier_name"]
        supplier_folder = TEST_DATA_DIR / folder_name
        supplier_folder.mkdir(exist_ok=True)
        
        print(f"\n⭐ Creating {supplier_name} -> {folder_name}")
        print(f"   Generating {len(supplier_data['invoice_data'])} invoices")
        
        supplier_success = 0
        
        for invoice_info in supplier_data["invoice_data"]:
            filename = invoice_info["filename"]
            content = invoice_info["content"]
            
            try:
                # Create realistic PDF file
                pdf_path = supplier_folder / filename
                create_realistic_pdf(content, pdf_path)
                print(f"   📄 Created PDF: {filename}")
                
                # Create expected Excel file
                excel_filename = filename.replace('.pdf', '_expected.xlsx')
                excel_path = supplier_folder / excel_filename
                create_comprehensive_excel(supplier_name, invoice_info, excel_path)
                print(f"   📊 Created Excel: {excel_filename}")
                
                supplier_success += 1
                total_invoices += 1
                
            except Exception as e:
                print(f"   ❌ Failed to create {filename}: {e}")
                continue
        
        if supplier_success > 0:
            total_suppliers += 1
            print(f"   ✅ {supplier_name}: {supplier_success}/{len(supplier_data['invoice_data'])} files created")
        else:
            print(f"   ❌ {supplier_name}: No files created")
    
    print(f"\n🎉 Enhanced test data creation complete!")
    print(f"   Suppliers: {total_suppliers}/{len(ENHANCED_SUPPLIERS)}")
    print(f"   Total invoices: {total_invoices}")
    print(f"   Test directory: {TEST_DATA_DIR}")
    
    return total_suppliers, total_invoices

if __name__ == "__main__":
    setup_enhanced_supplier_data()
