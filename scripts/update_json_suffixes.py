#!/usr/bin/env python3
"""
Update JSON Fixture Files with Proper Suffixes

This script updates the item-mapping.json and temp-item-mapping.json files
to include proper suffixes based on supplier information.

Usage:
    python scripts/update_json_suffixes.py
"""

import json
import os
import sys
import logging
from typing import Dict, List, Optional

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Supplier ID to suffix mapping (from item_utils.py)
SUPPLIER_SUFFIX_MAP = {
    1: 'B',   # BMW Plumbing Supplies
    2: 'W',   # World Wide Plumbing  
    3: 'Y',   # Y & S Plumbing Supply
    4: 'S',   # Supreme Plumbing Supply
    5: 'P',   # Pyramid Plumbing
    6: 'A',   # ABC Opus Services
    7: 'P',   # Park Plumbing Supply (same as Pyramid)
    8: 'G',   # Gotham Plumbing Supply
    9: 'F',   # FW Webb Plumbing Supply
    10: 'F',  # Flow Mark Plumbing Supply (same as FW Webb)
    11: None, # Plumbing Exchange (no specific suffix)
    12: 'A',  # AF Supply (same as ABC Opus)
    13: None, # Lion Hvac Supplies (no specific suffix)
    14: 'F',  # Bruce Ferguson
}

# Supplier name to suffix mapping for display purposes
SUPPLIER_NAME_SUFFIX_MAP = {
    "BMW Plumbing Supplies": "B",
    "World Wide Plumbing": "W",
    "Y & S Plumbing Supply": "Y",
    "Supreme Plumbing Supply": "S",
    "Pyramid Plumbing": "P",
    "ABC Opus Services": "A",
    "Park Plumbing Supply": "P",
    "Gotham Plumbing Supply": "G",
    "FW Webb Plumbing Supply": "F",
    "Flow Mark Plumbing Supply": "F",
    "Plumbing Exchange": None,  # No suffix
    "AF Supply": "A",
    "Lion Hvac Supplies": None,  # No suffix
    "Bruce Ferguson": "F",
}


def get_supplier_suffix(supplier_id: int) -> Optional[str]:
    """Get suffix for a supplier ID."""
    return SUPPLIER_SUFFIX_MAP.get(supplier_id)


def get_supplier_suffix_by_name(supplier_name: str) -> Optional[str]:
    """Get suffix for a supplier name."""
    return SUPPLIER_NAME_SUFFIX_MAP.get(supplier_name)


def should_skip_item(item_code: str) -> bool:
    """Check if item should be skipped from suffix processing."""
    if not item_code:
        return True
    
    item_str = str(item_code).strip()
    
    # Exclude tax and administrative items from getting suffixes
    excluded_items = [
        "tax", "freight", "shipping", "handling", "subtotal", "total"
    ]
    
    if (item_str.startswith("10 Materials") or 
            item_str.lower() in excluded_items):
        return True
    
    return False


def clean_existing_suffixes(item_code: str) -> str:
    """Remove all existing suffixes from item code."""
    if not item_code:
        return item_code
    
    clean_item = str(item_code).strip()
    
    # Remove ALL existing suffixes first (including double suffixes)
    all_suffixes = set(SUPPLIER_SUFFIX_MAP.values())
    all_suffixes.discard(None)  # Remove None values
    
    # Keep removing suffixes until none are found
    while True:
        found_suffix = False
        for existing_suffix in all_suffixes:
            if existing_suffix and clean_item.endswith(f"-{existing_suffix}"):
                clean_item = clean_item[:-len(f"-{existing_suffix}")]
                found_suffix = True
                break
        if not found_suffix:
            break
    
    return clean_item


def add_suffix_to_item(item_code: str, supplier_id: int) -> str:
    """
    Add the correct suffix to an item code based on supplier ID.
    """
    if should_skip_item(item_code):
        return item_code
    
    suffix = get_supplier_suffix(supplier_id)
    if not suffix:
        return item_code
    
    # Clean existing suffixes first
    clean_item = clean_existing_suffixes(item_code)
    
    # Add the correct suffix
    return f"{clean_item}-{suffix}"


