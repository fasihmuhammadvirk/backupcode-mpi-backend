#!/usr/bin/env python3
"""
Script to clean up temporary mappings from the main supplier_item_mappings table.

UIDI and "No Match" entries are temporary placeholders and should not be stored
as permanent mappings in the main mapping table. This script removes them.

Usage:
    python scripts/cleanup_temporary_mappings.py [--dry-run]
    
Arguments:
    --dry-run: Show what would be deleted without actually deleting
"""

import sys
import os
import argparse
import logging
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import get_db
from mpi_backend.database.models import ItemsMapping
from sqlalchemy.orm import Session
from sqlalchemy import or_

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def cleanup_temporary_mappings(dry_run: bool = False, migrate_to_temp: bool = False) -> dict:
    """
    Remove UIDI and No Match mappings from supplier_item_mappings table.
    
    Args:
        dry_run (bool): If True, show what would be deleted without deleting
        migrate_to_temp (bool): If True, migrate valid temporary mappings to temporary_item_mappings
        
    Returns:
        dict: Summary of cleanup operation
    """
    from mpi_backend.database.models import TempItemMapping
    
    db: Session = next(get_db())
    
    try:
        # Find all temporary mappings
        temporary_mappings = db.query(ItemsMapping).filter(
            or_(
                # UIDI mappings
                ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.description.like("UIDI%"),
                
                # No Match mappings
                ItemsMapping.mpi_code == "No Match",
                ItemsMapping.mpi_code == "No Match / UIDI",
                ItemsMapping.description == "No Match",
                ItemsMapping.description == "No Match / UIDI",
                
                # Empty/null mappings
                ItemsMapping.mpi_code.is_(None),
                ItemsMapping.mpi_code == "",
                ItemsMapping.description.is_(None),
                ItemsMapping.description == "",
                
                # Suspicious short codes that may be placeholders
                ItemsMapping.mpi_code.in_(["TBD", "TMP", "TEMP", "TODO", "FIX", "UNKNOWN"])
            )
        ).all()
        
        if not temporary_mappings:
            logger.info(" No temporary mappings found in supplier_item_mappings table")
            return {
                "status": "success",
                "message": "No temporary mappings found",
                "deleted_count": 0,
                "dry_run": dry_run
            }
        
        # Log what will be deleted
        logger.info(f"Found {len(temporary_mappings)} temporary mappings to clean up:")
        
        categories = {
            "UIDI": [],
            "No Match": [],
            "Empty/Null": []
        }
        
        for mapping in temporary_mappings:
            mpi_code = mapping.mpi_code or ""
            description = mapping.description or ""
            
            if "UIDI" in mpi_code or "UIDI" in description:
                categories["UIDI"].append(mapping)
            elif "No Match" in mpi_code or "No Match" in description:
                categories["No Match"].append(mapping)
            else:
                categories["Empty/Null"].append(mapping)
        
        # Display summary by category
        for category, mappings in categories.items():
            if mappings:
                logger.info(f"\n {category} mappings ({len(mappings)}):")
                for mapping in mappings[:5]:  # Show first 5 examples
                    supplier_item = mapping.supplier_item_ids or "N/A"
                    mpi_code = mapping.mpi_code or "NULL"
                    description = mapping.description or "NULL"
                    logger.info(f"  - Supplier Item: {supplier_item} | MPI: {mpi_code} | Desc: {description}")
                
                if len(mappings) > 5:
                    logger.info(f"  ... and {len(mappings) - 5} more")
        
        if dry_run:
            logger.info(f"\n DRY RUN: Would delete {len(temporary_mappings)} temporary mappings")
            logger.info("Run without --dry-run to actually delete these mappings")
            return {
                "status": "success",
                "message": f"DRY RUN: Found {len(temporary_mappings)} temporary mappings to delete",
                "deleted_count": 0,
                "dry_run": True,
                "categories": {k: len(v) for k, v in categories.items()}
            }
        
        # Handle migration or deletion
        if migrate_to_temp:
            logger.info(f"\n Migrating {len(temporary_mappings)} temporary mappings to temporary_item_mappings table...")
            migrated_count = 0
            deleted_count = 0
            
            for mapping in temporary_mappings:
                # Try to migrate UIDI mappings to temporary table
                if mapping.mpi_code and mapping.mpi_code.startswith("UIDI") and mapping.supplier_item_ids:
                    try:
                        # Check if already exists in temp table
                        existing_temp = db.query(TempItemMapping).filter_by(
                            original_item=mapping.supplier_item_ids
                        ).first()
                        
                        if not existing_temp:
                            new_temp_mapping = TempItemMapping(
                                original_item=mapping.supplier_item_ids,
                                original_description=mapping.description or "",
                                sheet_name=mapping.google_sheet_name or ""
                            )
                            db.add(new_temp_mapping)
                            migrated_count += 1
                            logger.info(f"Migrated: {mapping.supplier_item_ids} -> sheet: {mapping.google_sheet_name or 'Unknown'}")
                    except Exception as e:
                        logger.warning(f"Failed to migrate {mapping.supplier_item_ids}: {e}")
                
                # Delete from permanent table
                db.delete(mapping)
                deleted_count += 1
            
            db.commit()
            logger.info(f" Migration complete: {migrated_count} migrated, {deleted_count} removed from permanent table")
        else:
            # Just delete the mappings
            logger.info(f"\n  Deleting {len(temporary_mappings)} temporary mappings...")
            
            deleted_count = 0
            for mapping in temporary_mappings:
                db.delete(mapping)
                deleted_count += 1
            
            db.commit()
            logger.info(f" Successfully deleted {deleted_count} temporary mappings from supplier_item_mappings table")
        
        return {
            "status": "success",
            "message": f"Successfully deleted {deleted_count} temporary mappings",
            "deleted_count": deleted_count,
            "dry_run": False,
            "categories": {k: len(v) for k, v in categories.items()}
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"ERROR: Error during cleanup: {str(e)}")
        return {
            "status": "error",
            "message": f"Error during cleanup: {str(e)}",
            "deleted_count": 0,
            "dry_run": dry_run
        }
    finally:
        db.close()


