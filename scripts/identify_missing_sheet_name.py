#!/usr/bin/env python3
"""
Script to identify invoice items with empty sheet names where MPI item 
isn't "No Match" and doesn't start with "UIDI", then export them to Excel.
"""

import pandas as pd
import os
import sys
from sqlalchemy import and_, not_, or_
from sqlalchemy.orm import Session
import uuid

# Add the parent directory to sys.path to allow imports from mpi_backend
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

# Import database components
from mpi_backend.database import SessionLocal
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url


def get_problematic_items(db: Session):
    """
    Query invoice items with empty sheet_name where:
    - mpi_item is not "No Match"
    - mpi_item doesn't start with "UIDI"
    """
    return db.query(InvoiceItem).filter(
        and_(
            or_(
                InvoiceItem.sheet_name.is_(None),  # None values
                InvoiceItem.sheet_name == ''     # Empty strings
            ),
            InvoiceItem.mpi_item != 'No Match',
            not_(InvoiceItem.mpi_item.startswith('UIDI'))
        )
    ).all()


def export_to_excel(items, output_dir=None):
    """
    Export the problematic items to an Excel file
    
    Args:
        items: List of InvoiceItem objects
        output_dir: Directory to save the file (default: project root)
    
    Returns:
        Tuple of (local_file_path, s3_file_key)
    """
    # Set default output directory to project root if not specified
    if output_dir is None:
        # Get the directory two levels up from this script
        # (script is in scripts/, so two levels up is project root)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.dirname(script_dir)
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate a unique filename with timestamp
    file_name = f'problematic_items_{uuid.uuid4().hex[:8]}.xlsx'
    output_file = os.path.join(output_dir, file_name)
    
    # Create a list of dictionaries with the required data
    data = []
    for item in items:
        data.append({
            'ref_no': item.ref_no,
            'org_item': item.item,
            'org_description': item.description,
            'mpi_item': item.mpi_item,
            'mpi_description': item.mpi_description,
        })
    
    # Convert to DataFrame and export
    if data:
        df = pd.DataFrame(data)
        df.to_excel(output_file, index=False)
        print(f"Exported {len(data)} items to {output_file}")
        
        # Generate S3 file key (path within S3 bucket)
        s3_file_key = f'reports/{file_name}'
        
        return output_file, s3_file_key
    else:
        print("No problematic items found.")
        return None, None


def upload_to_s3_and_get_link(local_file_path, s3_file_key):
    """
    Upload the Excel file to S3 and generate a download link
    
    Args:
        local_file_path: Path to the local Excel file
        s3_file_key: Key for the file in S3 bucket
        
    Returns:
        Presigned URL for downloading the file
    """
    if not local_file_path or not s3_file_key:
        return None
        
    try:
        # Upload to S3
        upload_file(local_file_path, s3_file_key, is_invoice=False)
        
        # Generate presigned URL
        presigned_url = get_presigned_url(
            s3_file_key, 
            expiration_time=3600, 
            is_invoice=False
        )
        
        print(f"Download link: {presigned_url}")
        print("Link will expire in 1 hour")
        
        return presigned_url
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return None


def main():
    """Main function to run the script"""
    db = SessionLocal()
    try:
        print("Searching for problematic items...")
        items = get_problematic_items(db)
        
        local_file_path, s3_file_key = export_to_excel(items)
        
        if local_file_path:
            download_link = upload_to_s3_and_get_link(
                local_file_path, 
                s3_file_key
            )
            if download_link:
                print("File uploaded to S3 successfully.")
                print(f"Download link: {download_link}")
            else:
                print(
                    "Failed to generate download link. "
                    "File is available locally at:"
                )
                print(local_file_path)
    finally:
        db.close()


if __name__ == "__main__":
    main()