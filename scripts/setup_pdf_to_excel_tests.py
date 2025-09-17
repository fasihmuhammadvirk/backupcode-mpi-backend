#!/usr/bin/env python3
"""
Script to set up PDF to Excel test data by fetching invoices from database
and downloading them via S3 URLs, then organizing them by supplier.
"""

import os
import sys
import logging
import requests
import uuid
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

# Add the mpi_backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mpi_backend.database import db_context
from mpi_backend.database.models.Invoice import Invoice
from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.utils.s3_utils import get_presigned_url
from mpi_backend.utils.pdf_to_excel.main_extractor import extract_data

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define the test data directory
TEST_DATA_DIR = Path(__file__).parent.parent / "mpi_backend" / "tests" / "pdf_to_excel_test_files"

# Supplier name mapping for the test directories
SUPPLIER_FOLDER_MAP = {
    "BMW Plumbing Supplies": "bmw",
    "FW Webb Plumbing Supply": "wwps", 
    "Y & S Plumbing Supply": "y&s",
    "World Wide Plumbing": "web_co",
    "Pyramid Plumbing": "pyramid",
    "Supreme Plumbing Supply": "supreme",
    "Gotham Plumbing Supply": "ghotam",
    "Flow Mark Plumbing Supply": "flowmark",
    "Plumbing Exchange": "plumbing_exchange",
    "AF Supply": "af_supply",
    "Lion Hvac Supplies": "lion_havac",
    "ABC Opus": "abc_opus"
}

def get_supplier_invoices() -> Dict[str, List[Tuple[Invoice, str]]]:
    """
    Fetch invoices from database grouped by supplier name.
    Returns dict mapping supplier name to list of (invoice, supplier_name) tuples.
    """
    supplier_invoices = defaultdict(list)
    
    with db_context() as db:
        # Query invoices with supplier info
        query = db.query(Invoice, Supplier.supplier_name).join(
            Supplier, Invoice.supplier_id == Supplier.id
        ).filter(
            Invoice.status == 'PROCESSED'  # Only get successfully processed invoices
        ).order_by(
            Supplier.supplier_name, Invoice.date.desc()
        )
        
        results = query.all()
        
        for invoice, supplier_name in results:
            supplier_invoices[supplier_name].append((invoice, supplier_name))
    
    return supplier_invoices

def download_pdf_from_s3(invoice: Invoice, supplier_folder: Path) -> Path:
    """
    Download PDF file from S3 using presigned URL.
    Returns the local file path.
    """
    # Generate presigned URL for the invoice
    presigned_url = get_presigned_url(invoice.storage_path, expiration_time=300)
    
    if not presigned_url:
        raise Exception(f"Could not generate presigned URL for {invoice.storage_path}")
    
    # Create a safe filename
    safe_filename = f"{invoice.filename}"
    if not safe_filename.lower().endswith('.pdf'):
        safe_filename += '.pdf'
    
    local_path = supplier_folder / safe_filename
    
    # Download the file
    logger.info(f"Downloading {invoice.filename} to {local_path}")
    response = requests.get(presigned_url, timeout=60)
    response.raise_for_status()
    
    with open(local_path, 'wb') as f:
        f.write(response.content)
    
    return local_path

def generate_golden_excel(pdf_path: Path, supplier_name: str) -> Path:
    """
    Generate golden Excel file using the current production code.
    Returns the Excel file path.
    """
    excel_path = pdf_path.with_suffix('_expected.xlsx')
    
    logger.info(f"Generating golden Excel for {pdf_path} using supplier '{supplier_name}'")
    
    try:
        # Use the production PDF to Excel conversion logic
        result = extract_data(str(pdf_path), str(excel_path), supplier_name)
        
        # Handle the case where extract_data returns split files
        if isinstance(result, list) and result:
            # If files were split, use the first one as the expected output
            if len(result) > 0 and Path(result[0]).exists():
                excel_path = Path(result[0])
        
        if not excel_path.exists():
            raise Exception(f"Excel file was not generated at {excel_path}")
        
        logger.info(f"Generated golden Excel: {excel_path}")
        return excel_path
        
    except Exception as e:
        logger.error(f"Failed to generate Excel for {pdf_path}: {e}")
        raise

def setup_test_data():
    """
    Main function to set up test data.
    """
    logger.info("Starting PDF to Excel test data setup")
    
    # Create test data directory
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get invoices grouped by supplier
    supplier_invoices = get_supplier_invoices()
    
    logger.info(f"Found {len(supplier_invoices)} suppliers with invoices")
    
    for supplier_name, invoices in supplier_invoices.items():
        # Skip suppliers not in our test mapping
        if supplier_name not in SUPPLIER_FOLDER_MAP:
            logger.info(f"Skipping {supplier_name} - not in test mapping")
            continue
        
        folder_name = SUPPLIER_FOLDER_MAP[supplier_name]
        supplier_folder = TEST_DATA_DIR / folder_name
        supplier_folder.mkdir(exist_ok=True)
        
        logger.info(f"Processing {supplier_name} -> {folder_name}")
        logger.info(f"  Found {len(invoices)} invoices")
        
        # Get up to 3 recent invoices for this supplier
        selected_invoices = invoices[:3]
        
        for i, (invoice, _) in enumerate(selected_invoices):
            try:
                logger.info(f"  Processing invoice {i+1}/{len(selected_invoices)}: {invoice.filename}")
                
                # Download PDF from S3
                pdf_path = download_pdf_from_s3(invoice, supplier_folder)
                
                # Generate golden Excel file
                excel_path = generate_golden_excel(pdf_path, supplier_name)
                
                logger.info(f"  ✓ Completed {invoice.filename}")
                
            except Exception as e:
                logger.error(f"  ✗ Failed to process {invoice.filename}: {e}")
                continue
    
    logger.info("Test data setup complete!")
    logger.info(f"Test data directory: {TEST_DATA_DIR}")

if __name__ == "__main__":
    setup_test_data()
