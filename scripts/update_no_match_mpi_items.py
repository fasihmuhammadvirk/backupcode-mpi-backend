#!/usr/bin/env python3
"""
Script to update mpi_item for all items where mpi_item is "No Match"
based on their cost:
- Cost < 100: UIDI Job Material
- Cost >= 100: UIDI Job Equipment
"""

import sys
import os
import logging

# Add the parent directory to the path so we can import mpi_backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpi_backend.database import get_db
from mpi_backend.database.models.InvoiceItems import InvoiceItem

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def update_no_match_mpi_items():
    """
    Update mpi_item for all items where mpi_item is "No Match" based on cost.
    """
    db = next(get_db())
    
    try:
        # Get all items where mpi_item is "No Match" AND export_status is "Sent"
        no_match_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "No Match",
            InvoiceItem.export_status == "Sent"
        ).all()
        
        logger.info(
            f"Found {len(no_match_items)} items with mpi_item = 'No Match' and export_status = 'Sent'"
        )
        
        if not no_match_items:
            logger.info(
                "No items found with mpi_item = 'No Match' and export_status = 'Sent'. Nothing to update."
            )
            return
        
        # Counters for reporting
        material_count = 0
        equipment_count = 0
        skipped_count = 0
        
        # Process each item
        for item in no_match_items:
            try:
                # Get the cost value
                cost = item.cost
                
                if cost is None:
                    logger.warning(f"Item ID {item.id} has no cost value, skipping")
                    skipped_count += 1
                    continue
                
                # Update mpi_item based on cost
                if cost < 100:
                    item.mpi_item = "UIDI Job Material"
                    material_count += 1
                    logger.debug(f"Item ID {item.id}: Cost {cost} < 100 -> UIDI Job Material")
                else:
                    item.mpi_item = "UIDI Job Equipment"
                    equipment_count += 1
                    logger.debug(f"Item ID {item.id}: Cost {cost} >= 100 -> UIDI Job Equipment")
                
            except Exception as e:
                logger.error(f"Error processing item ID {item.id}: {str(e)}")
                skipped_count += 1
                continue
        
        # Commit all changes
        db.commit()
        
        # Log summary
        logger.info("=" * 60)
        logger.info("UPDATE SUMMARY:")
        logger.info(f"Total items processed: {len(no_match_items)}")
        logger.info(f"Updated to 'UIDI Job Material': {material_count}")
        logger.info(f"Updated to 'UIDI Job Equipment': {equipment_count}")
        logger.info(f"Skipped (no cost value): {skipped_count}")
        logger.info("=" * 60)
        
        # Verify the update
        verify_update(db)
        
    except Exception as e:
        logger.error(f"Error in update_no_match_mpi_items: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


def verify_update(db):
    """
    Verify that the update was successful by checking the counts.
    """
    try:
        # Count remaining "No Match" items with "Sent" status
        remaining_no_match = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "No Match",
            InvoiceItem.export_status == "Sent"
        ).count()
        
        # Count new "UIDI Job Material" items
        material_count = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI Job Material"
        ).count()
        
        # Count new "UIDI Job Equipment" items
        equipment_count = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "UIDI Job Equipment"
        ).count()
        
        logger.info("VERIFICATION:")
        logger.info(f"Remaining 'No Match' items: {remaining_no_match}")
        logger.info(f"Total 'UIDI Job Material' items: {material_count}")
        logger.info(f"Total 'UIDI Job Equipment' items: {equipment_count}")
        
    except Exception as e:
        logger.error(f"Error in verification: {str(e)}")


def show_preview():
    """
    Show a preview of what would be updated without making changes.
    """
    db = next(get_db())
    
    try:
        # Get all items where mpi_item is "No Match" AND export_status is "Sent"
        no_match_items = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "No Match",
            InvoiceItem.export_status == "Sent"
        ).limit(10).all()  # Limit to 10 for preview
        
        logger.info(f"PREVIEW - First 10 items with mpi_item = 'No Match' and export_status = 'Sent':")
        logger.info("=" * 80)
        
        material_count = 0
        equipment_count = 0
        skipped_count = 0
        
        for item in no_match_items:
            cost = item.cost
            if cost is None:
                logger.info(f"Item ID {item.id}: Cost = None -> SKIP")
                skipped_count += 1
            elif cost < 100:
                logger.info(f"Item ID {item.id}: Cost {cost} -> UIDI Job Material")
                material_count += 1
            else:
                logger.info(f"Item ID {item.id}: Cost {cost} -> UIDI Job Equipment")
                equipment_count += 1
        
        logger.info("=" * 80)
        logger.info(f"Preview Summary: Material={material_count}, Equipment={equipment_count}, Skipped={skipped_count}")
        
        # Get total count of "No Match" items with "Sent" status
        total_count = db.query(InvoiceItem).filter(
            InvoiceItem.mpi_item == "No Match",
            InvoiceItem.export_status == "Sent"
        ).count()
        
        logger.info(f"Total items with 'No Match' and 'Sent' status: {total_count}")
        
    except Exception as e:
        logger.error(f"Error in preview: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Update mpi_item for 'No Match' items based on cost")
    parser.add_argument("--preview", action="store_true", help="Show preview without making changes")
    parser.add_argument("--execute", action="store_true", help="Execute the update")
    
    args = parser.parse_args()
    
    if args.preview:
        logger.info("Running in PREVIEW mode - no changes will be made")
        show_preview()
    elif args.execute:
        logger.info("Running in EXECUTE mode - changes will be made")
        update_no_match_mpi_items()
    else:
        logger.info("No action specified. Use --preview to see what would be updated or --execute to make changes")
        logger.info("Example: python scripts/update_no_match_mpi_items.py --preview")
        logger.info("Example: python scripts/update_no_match_mpi_items.py --execute") 