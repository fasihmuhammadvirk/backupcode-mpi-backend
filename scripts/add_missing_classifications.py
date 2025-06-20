#!/usr/bin/env python3
"""
Script to add missing item classifications from item-mapping.json
This script:
1. Updates item-classifications.json (preserves existing ones)
2. Updates the database directly
3. Generates SQL script as backup
"""

import json
import os
import sys
from datetime import datetime

# Add the parent directory to Python path to import from mpi_backend
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import database connection from your project
try:
    from mpi_backend.database.connection import get_database_connection
    DATABASE_CONNECTION_AVAILABLE = True
except ImportError:
    DATABASE_CONNECTION_AVAILABLE = False
    print("⚠  Warning: Could not import database connection from mpi_backend")

def load_json_file(filepath):
    """Load JSON file safely"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: File not found: {filepath}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON in {filepath}: {e}")
        return None

def find_missing_classifications():
    """Find sheet names that are missing from classifications"""
    
    print(" Loading existing classifications...")
    classifications_data = load_json_file('mpi_backend/storage/fixtures/item-classifications.json')
    if not classifications_data:
        return None, None
    
    print(" Loading item mappings...")
    mappings_data = load_json_file('mpi_backend/storage/fixtures/item-mapping.json')
    if not mappings_data:
        return None, None
    
    # Get existing sheet names from classifications
    existing_sheet_names = set()
    for item in classifications_data:
        if 'item' in item and item['item']:
            existing_sheet_names.add(item['item'])
    
    print(f" Found {len(existing_sheet_names)} existing classifications")
    
    # Get all sheet names from mappings
    mapping_sheet_names = set()
    for item in mappings_data:
        if 'google_sheet_name' in item and item['google_sheet_name']:
            sheet_name = item['google_sheet_name'].strip()
            if sheet_name:  # Only add non-empty sheet names
                mapping_sheet_names.add(sheet_name)
    
    print(f" Found {len(mapping_sheet_names)} unique sheet names in mappings")
    
    # Find missing sheet names
    missing_sheet_names = mapping_sheet_names - existing_sheet_names
    missing_sheet_names = sorted(list(missing_sheet_names))
    
    print(f"\n Analysis Results:")
    print(f"   - Existing classifications: {len(existing_sheet_names)}")
    print(f"   - Sheet names in mappings: {len(mapping_sheet_names)}")
    print(f"   - Missing classifications: {len(missing_sheet_names)}")
    
    return missing_sheet_names, classifications_data

def determine_category(sheet_name):
    """Determine category for a sheet name (M=Materials, E=Equipment)"""
    sheet_lower = sheet_name.lower()
    
    # Equipment-related keywords
    equipment_keywords = [
        'equipment', 'tool', 'machinery', 'pump', 'motor', 'generator',
        'compressor', 'drill', 'saw', 'grinder', 'welder', 'crane'
    ]
    
    # Check if it's equipment-related
    for keyword in equipment_keywords:
        if keyword in sheet_lower:
            return 'E'
    
    # Default to materials
    return 'M'

def update_database(new_classifications):
    """Update the database with new classifications"""
    
    if not DATABASE_CONNECTION_AVAILABLE:
        print("❌ Database connection not available. Skipping database update.")
        print("   You'll need to run the generated SQL script manually.")
        return False
    
    try:
        print("\n Connecting to database...")
        db = get_database_connection()
        cursor = db.cursor()
        
        print(f" Inserting {len(new_classifications)} new classifications into database...")
        
        inserted_count = 0
        for classification in new_classifications:
            try:
                query = "INSERT INTO item_classification (item, category) VALUES (%s, %s)"
                cursor.execute(query, (classification['item'], classification['category']))
                inserted_count += 1
                print(f"    Added: '{classification['item']}' → {classification['category']}")
            except Exception as e:
                print(f"   ⚠  Warning: Could not insert '{classification['item']}': {e}")
        
        # Commit the changes
        db.commit()
        cursor.close()
        db.close()
        
        print(f"\n Database updated successfully!")
        print(f"   - Inserted: {inserted_count}/{len(new_classifications)} classifications")
        
        return True
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        print("   Falling back to SQL script generation only.")
        return False

def add_missing_classifications(missing_sheet_names, existing_data):
    """Add missing classifications to JSON file and database"""
    
    if not missing_sheet_names:
        print("\n No missing classifications found! Your system is up to date.")
        return False
    
    print(f"\n❌ Missing sheet names that need to be added:")
    for i, sheet_name in enumerate(missing_sheet_names, 1):
        print(f"   {i:2d}. '{sheet_name}'")
    
    # Ask for confirmation
    print(f"\n⚠  This will add {len(missing_sheet_names)} new classifications:")
    print(f"   - To item-classifications.json (preserving existing ones)")
    print(f"   - To the database (item_classification table)")
    response = input(f"\nProceed with adding {len(missing_sheet_names)} missing classifications? (y/N): ")
    
    if response.lower() != 'y':
        print("❌ Operation cancelled by user")
        return False
    
    # Create new classifications
    print(f"\n Creating new classifications...")
    new_classifications = []
    
    for sheet_name in missing_sheet_names:
        category = determine_category(sheet_name)
        
        new_classification = {
            "item": sheet_name,
            "category": category
        }
        
        new_classifications.append(new_classification)
        
        category_name = "Equipment" if category == 'E' else "Materials"
        print(f"   + '{sheet_name}' → Category: {category} ({category_name})")
    
    # Update JSON file
    success_json = update_json_file(existing_data, new_classifications)
    
    # Update database
    success_db = update_database(new_classifications)
    
    # Generate SQL script as backup
    generate_sql_script(new_classifications)
    
    if success_json:
        print(f"\n SUCCESS!")
        print(f"   -  JSON file updated: {len(new_classifications)} classifications added")
        if success_db:
            print(f"   -  Database updated: Classifications inserted")
        else:
            print(f"   - ⚠  Database update failed: Use generated SQL script")
        print(f"   -  SQL script generated as backup")
        
        # Check if the specific problematic classification was added
        if any(c['item'] == '(NO-HUB FITTINGS)' for c in new_classifications):
            print(f"\n QUICKBOOKS ISSUE FIXED:")
            print(f"   - Added '(NO-HUB FITTINGS)' classification")
            print(f"   - Your QuickBooks import should now work!")
        
        return True
    
    return False

def update_json_file(existing_data, new_classifications):
    """Update the JSON file with new classifications"""
    
    # Combine existing and new data (preserving existing ones)
    updated_data = existing_data + new_classifications
    
    # Sort by item name for better organization
    updated_data.sort(key=lambda x: x.get('item', ''))
    
    # Create backup
    backup_filename = f"mpi_backend/storage/fixtures/item-classifications.json.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print(f"\n Creating backup: {backup_filename}")
    try:
        with open('mpi_backend/storage/fixtures/item-classifications.json', 'r') as original:
            with open(backup_filename, 'w') as backup:
                backup.write(original.read())
        print(f" Backup created successfully")
    except Exception as e:
        print(f"⚠  Warning: Could not create backup: {e}")
        response = input("Continue without backup? (y/N): ")
        if response.lower() != 'y':
            print("❌ Operation cancelled")
            return False
    
    # Write updated data
    print(f" Updating item-classifications.json...")
    try:
        with open('mpi_backend/storage/fixtures/item-classifications.json', 'w', encoding='utf-8') as f:
            json.dump(updated_data, f, indent=2, ensure_ascii=False)
        print(f" JSON file updated successfully")
        print(f"   - Total classifications now: {len(updated_data)}")
        print(f"   - Existing classifications: PRESERVED")
        print(f"   - New classifications: {len(new_classifications)} ADDED")
        
        return True
        
    except Exception as e:
        print(f"❌ Error writing JSON file: {e}")
        return False

def generate_sql_script(new_classifications):
    """Generate SQL script for database updates (as backup)"""
    
    sql_filename = f"scripts/add_missing_classifications_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    
    print(f"\n Generating SQL script: {sql_filename}")
    
    try:
        with open(sql_filename, 'w') as f:
            f.write("-- SQL script to add missing item classifications\n")
            f.write("-- This script adds ONLY the missing classifications\n")
            f.write(f"-- Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"-- Total new classifications: {len(new_classifications)}\n\n")
            
            for classification in new_classifications:
                item_name = classification['item'].replace("'", "''")  # Escape quotes
                category = classification['category']
                f.write(f"INSERT INTO item_classification (item, category) VALUES ('{item_name}', '{category}');\n")
            
            f.write(f"\n-- End of script ({len(new_classifications)} classifications added)\n")
        
        print(f" SQL script generated: {sql_filename}")
        print(f"   Use this script as backup or for manual database updates")
        
    except Exception as e:
        print(f"❌ Error generating SQL script: {e}")

def main():
    """Main function"""
    print("=" * 70)
    print(" ADD MISSING ITEM CLASSIFICATIONS (JSON + DATABASE)")
    print("=" * 70)
    print("This script will:")
    print("1. Find missing sheet names from item-mapping.json")
    print("2. ADD them to item-classifications.json (preserving existing)")
    print("3. INSERT them into the database (item_classification table)")
    print("4. Generate SQL script as backup")
    print()
    
    # Check required files
    required_files = [
        'mpi_backend/storage/fixtures/item-classifications.json',
        'mpi_backend/storage/fixtures/item-mapping.json'
    ]
    
    for filepath in required_files:
        if not os.path.exists(filepath):
            print(f"❌ Error: Required file not found: {filepath}")
            return
    
    # Show database connection status
    if DATABASE_CONNECTION_AVAILABLE:
        print(" Database connection available - will update both JSON and database")
    else:
        print("⚠  Database connection not available - will update JSON and generate SQL script")
    
    print()
    
    # Find and add missing classifications
    missing_sheet_names, existing_data = find_missing_classifications()
    
    if missing_sheet_names is None:
        return
    
    if add_missing_classifications(missing_sheet_names, existing_data):
        print(f"\n NEXT STEPS:")
        if DATABASE_CONNECTION_AVAILABLE:
            print(f"   1.  JSON file updated with new classifications")
            print(f"   2.  Database updated with new classifications")
            print(f"   3.  Test your QuickBooks import - it should work now!")
        else:
            print(f"   1.  JSON file updated with new classifications")
            print(f"   2.  Run the generated SQL script in your database")
            print(f"   3.  Test your QuickBooks import - it should work now!")

if __name__ == "__main__":
    main() 