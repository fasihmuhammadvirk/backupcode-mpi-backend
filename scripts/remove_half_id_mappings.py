#!/usr/bin/env python3
"""
Script to remove item mappings with google_sheet_name "(1/2 ID)" from both
the item-mapping.json file and the database.
"""

import json
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from pathlib import Path

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# Load environment variables
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

from mpi_backend.database import Base
from mpi_backend.database.models.ItemsMapping import ItemsMapping

def remove_mappings_from_json():
    """Remove mappings with google_sheet_name "(1/2 ID)" from the JSON file."""
    json_file_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "mpi_backend", "storage", "fixtures", "item-mapping.json"
    )
    
    # Check if the file exists
    if not os.path.exists(json_file_path):
        print(f"Error: JSON file not found at {json_file_path}")
        return 0
    
    # Load the JSON file
    with open(json_file_path, 'r') as f:
        mappings = json.load(f)
    
    # Count original mappings
    original_count = len(mappings)
    
    # Filter out mappings with google_sheet_name "(1/2 ID)"
    filtered_mappings = [
        mapping for mapping in mappings 
        if mapping.get('google_sheet_name') != "(1/2 ID)"
    ]
    
    # Count removed mappings
    removed_count = original_count - len(filtered_mappings)
    
    # Save the filtered mappings back to the file
    with open(json_file_path, 'w') as f:
        json.dump(filtered_mappings, f, indent=2)
    
    print(f"Removed {removed_count} mappings from JSON file")
    return removed_count

def remove_mappings_from_database():
    """Remove mappings with google_sheet_name "(1/2 ID)" from the database."""
    # Get database connection parameters from environment variables
    postgres_host = os.getenv("POSTGRES_HOST")
    postgres_port = os.getenv("POSTGRES_PORT", "5432")
    postgres_db = os.getenv("POSTGRES_DB")
    postgres_username = os.getenv("POSTGRES_USERNAME")
    postgres_password = os.getenv("POSTGRES_PASSWORD")
    
    # Construct database URL
    database_url = f"postgresql://{postgres_username}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"
    
    # Create database connection
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Delete mappings with google_sheet_name "(1/2 ID)"
        result = session.query(ItemsMapping).filter(
            ItemsMapping.google_sheet_name == "(1/2 ID)"
        ).delete()
        
        # Commit the changes
        session.commit()
        
        print(f"Removed {result} mappings from database")
        return result
    except Exception as e:
        session.rollback()
        print(f"Error removing mappings from database: {str(e)}")
        return 0
    finally:
        session.close()

def main():
    """Main function to run the script."""
    print("Starting removal of mappings with google_sheet_name '(1/2 ID)'...")
    
    # Remove from JSON file
    json_removed = remove_mappings_from_json()
    
    # Remove from database
    db_removed = remove_mappings_from_database()
    
    print(f"Summary: Removed {json_removed} mappings from JSON and {db_removed} mappings from database")

if __name__ == "__main__":
    main()