def verify_cleanup(dry_run: bool = False) -> dict:
    """
    Verify that no temporary mappings remain in the table.
    """
    db: Session = next(get_db())
    
    try:
        remaining_temporary = db.query(ItemsMapping).filter(
            or_(
                ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.description.like("UIDI%"),
                ItemsMapping.mpi_code == "No Match",
                ItemsMapping.mpi_code == "No Match / UIDI",
                ItemsMapping.description == "No Match",
                ItemsMapping.description == "No Match / UIDI"
            )
        ).count()
        
        if remaining_temporary == 0:
            logger.info(" Verification successful: No temporary mappings remain in supplier_item_mappings table")
            return {"status": "success", "remaining_count": 0}
        else:
            logger.warning(f"⚠  Verification found {remaining_temporary} temporary mappings still in table")
            return {"status": "warning", "remaining_count": remaining_temporary}
            
    except Exception as e:
        logger.error(f"ERROR: Error during verification: {str(e)}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Clean up temporary UIDI and No Match mappings from supplier_item_mappings table"
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Show what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--verify-only", 
        action="store_true", 
        help="Only verify if temporary mappings exist, don't delete"
    )
    parser.add_argument(
        "--migrate", 
        action="store_true", 
        help="Migrate UIDI mappings to temporary_item_mappings before deleting from permanent table"
    )
    
    args = parser.parse_args()
    
    logger.info(" Starting temporary mappings cleanup...")
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if args.verify_only:
        logger.info(" Running verification only...")
        result = verify_cleanup()
    else:
        # Run cleanup
        result = cleanup_temporary_mappings(dry_run=args.dry_run, migrate_to_temp=args.migrate)
        
        # Run verification if cleanup was successful and not dry run
        if result["status"] == "success" and not args.dry_run and result["deleted_count"] > 0:
            logger.info("\n Running verification...")
            verify_result = verify_cleanup()
    
    logger.info(f"\n Final Status: {result['status']}")
    if "message" in result:
        logger.info(f" Message: {result['message']}")
    
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    exit(main()) 