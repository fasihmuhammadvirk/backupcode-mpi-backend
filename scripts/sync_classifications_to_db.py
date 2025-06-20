#!/usr/bin/env python3
"""
CRITICAL SCRIPT: Sync Item Classifications from JSON to Database
This script finds all classifications in the JSON file that don't exist in the database
and adds them safely. It uses your existing database connection setup.
"""

import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Optional

# Add the parent directory to Python path to import from mpi_backend
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import your database components
try:
    from mpi_backend.database import SessionLocal, engine
    from mpi_backend.database.models.ItemClassification import ItemClassification
    from mpi_backend.config import SQLALCHEMY_DATABASE_URI
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    DATABASE_AVAILABLE = True
    print(" Database components imported successfully")
except ImportError as e:
    DATABASE_AVAILABLE = False
    print(f"❌ Failed to import database components: {e}")
    sys.exit(1)

def test_database_connection() -> bool:
    """Test if database connection is working"""
    try:
        print(" Testing database connection...")
        print(f" Database URI: {SQLALCHEMY_DATABASE_URI[:50]}...")
        
        db = SessionLocal()
        # Test basic connection
        result = db.execute(text("SELECT 1 as test")).fetchone()
        
        # Test if item_classification table exists
        result = db.execute(text("""
            SELECT count(*) 
            FROM information_schema.tables 
            WHERE table_name = 'item_classification'
        """)).fetchone()
        
        if result[0] == 0:
            print("❌ item_classification table does not exist!")
            db.close()
            return False
        
        # Test if we can query the table
        count = db.query(ItemClassification).count()
        print(f" Database connection successful!")
        print(f" Found {count} existing classifications in database")
        
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        try:
            db.close()
        except:
            pass
        return False