def update_item_mapping_json():
    """Update item-mapping.json with proper suffixes."""
    json_file = "mpi_backend/storage/fixtures/item-mapping.json"
    
    if not os.path.exists(json_file):
        logger.warning(f"File {json_file} does not exist. Skipping.")
        return
    
    logger.info(f"Updating {json_file}...")
    
    try:
        # Read the JSON file
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            logger.error(f"Expected list in {json_file}, got {type(data)}")
            return
        
        updated_count = 0
        total_count = len(data)
        
        for item in data:
            try:
                if not isinstance(item, dict):
                    continue
                
                # Get supplier information
                supplier_id = item.get('supplier_id')
                supplier_name = item.get('supplier_name')
                supplier_item_ids = item.get('supplier_item_ids')
                
                if not supplier_item_ids:
                    continue
                
                # Determine supplier ID if not present
                if not supplier_id and supplier_name:
                    for sid, suffix in SUPPLIER_SUFFIX_MAP.items():
                        if SUPPLIER_NAME_SUFFIX_MAP.get(supplier_name) == suffix:
                            supplier_id = sid
                            break
                
                if not supplier_id:
                    logger.debug(f"No supplier ID found for item: {supplier_item_ids}")
                    continue
                
                # Add suffix to supplier_item_ids
                original_item = supplier_item_ids
                new_item = add_suffix_to_item(supplier_item_ids, supplier_id)
                
                if new_item != original_item:
                    item['supplier_item_ids'] = new_item
                    updated_count += 1
                    logger.debug(f"Updated item: {original_item} -> {new_item}")
                
            except Exception as e:
                logger.error(f"Error processing item: {e}")
        
        # Write back to file
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Successfully updated {updated_count} out of {total_count} items in {json_file}")
        
    except Exception as e:
        logger.error(f"Error updating {json_file}: {e}")


def update_temp_item_mapping_json():
    """Update temp-item-mapping.json with proper suffixes."""
    json_file = "mpi_backend/storage/fixtures/temp-item-mapping.json"
    
    if not os.path.exists(json_file):
        logger.warning(f"File {json_file} does not exist. Skipping.")
        return
    
    logger.info(f"Updating {json_file}...")
    
    try:
        # Read the JSON file
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            logger.error(f"Expected list in {json_file}, got {type(data)}")
            return
        
        if not data:
            logger.info(f"{json_file} is empty. No updates needed.")
            return
        
        updated_count = 0
        total_count = len(data)
        
        for item in data:
            try:
                if not isinstance(item, dict):
                    continue
                
                # Get supplier information
                supplier_id = item.get('supplier_id')
                supplier_name = item.get('supplier_name')
                supplier_item_ids = item.get('supplier_item_ids')
                
                if not supplier_item_ids:
                    continue
                
                # Determine supplier ID if not present
                if not supplier_id and supplier_name:
                    for sid, suffix in SUPPLIER_SUFFIX_MAP.items():
                        if SUPPLIER_NAME_SUFFIX_MAP.get(supplier_name) == suffix:
                            supplier_id = sid
                            break
                
                if not supplier_id:
                    logger.debug(f"No supplier ID found for item: {supplier_item_ids}")
                    continue
                
                # Add suffix to supplier_item_ids
                original_item = supplier_item_ids
                new_item = add_suffix_to_item(supplier_item_ids, supplier_id)
                
                if new_item != original_item:
                    item['supplier_item_ids'] = new_item
                    updated_count += 1
                    logger.debug(f"Updated item: {original_item} -> {new_item}")
                
            except Exception as e:
                logger.error(f"Error processing item: {e}")
        
        # Write back to file
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Successfully updated {updated_count} out of {total_count} items in {json_file}")
        
    except Exception as e:
        logger.error(f"Error updating {json_file}: {e}")


def main():
    """Main function to update JSON files."""
    logger.info("Starting JSON suffix updates...")
    
    try:
        # Update both JSON files
        update_item_mapping_json()
        update_temp_item_mapping_json()
        
        logger.info("JSON suffix updates completed successfully!")
        
    except Exception as e:
        logger.error(f"JSON suffix updates failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 