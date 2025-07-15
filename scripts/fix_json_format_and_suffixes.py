#!/usr/bin/env python3
"""
Script to fix JSON format issues and update suffixes in fixture files.
Handles both item-mapping.json and temp-item-mapping.json files.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Supplier suffix mapping
SUPPLIER_SUFFIXES = {
    1: "-B",  # ABC Opus Services
    2: "-W",  # AF Supply
    3: "-Y",  # Y & S Plumbing Supply
    4: "-S",  # Gotham Supply
    5: "-B",  # Lion HVAC
    6: "-W",  # Plumbing Exchange
    7: "-Y",  # Supreme Plumbing
    8: "-S",  # Web Co Supply
    9: "-B",  # BMW Old
    10: "-W", # YS Old
    11: "-Y", # Flow Mark
}

def get_suffix_for_supplier(supplier_id: int) -> str:
    """Get the correct suffix for a supplier ID."""
    return SUPPLIER_SUFFIXES.get(supplier_id, "")

def should_skip_item(item_data: Dict[str, Any]) -> bool:
    """Check if item should be skipped (tax/admin items)."""
    if not item_data:
        return True
    
    # Check various fields that might contain tax/admin indicators
    fields_to_check = ['mpi_code', 'supplier_item_ids', 'original_item', 'description']
    
    for field in fields_to_check:
        value = item_data.get(field, '')
        if isinstance(value, str) and value.lower().startswith('tax'):
            return True
    
    return False

def fix_item_mapping_format(data: Any) -> List[Dict[str, Any]]:
    """Fix item-mapping.json format and extract the mappings array."""
    if isinstance(data, dict):
        # If it's a dictionary, look for permanent_mappings key
        if 'permanent_mappings' in data:
            mappings = data['permanent_mappings']
            logger.info(f"Found permanent_mappings array with {len(mappings)} items")
            return mappings
        else:
            # If no permanent_mappings key, treat the whole dict as a single item
            logger.warning("No permanent_mappings key found, treating as single item")
            return [data]
    elif isinstance(data, list):
        # If it's already a list, return as is
        logger.info(f"Data is already a list with {len(data)} items")
        return data
    else:
        logger.error(f"Unexpected data type: {type(data)}")
        return []

def fix_temp_item_mapping_format(data: Any) -> List[Dict[str, Any]]:
    """Fix temp-item-mapping.json format and filter out null items."""
    if isinstance(data, list):
        # Filter out items that are mostly null or empty
        valid_items = []
        for item in data:
            if item and any(value is not None and value != "" for value in item.values()):
                valid_items.append(item)
        
        logger.info(f"Filtered {len(valid_items)} valid items from {len(data)} total items")
        return valid_items
    else:
        logger.error(f"temp-item-mapping.json should be a list, got {type(data)}")
        return []

def update_suffixes_in_item_mapping(items: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    """Update suffixes in item-mapping.json items."""
    updated_count = 0
    updated_items = []
    
    for item in items:
        if should_skip_item(item):
            updated_items.append(item)
            continue
        
        supplier_id = item.get('supplier_id')
        if not supplier_id:
            updated_items.append(item)
            continue
        
        suffix = get_suffix_for_supplier(supplier_id)
        if not suffix:
            updated_items.append(item)
            continue
        
        # Check if supplier_item_ids already has the correct suffix
        supplier_item_ids = item.get('supplier_item_ids', '')
        if isinstance(supplier_item_ids, str) and not supplier_item_ids.endswith(suffix):
            # Add suffix if missing
            item['supplier_item_ids'] = supplier_item_ids + suffix
            updated_count += 1
            logger.debug(f"Updated {supplier_item_ids} -> {item['supplier_item_ids']}")
        
        updated_items.append(item)
    
    return updated_items, updated_count

def update_suffixes_in_temp_item_mapping(items: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    """Update suffixes in temp-item-mapping.json items."""
    updated_count = 0
    updated_items = []
    
    for item in items:
        if should_skip_item(item):
            updated_items.append(item)
            continue
        
        # For temp items, we need to infer supplier from sheet_name or other fields
        sheet_name = item.get('sheet_name', '')
        original_item = item.get('original_item', '')
        
        # Try to determine supplier from sheet name
        supplier_id = None
        if 'abc' in sheet_name.lower() or 'opus' in sheet_name.lower():
            supplier_id = 1
        elif 'af' in sheet_name.lower() or 'supply' in sheet_name.lower():
            supplier_id = 2
        elif 'y&s' in sheet_name.lower() or 'ys' in sheet_name.lower():
            supplier_id = 3
        elif 'gotham' in sheet_name.lower():
            supplier_id = 4
        elif 'lion' in sheet_name.lower() or 'hvac' in sheet_name.lower():
            supplier_id = 5
        elif 'plumbing' in sheet_name.lower() and 'exchange' in sheet_name.lower():
            supplier_id = 6
        elif 'supreme' in sheet_name.lower():
            supplier_id = 7
        elif 'web' in sheet_name.lower():
            supplier_id = 8
        elif 'bmw' in sheet_name.lower():
            supplier_id = 9
        elif 'flow' in sheet_name.lower() or 'mark' in sheet_name.lower():
            supplier_id = 11
        
        if not supplier_id:
            updated_items.append(item)
            continue
        
        suffix = get_suffix_for_supplier(supplier_id)
        if not suffix:
            updated_items.append(item)
            continue
        
        # Check if original_item already has the correct suffix
        if isinstance(original_item, str) and not original_item.endswith(suffix):
            # Add suffix if missing
            item['original_item'] = original_item + suffix
            updated_count += 1
            logger.debug(f"Updated {original_item} -> {item['original_item']}")
        
        updated_items.append(item)
    
    return updated_items, updated_count

def process_json_file(file_path: str, is_item_mapping: bool = True) -> tuple[bool, int]:
    """Process a JSON file to fix format and update suffixes."""
    try:
        logger.info(f"Processing {file_path}...")
        
        # Read the file
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Fix format based on file type
        if is_item_mapping:
            items = fix_item_mapping_format(data)
            updated_items, updated_count = update_suffixes_in_item_mapping(items)
            # Save back in the original format (with permanent_mappings key)
            output_data = {"permanent_mappings": updated_items}
        else:
            items = fix_temp_item_mapping_format(data)
            updated_items, updated_count = update_suffixes_in_temp_item_mapping(items)
            output_data = updated_items
        
        # Create backup
        backup_path = f"{file_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Created backup: {backup_path}")
        
        # Write updated data
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Successfully updated {updated_count} items in {file_path}")
        return True, updated_count
        
    except Exception as e:
        logger.error(f"Error processing {file_path}: {str(e)}")
        return False, 0

def main():
    """Main function to process both JSON files."""
    logger.info("Starting JSON format fix and suffix updates...")
    
    # File paths
    item_mapping_path = "mpi_backend/storage/fixtures/item-mapping.json"
    temp_item_mapping_path = "mpi_backend/storage/fixtures/temp-item-mapping.json"
    
    total_updated = 0
    
    # Process item-mapping.json
    if os.path.exists(item_mapping_path):
        success, count = process_json_file(item_mapping_path, is_item_mapping=True)
        if success:
            total_updated += count
        else:
            logger.error(f"Failed to process {item_mapping_path}")
    else:
        logger.warning(f"File not found: {item_mapping_path}")
    
    # Process temp-item-mapping.json
    if os.path.exists(temp_item_mapping_path):
        success, count = process_json_file(temp_item_mapping_path, is_item_mapping=False)
        if success:
            total_updated += count
        else:
            logger.error(f"Failed to process {temp_item_mapping_path}")
    else:
        logger.warning(f"File not found: {temp_item_mapping_path}")
    
    logger.info(f"JSON format fix and suffix updates completed! Total items updated: {total_updated}")

if __name__ == "__main__":
    main() 