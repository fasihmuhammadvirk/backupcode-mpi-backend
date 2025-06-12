#!/usr/bin/env python
"""
Simple script to update all UIDI and No Match items with valid mappings.
Follows the same logic as the application's update_no_match_uidi_mappings function.

Usage:
    python scripts/update_uidi_items.py
"""

import os
import sys
import logging
from sqlalchemy import or_

# Add parent directory to path so we can import the app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import app modules
from mpi_backend.database import db_context
from mpi_backend.database.models import InvoiceItem, ItemsMapping
from mpi_backend.utils.mapping_validators import is_temporary_mapping
from mpi_backend.utils.item_utils import clean_supplier_suffix

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def extract_supplier_id(vendor_name):
    """Helper method to extract supplier ID from vendor name"""
    company_codes = {
        "BMW Plumbing Supplies": 1,
        "World Wide Plumbing": 2,
        "Y & S Plumbing Supply": 3,
        "Supreme Plumbing Supply": 4,
        "Pyramid Plumbing": 5,
        "ABC Opus Services": 6,
        "Park Plumbing Supply": 7,
        "Gotham Plumbing Supply": 8,
        "FW Webb Plumbing Supply": 9,
        "Flow Mark Plumbing Supply": 10,
        "Plumbing Exchange": 11,
        "AF Supply": 12,
        "Lion Hvac Supplies": 13
    }
    for company, code in company_codes.items():
        if company in vendor_name:
            return code, company
    return 1, "BMW Plumbing Supplies"  # Default

def update_uidi_items():
    """Update UIDI and No Match items with valid mappings"""
    try:
        with db_context() as db:
            # Get items with No Match / UIDI mappings
            no_match_items = db.query(InvoiceItem).filter(
                or_(
                    InvoiceItem.mpi_item.is_(None),
                    InvoiceItem.mpi_item == "",
                    InvoiceItem.mpi_item == "No Match",
                    InvoiceItem.mpi_item.like("UIDI%")
                )
            ).all()
            
            if not no_match_items:
                logger.info("No items with No Match / UIDI found")
                return
                
            logger.info(f"Found {len(no_match_items)} items with No Match / UIDI")
            
            # Get only valid permanent mappings
            valid_mappings = db.query(ItemsMapping).filter(
                ~ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.mpi_code != "No Match",
                ItemsMapping.mpi_code != "No Match / UIDI",
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != ""
            ).all()
            
            if not valid_mappings:
                logger.info("No valid permanent mappings available")
                return
                
            logger.info(f"Found {len(valid_mappings)} valid permanent mappings")
            
            # Update No Match / UIDI items if valid mappings are found
            updated_count = 0
            
            for item in no_match_items:
                # Find matching mapping using supplier-specific suffix cleaning
                matched = False
                
                for mapping in valid_mappings:
                    # Validate this is truly a permanent mapping
                    if is_temporary_mapping(mapping.mpi_code, mapping.description):
                        continue
                    
                    supplier_item_ids = mapping.supplier_item_ids
                    if not supplier_item_ids:
                        continue
                    
                    # Extract supplier_id from the invoice item's supplier/vendor
                    supplier_id, _ = extract_supplier_id(item.vendor)
                    
                    # Clean both items for comparison (strip whitespace and apply suffix cleaning)
                    clean_invoice_item = str(item.item).strip()
                    clean_mapping_item = supplier_item_ids.strip()
                    
                    # First try exact match
                    if clean_invoice_item == clean_mapping_item:
                        old_status = item.mpi_item or "Empty"
                        item.mpi_item = mapping.mpi_code
                        item.mpi_description = mapping.description
                        item.sheet_name = mapping.google_sheet_name or ""
                        updated_count += 1
                        matched = True
                        logger.info(f"Updated: {clean_invoice_item} | {old_status} -> {mapping.mpi_code}")
                        break
                    
                    # If no exact match, try with suffix cleaning
                    if supplier_id:
                        cleaned_mapping_item = clean_supplier_suffix(clean_mapping_item, supplier_id)
                        if clean_invoice_item == cleaned_mapping_item:
                            old_status = item.mpi_item or "Empty"
                            item.mpi_item = mapping.mpi_code
                            item.mpi_description = mapping.description
                            item.sheet_name = mapping.google_sheet_name or ""
                            updated_count += 1
                            matched = True
                            logger.info(f"Updated (with suffix cleaning): {clean_invoice_item} == {cleaned_mapping_item} | {old_status} -> {mapping.mpi_code}")
                            break
                
                # If no match found, preserve the UIDI status (don't change to No Match)
                
            db.commit()
            logger.info(f"Successfully updated {updated_count} items with No Match / UIDI mappings")
            
    except Exception as e:
        logger.error(f"Failed to update No Match / UIDI mappings: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting update of UIDI and No Match items")
    update_uidi_items()
    logger.info("Update completed") 