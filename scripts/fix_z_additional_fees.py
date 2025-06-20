#!/usr/bin/env python3
"""
Fix (Z, ADDITIONAL FEES) Classification
Updates the category from null to 'M' in both JSON file and database
Robust version with proper database connection handling
"""

import json
import sys
import os
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

def test_database_connection():
    """Test database connection before proceeding"""
    print(" Testing database connection...")
    
    try:
        from mpi_backend.database import SessionLocal
        from mpi_backend.database.models.ItemClassification import ItemClassification
        
        # Test connection
        db = SessionLocal()
        
        # Simple query to test connection
        test_query = db.query(ItemClassification).limit(1).first()
        db.close()
        
        print("    Database connection successful")
        return True
        
    except ImportError as e:
        print(f"   ❌ Import error: {e}")
        print("    Make sure you're running from the project root directory")
        return False
    except Exception as e:
        print(f"   ❌ Database connection failed: {e}")
        print("    Check your database configuration and ensure the database is running")
        return False

def check_project_structure():
    """Verify we're in the correct project directory"""
    print(" Checking project structure...")
    
    required_files = [
        'mpi_backend/storage/fixtures/item-classifications.json',
        'mpi_backend/database/__init__.py',
        'mpi_backend/database/models/ItemClassification.py'
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print(f"   ❌ Missing required files:")
        for file_path in missing_files:
            print(f"      - {file_path}")
        print("    Please run this script from the project root directory")
        return False
    
    print("    Project structure verified")
    return True

def update_json_file():
    """Update the JSON file to set (Z, ADDITIONAL FEES) category to 'M'"""
    
    json_path = 'mpi_backend/storage/fixtures/item-classifications.json'
    
    print(" Updating JSON file...")
    
    try:
        # Read current JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Find and update the item
        updated = False
        for item in data:
            if item.get('item') == '(Z, ADDITIONAL FEES)':
                old_category = item.get('category')
                item['category'] = 'M'
                print(f"    Updated JSON: '{item['item']}' category: {old_category} → 'M'")
                updated = True
                break
        
        if not updated:
            print("   ⚠  Item '(Z, ADDITIONAL FEES)' not found in JSON file")
            return False
        
        # Create backup before updating
        backup_path = f"{json_path}.backup"
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"    Backup created: {backup_path}")
        
        # Write updated JSON back to file
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print("    JSON file updated successfully")
        return True
        
    except FileNotFoundError:
        print(f"   ❌ JSON file not found: {json_path}")
        return False
    except json.JSONDecodeError as e:
        print(f"   ❌ Invalid JSON format: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Error updating JSON file: {e}")
        return False

def update_database():
    """Update the database to set (Z, ADDITIONAL FEES) category to 'M'"""
    
    print(" Updating database...")
    
    try:
        from mpi_backend.database import SessionLocal
        from mpi_backend.database.models.ItemClassification import ItemClassification
    except ImportError as e:
        print(f"   ❌ Import error: {e}")
        return False
    
    db = None
    try:
        # Create database session
        db = SessionLocal()
        
        # Find the item in database
        item = db.query(ItemClassification).filter(
            ItemClassification.item == '(Z, ADDITIONAL FEES)'
        ).first()
        
        if item:
            old_category = item.category
            item.category = 'M'
            db.commit()
            print(f"    Updated database: '{item.item}' category: {old_category} → 'M'")
            return True
        else:
            print("   ⚠  Item '(Z, ADDITIONAL FEES)' not found in database")
            print("    You may need to run the classification sync script first")
            return False
            
    except Exception as e:
        if db:
            db.rollback()
        print(f"   ❌ Error updating database: {e}")
        return False
    finally:
        if db:
            db.close()

def verify_updates():
    """Verify that both JSON and database have been updated correctly"""
    
    print(" Verifying updates...")
    
    # Check JSON file
    json_path = 'mpi_backend/storage/fixtures/item-classifications.json'
    json_updated = False
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for item in data:
            if item.get('item') == '(Z, ADDITIONAL FEES)':
                if item.get('category') == 'M':
                    print("    JSON file: category is 'M'")
                    json_updated = True
                else:
                    print(f"   ❌ JSON file: category is '{item.get('category')}' (should be 'M')")
                break
        else:
            print("   ❌ JSON file: item not found")
    except Exception as e:
        print(f"   ❌ JSON file error: {e}")
    
    # Check database
    db_updated = False
    try:
        from mpi_backend.database import SessionLocal
        from mpi_backend.database.models.ItemClassification import ItemClassification
        
        db = SessionLocal()
        
        item = db.query(ItemClassification).filter(
            ItemClassification.item == '(Z, ADDITIONAL FEES)'
        ).first()
        
        if item:
            if item.category == 'M':
                print("    Database: category is 'M'")
                db_updated = True
            else:
                print(f"   ❌ Database: category is '{item.category}' (should be 'M')")
        else:
            print("   ❌ Database: item not found")
            
        db.close()
        
    except Exception as e:
        print(f"   ❌ Database error: {e}")
    
    return json_updated and db_updated

