#!/usr/bin/env python3
"""
Quick test to verify statement S3 key issues
"""

import sys
import os
import boto3

# Add parent directory to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database.models.statement_models import PlumbingStatement
from mpi_backend.database import get_db
from mpi_backend.config import (
    AWS_SERVER_PUBLIC_KEY, 
    AWS_SERVER_SECRET_KEY, 
    REGION, 
    BUCKET_NAME
)

def test_statement_s3_keys():
    """Test statement S3 key accessibility"""
    print("Testing statement S3 key accessibility...")
    
    # Initialize S3 client
    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_SERVER_PUBLIC_KEY,
        aws_secret_access_key=AWS_SERVER_SECRET_KEY,
        region_name=REGION
    )
    
    # Get database connection
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        # Get a few sample statements
        statements = db.query(PlumbingStatement).filter(
            PlumbingStatement.pdf_filename.isnot(None),
            PlumbingStatement.pdf_filename != ''
        ).limit(5).all()
        
        print(f"Testing {len(statements)} statements:")
        
        for stmt in statements:
            print(f"\nStatement ID: {stmt.id}")
            print(f"PDF filename: {stmt.pdf_filename}")
            
            # Test different S3 key patterns
            test_keys = [
                f"statements/{stmt.pdf_filename}",
                f"statements/{stmt.pdf_filename}.pdf",
            ]
            
            for key in test_keys:
                try:
                    s3_client.head_object(Bucket=BUCKET_NAME, Key=key)
                    print(f"  ✅ EXISTS: {key}")
                except s3_client.exceptions.NoSuchKey:
                    print(f"  ❌ MISSING: {key}")
                except Exception as e:
                    print(f"  ⚠️  ERROR: {key} - {e}")
    
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    test_statement_s3_keys() 