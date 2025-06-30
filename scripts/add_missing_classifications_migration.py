#!/usr/bin/env python3
"""
Production Migration: Add Missing Item Classifications
Safe to run on production - only adds missing items
"""

import json
import sys
import os

# Add project to path - go up one directory from scripts/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.ItemClassification import ItemClassification
from sqlalchemy.exc import IntegrityError

def get_missing_classifications():
    """Get classifications from JSON that aren't in database"""
    
    # Load JSON data
    json_path = 'mpi_backend/storage/fixtures/item-classifications.json'
    with open(json_path, 'r') as f:
        json_data = json.load(f)
    
    # Get existing database items
    db = SessionLocal()
    existing_items = set()
    for item in db.query(ItemClassification.item).all():
        if item.item:
            existing_items.add(item.item)
    
    # Find missing items
    missing = []
    for item in json_data:
        if item.get('item') and item['item'] not in existing_items:
            missing.append(item)
    
    db.close()
    return missing

def migrate_classifications():
    """Add missing classifications to database"""
    
    print(" Finding missing classifications...")
    missing = get_missing_classifications()
    
    if not missing:
        print(" No missing classifications found!")
        return True
    
    print(f" Found {len(missing)} missing classifications")
    
    db = SessionLocal()
    added_count = 0
    
    try:
        for item_data in missing:
            try:
                new_item = ItemClassification(
                    item=item_data['item'],
                    category=item_data.get('category')
                )
                db.add(new_item)
                db.flush()
                print(f" Added: {item_data['item']}")
                added_count += 1
                
            except IntegrityError:
                db.rollback()
                print(f"⚠  Skipped duplicate: {item_data['item']}")
            except Exception as e:
                db.rollback()
                print(f"ERROR: Error adding {item_data['item']}: {e}")
        
        # Fix Z, ADDITIONAL FEES if it has null category
        z_item = db.query(ItemClassification).filter(
            ItemClassification.item == '(Z, ADDITIONAL FEES)'
        ).first()
        
        if z_item and z_item.category is None:
            z_item.category = 'M'
            print(" Fixed (Z, ADDITIONAL FEES) category")
        
        db.commit()
        print(f"\n Migration complete! Added {added_count} classifications")
        return True
        
    except Exception as e:
        db.rollback()
        print(f"ERROR: Migration failed: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print(" Starting production migration...")
    success = migrate_classifications()
    sys.exit(0 if success else 1) 