def test_classification():
    """Test the classification after update"""
    
    print(" Testing classification...")
    
    try:
        from mpi_backend.database import SessionLocal
        from mpi_backend.database.controllers.ItemClassification import ItemClassificationController
        
        db = SessionLocal()
        controller = ItemClassificationController(db)
        
        result = controller.get_classification('(Z, ADDITIONAL FEES)')
        
        if result == 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased':
            print("    Classification test passed: Returns Materials account")
            db.close()
            return True
        elif result == '':
            print("   ❌ Classification test failed: Returns empty string")
            print("    This means the item has null category or is missing")
            db.close()
            return False
        else:
            print(f"   ⚠  Classification test: Returns unexpected account: {result}")
            db.close()
            return False
            
    except Exception as e:
        print(f"   ❌ Classification test error: {e}")
        return False

def get_current_status():
    """Check current status of the item"""
    
    print(" Checking current status...")
    
    try:
        from mpi_backend.database import SessionLocal
        from mpi_backend.database.models.ItemClassification import ItemClassification
        
        db = SessionLocal()
        
        item = db.query(ItemClassification).filter(
            ItemClassification.item == '(Z, ADDITIONAL FEES)'
        ).first()
        
        if item:
            print(f"   Database category: {item.category}")
            
            if item.category == 'M':
                print("    Item already has category 'M' in database")
                status = "already_fixed"
            elif item.category is None:
                print("   ⚠  Item has null category - needs fixing")
                status = "needs_fixing"
            else:
                print(f"   ⚠  Item has category '{item.category}' - will update to 'M'")
                status = "needs_updating"
        else:
            print("   ❌ Item not found in database")
            status = "not_found"
            
        db.close()
        return status
        
    except Exception as e:
        print(f"   ❌ Error checking status: {e}")
        return "error"

def main():
    """Main function with comprehensive error handling"""
    
    print(" FIX (Z, ADDITIONAL FEES) CLASSIFICATION")
    print("=" * 60)
    print("This script will update '(Z, ADDITIONAL FEES)' category from null to 'M'")
    print("in both the JSON file and database.")
    print()
    
    # Step 1: Check project structure
    if not check_project_structure():
        print("\n❌ Project structure check failed")
        print(" Please run this script from the mpi-backend project root directory")
        return False
    
    # Step 2: Test database connection
    if not test_database_connection():
        print("\n❌ Database connection failed")
        print(" Please check your database configuration and ensure it's running")
        return False
    
    # Step 3: Check current status
    status = get_current_status()
    
    if status == "error":
        print("\n❌ Cannot proceed due to errors")
        return False
    elif status == "not_found":
        print("\n❌ Item not found in database")
        print(" You may need to run the classification sync script first")
        return False
    
    # Step 4: Ask for confirmation
    if status == "already_fixed":
        response = input("\nItem already has category 'M'. Update anyway? (y/N): ")
    else:
        response = input("\nProceed with updating category to 'M'? (y/N): ")
    
    if response.lower() != 'y':
        print("❌ Operation cancelled")
        return False
    
    print("\n Starting updates...")
    
    # Step 5: Update JSON file
    json_success = update_json_file()
    
    # Step 6: Update database
    db_success = update_database()
    
    # Step 7: Summary
    print("\n Update Summary:")
    print(f"   JSON file: {' Success' if json_success else '❌ Failed'}")
    print(f"   Database:  {' Success' if db_success else '❌ Failed'}")
    
    if json_success and db_success:
        print("\n Verification...")
        if verify_updates():
            print("\n Final test...")
            if test_classification():
                print("\n SUCCESS!")
                print(" (Z, ADDITIONAL FEES) category updated to 'M'")
                print(" QuickBooks import should now work for this item")
                print(" Item will be assigned to Materials account")
                return True
            else:
                print("\n⚠  Updates completed but classification test failed")
        else:
            print("\n❌ Verification failed")
    else:
        print("\n❌ Some updates failed - check the errors above")
    
    return False

if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\n Script completed successfully!")
        else:
            print("\n⚠  Script completed with issues - please review the output above")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n❌ Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1) 