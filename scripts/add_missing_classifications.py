#!/usr/bin/env python3
"""
Script to add missing item classifications from item-mapping.json
This script ONLY ADDS missing classifications - it does NOT overwrite existing ones.
"""

import json
import os
from datetime import datetime

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
    
    print("🔍 Loading existing classifications...")
    classifications_data = load_json_file('mpi_backend/storage/fixtures/item-classifications.json')
    if not classifications_data:
        return None, None
    
    print("🔍 Loading item mappings...")
    mappings_data = load_json_file('mpi_backend/storage/fixtures/item-mapping.json')
    if not mappings_data:
        return None, None
    
    # Get existing sheet names from classifications
    existing_sheet_names = set()
    for item in classifications_data:
        if 'item' in item and item['item']:
            existing_sheet_names.add(item['item'])
    
    print(f"✅ Found {len(existing_sheet_names)} existing classifications")
    
    # Get all sheet names from mappings
    mapping_sheet_names = set()
    for item in mappings_data:
        if 'google_sheet_name' in item and item['google_sheet_name']:
            sheet_name = item['google_sheet_name'].strip()
            if sheet_name:  # Only add non-empty sheet names
                mapping_sheet_names.add(sheet_name)
    
    print(f"✅ Found {len(mapping_sheet_names)} unique sheet names in mappings")
    
    # Find missing sheet names
    missing_sheet_names = mapping_sheet_names - existing_sheet_names
    missing_sheet_names = sorted(list(missing_sheet_names))
    
    print(f"\n📊 Analysis Results:")
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

def add_missing_classifications(missing_sheet_names, existing_data):
    """Add missing classifications to the existing data"""
    
    if not missing_sheet_names:
        print("\n✅ No missing classifications found! Your system is up to date.")
        return False
    
    print(f"\n❌ Missing sheet names that need to be added:")
    for i, sheet_name in enumerate(missing_sheet_names, 1):
        print(f"   {i:2d}. '{sheet_name}'")
    
    # Ask for confirmation
    print(f"\n⚠️  This will add {len(missing_sheet_names)} new classifications to your existing ones.")
    print(f"⚠️  Existing classifications will NOT be modified.")
    response = input(f"\nProceed with adding {len(missing_sheet_names)} missing classifications? (y/N): ")
    
    if response.lower() != 'y':
        print("❌ Operation cancelled by user")
        return False
    
    # Create new classifications
    print(f"\n🔧 Creating new classifications...")
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
    
    # Combine existing and new data (preserving existing ones)
    updated_data = existing_data + new_classifications
    
    # Sort by item name for better organization
    updated_data.sort(key=lambda x: x.get('item', ''))
    
    # Create backup
    backup_filename = f"mpi_backend/storage/fixtures/item-classifications.json.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print(f"\n💾 Creating backup: {backup_filename}")
    try:
        with open('mpi_backend/storage/fixtures/item-classifications.json', 'r') as original:
            with open(backup_filename, 'w') as backup:
                backup.write(original.read())
        print(f"✅ Backup created successfully")
    except Exception as e:
        print(f"⚠️  Warning: Could not create backup: {e}")
        response = input("Continue without backup? (y/N): ")
        if response.lower() != 'y':
            print("❌ Operation cancelled")
            return False
    
    # Write updated data
    print(f"💾 Updating item-classifications.json...")
    try:
        with open('mpi_backend/storage/fixtures/item-classifications.json', 'w', encoding='utf-8') as f:
            json.dump(updated_data, f, indent=2, ensure_ascii=False)
        print(f"✅ File updated successfully")
        
        # Generate SQL script
        generate_sql_script(new_classifications)
        
        print(f"\n🎉 SUCCESS! Added {len(new_classifications)} new classifications")
        print(f"   - Total classifications now: {len(updated_data)}")
        print(f"   - Existing classifications: PRESERVED")
        print(f"   - New classifications: {len(new_classifications)} ADDED")
        
        # Check if the specific problematic classification was added
        if any(c['item'] == '(NO-HUB FITTINGS)' for c in new_classifications):
            print(f"\n🎯 QUICKBOOKS ISSUE FIXED:")
            print(f"   - Added '(NO-HUB FITTINGS)' classification")
            print(f"   - Your QuickBooks import should now work!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error writing file: {e}")
        return False

def generate_sql_script(new_classifications):
    """Generate SQL script for database updates"""
    
    sql_filename = f"add_missing_classifications_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    
    print(f"\n📝 Generating SQL script: {sql_filename}")
    
    try:
        with open(sql_filename, 'w') as f:
            f.write("-- SQL script to add missing item classifications\n")
            f.write("-- This script adds ONLY the missing classifications\n")
            f.write(f"-- Total new classifications: {len(new_classifications)}\n\n")
            
            for classification in new_classifications:
                item_name = classification['item'].replace("'", "''")  # Escape quotes
                category = classification['category']
                f.write(f"INSERT INTO item_classification (item, category) VALUES ('{item_name}', '{category}');\n")
            
            f.write(f"\n-- End of script ({len(new_classifications)} classifications added)\n")
        
        print(f"✅ SQL script generated: {sql_filename}")
        print(f"   Run this script in your database to complete the fix")
        
    except Exception as e:
        print(f"❌ Error generating SQL script: {e}")

def main():
    """Main function"""
    print("=" * 60)
    print("🔧 ADD MISSING ITEM CLASSIFICATIONS")
    print("=" * 60)
    print("This script will:")
    print("1. Find sheet names in item-mapping.json that don't exist in item-classifications.json")
    print("2. ADD missing classifications (existing ones are preserved)")
    print("3. Generate SQL script for database updates")
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
    
    # Find and add missing classifications
    missing_sheet_names, existing_data = find_missing_classifications()
    
    if missing_sheet_names is None:
        return
    
    if add_missing_classifications(missing_sheet_names, existing_data):
        print(f"\n🚀 NEXT STEPS:")
        print(f"   1. ✅ JSON file updated with new classifications")
        print(f"   2. 🔄 Run the generated SQL script in your database")
        print(f"   3. 🎯 Test your QuickBooks import - it should work now!")

if __name__ == "__main__":
    main() 