def load_json_classifications() -> Optional[List[Dict]]:
    """Load classifications from JSON file"""
    json_path = 'mpi_backend/storage/fixtures/item-classifications.json'
    
    try:
        print(f" Loading classifications from: {json_path}")
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f" Loaded {len(data)} classifications from JSON")
        return data
        
    except FileNotFoundError:
        print(f"❌ JSON file not found: {json_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        return None
    except Exception as e:
        print(f"❌ Error loading JSON: {e}")
        return None

def get_existing_db_classifications() -> Dict[str, str]:
    """Get all existing classifications from database"""
    try:
        print(" Fetching existing classifications from database...")
        db = SessionLocal()
        
        existing = {}
        classifications = db.query(ItemClassification).all()
        
        for classification in classifications:
            if classification.item:  # Only add non-null items
                existing[classification.item] = classification.category
        
        print(f" Found {len(existing)} existing classifications in database")
        db.close()
        return existing
        
    except Exception as e:
        print(f"❌ Error fetching database classifications: {e}")
        try:
            db.close()
        except:
            pass
        return {}

def find_missing_classifications(json_data: List[Dict], db_existing: Dict[str, str]) -> List[Dict]:
    """Find classifications that exist in JSON but not in database"""
    missing = []
    
    print(" Comparing JSON vs Database classifications...")
    
    for item in json_data:
        if not item.get('item'):  # Skip items with no name
            continue
            
        item_name = item['item']
        category = item.get('category')
        
        if item_name not in db_existing:
            missing.append({
                'item': item_name,
                'category': category
            })
        elif db_existing[item_name] != category:
            print(f"⚠  Category mismatch for '{item_name}': JSON='{category}' vs DB='{db_existing[item_name]}'")
    
    print(f" Analysis complete:")
    print(f"   - Total in JSON: {len(json_data)}")
    print(f"   - Total in Database: {len(db_existing)}")
    print(f"   - Missing from Database: {len(missing)}")
    
    return missing

def insert_missing_classifications(missing_classifications: List[Dict]) -> bool:
    """Insert missing classifications into database"""
    if not missing_classifications:
        print(" No missing classifications to insert!")
        return True
    
    print(f"\n Inserting {len(missing_classifications)} missing classifications...")
    
    db = SessionLocal()
    inserted_count = 0
    error_count = 0
    
    try:
        for classification in missing_classifications:
            try:
                item_name = classification['item']
                category = classification.get('category')
                
                # Create new classification
                new_classification = ItemClassification(
                    item=item_name,
                    category=category
                )
                
                db.add(new_classification)
                db.flush()  # Flush to catch any errors before commit
                
                print(f"    Added: '{item_name}' → '{category}'")
                inserted_count += 1
                
            except IntegrityError as e:
                db.rollback()
                print(f"   ⚠  Duplicate: '{item_name}' (already exists)")
                error_count += 1
                
            except Exception as e:
                db.rollback()
                print(f"   ❌ Error inserting '{item_name}': {e}")
                error_count += 1
        
        # Commit all changes
        db.commit()
        print(f"\n Database update complete!")
        print(f"   - Successfully inserted: {inserted_count}")
        print(f"   - Errors/Duplicates: {error_count}")
        
        return True
        
    except Exception as e:
        db.rollback()
        print(f"❌ Failed to commit changes: {e}")
        return False
        
    finally:
        db.close()

def create_backup_sql(missing_classifications: List[Dict]) -> None:
    """Create a backup SQL script"""
    if not missing_classifications:
        return
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    sql_filename = f"scripts/sync_classifications_backup_{timestamp}.sql"
    
    try:
        print(f"\n Creating backup SQL script: {sql_filename}")
        
        with open(sql_filename, 'w') as f:
            f.write("-- Backup SQL script for classification sync\n")
            f.write(f"-- Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"-- Total classifications: {len(missing_classifications)}\n\n")
            f.write("-- Insert missing classifications\n")
            
            for classification in missing_classifications:
                item_name = classification['item'].replace("'", "''")  # Escape quotes
                category = classification.get('category', 'NULL')
                if category and category != 'NULL':
                    category = f"'{category}'"
                f.write(f"INSERT INTO item_classification (item, category) VALUES ('{item_name}', {category});\n")
            
            f.write(f"\n-- End of script\n")
        
        print(f" Backup SQL script created: {sql_filename}")
        
    except Exception as e:
        print(f"❌ Error creating backup SQL: {e}")

def main():
    """Main execution function"""
    print("=" * 80)
    print(" CRITICAL: SYNC ITEM CLASSIFICATIONS FROM JSON TO DATABASE")
    print("=" * 80)
    print("This script will:")
    print("1. Test database connection")
    print("2. Load classifications from JSON file")
    print("3. Compare with existing database classifications")
    print("4. Insert missing classifications into database")
    print("5. Create backup SQL script")
    print()
    
    # Step 1: Test database connection
    if not test_database_connection():
        print("❌ Cannot proceed without database connection!")
        return False
    
    # Step 2: Load JSON data
    json_data = load_json_classifications()
    if not json_data:
        print("❌ Cannot proceed without JSON data!")
        return False
    
    # Step 3: Get existing database classifications
    db_existing = get_existing_db_classifications()
    
    # Step 4: Find missing classifications
    missing_classifications = find_missing_classifications(json_data, db_existing)
    
    if not missing_classifications:
        print("\n SUCCESS: All classifications are already in sync!")
        print(" Your database is up to date with the JSON file")
        return True
    
    # Show what will be added
    print(f"\n Missing classifications to be added:")
    for i, classification in enumerate(missing_classifications[:10], 1):  # Show first 10
        category = classification.get('category', 'NULL')
        print(f"   {i:2d}. '{classification['item']}' → '{category}'")
    
    if len(missing_classifications) > 10:
        print(f"   ... and {len(missing_classifications) - 10} more")
    
    # Ask for confirmation
    print(f"\n⚠  This will add {len(missing_classifications)} new classifications to your database.")
    print("⚠  This operation is SAFE - it only ADDS missing items, never modifies existing ones.")
    
    response = input(f"\nProceed with adding {len(missing_classifications)} classifications? (y/N): ")
    
    if response.lower() != 'y':
        print("❌ Operation cancelled by user")
        return False
    
    # Step 5: Create backup SQL
    create_backup_sql(missing_classifications)
    
    # Step 6: Insert missing classifications
    success = insert_missing_classifications(missing_classifications)
    
    if success:
        print(f"\n SUCCESS! Sync completed successfully!")
        print(f" Added {len(missing_classifications)} classifications to database")
        print(f" Your QuickBooks import should now work correctly!")
        
        # Check if the NO-HUB FITTINGS issue was fixed
        if any(c['item'] == '(NO-HUB FITTINGS)' for c in missing_classifications):
            print(f"\n QUICKBOOKS ISSUE FIXED:")
            print(f"   - Added '(NO-HUB FITTINGS)' classification")
            print(f"   - Item ID 330285 should now import successfully!")
        
        return True
    else:
        print(f"\n❌ Sync failed! Check the error messages above.")
        print(f" You can try running the backup SQL script manually.")
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n❌ Operation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1) 