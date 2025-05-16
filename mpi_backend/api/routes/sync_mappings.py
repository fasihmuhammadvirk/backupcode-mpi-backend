from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime
from apscheduler.triggers.interval import IntervalTrigger

from mpi_backend.database import get_db, SessionLocal
from mpi_backend.database.controllers import ItemsMappingController
from mpi_backend.database.models import InvoiceItem, ItemsMapping 
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.google_sheets import GoogleSheetDataExtractor
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID,
    DEFAULT_OUTPUT_FILE,
    GOOGLE_API_KEY,
    SKIP_SHEETS,
    MAPPING_CONFIG
)
from mpi_backend.database.schemas import SyncMappingsResponse
from sqlalchemy import or_

import json
import os
import logging

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync")

# Global variable to track sync status
sync_task_running = False
last_sync_time = None


def perform_sync_mapping_task(db: Session = None):
    """
    Performs the actual sync operation.
    
    Args:
        db: Database session
    
    Returns:
        Dict with sync operation details
    """
    global sync_task_running, last_sync_time
    
    # If task is already running, skip this run
    if sync_task_running:
        logger.info("Sync task already running, skipping this run")
        return {
            "success": False,
            "message": "Task already running",
            "skipped": True
        }
    
    # If db is not provided, create a new session
    if db is None:
        # Create a new database session properly instead of using get_db() as a context manager
        db_session = SessionLocal()
        try:
            return _perform_sync_internal(db_session)
        finally:
            db_session.close()
    else:
        return _perform_sync_internal(db)


def _perform_sync_internal(db: Session):
    """Internal function to perform the sync with a session"""
    global sync_task_running, last_sync_time
    
    try:
        sync_task_running = True
        logger.info("Starting sync task...")
        
        # Step 1: Extract data from Google Sheets
        temp_output_file = f"{DEFAULT_OUTPUT_FILE}.temp"
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(temp_output_file), exist_ok=True)
        
        extractor = GoogleSheetDataExtractor(
            sheet_id=DEFAULT_SHEET_ID,
            api_key=GOOGLE_API_KEY,
            output_file=temp_output_file,
            skip_sheets=SKIP_SHEETS,
            batch_size=MAPPING_CONFIG["batch_size"],
            fuzzy_threshold=MAPPING_CONFIG["fuzzy_threshold"]
        )
        
        # Extract data from Google Sheets to temp file
        google_sheet_json = extractor.process_all_sheets()
        
        # Step 2: Compare with existing mappings
        # Load existing mappings JSON
        existing_json = []
        if os.path.exists(DEFAULT_OUTPUT_FILE):
            with open(DEFAULT_OUTPUT_FILE, 'r') as f:
                try:
                    existing_json = json.load(f)
                except json.JSONDecodeError:
                    logger.warning(
                        "Could not read existing JSON file "
                        f"{DEFAULT_OUTPUT_FILE}"
                    )
        
        # Create sets of unique keys for comparison
        existing_keys = set()
        for item in existing_json:
            mpi = item.get('mpi_code', '')
            supplier_id = item.get('supplier_id', '')
            item_ids = item.get('supplier_item_ids', '')
            key = f"{mpi}-{supplier_id}-{item_ids}"
            existing_keys.add(key)
        
        # Filter to only new mappings
        new_json_entries = []
        new_mappings = []
        
        for item in google_sheet_json:
            mpi = item.get('mpi_code', '')
            supplier_id = item.get('supplier_id', '')
            item_ids = item.get('supplier_item_ids', '')
            key = f"{mpi}-{supplier_id}-{item_ids}"
            if key not in existing_keys:
                new_json_entries.append(item)
                new_mappings.append(item)
        
        # Step 3: Update the database and save the updated JSON
        mapping_controller = ItemsMappingController(db)
        
        # Update database with new mappings
        for mapping in new_mappings:
            mapping_data = {
                "mpi_code": mapping["mpi_code"],
                "description": mapping["description"],
                "google_sheet_name": mapping["google_sheet_name"],
                "supplier_item_ids": mapping["supplier_item_ids"]
            }
            mapping_controller.update_mapping(
                supplier_id=mapping["supplier_id"],
                mapping_data=mapping_data
            )
        
        # Save updated JSON
        combined_json = existing_json + new_json_entries
        with open(DEFAULT_OUTPUT_FILE, 'w') as f:
            json.dump(combined_json, f, indent=2)
        
        # Clean up temp file
        if os.path.exists(temp_output_file):
            os.remove(temp_output_file)
        
        # Update last sync time
        last_sync_time = datetime.now()
        
        logger.info(f"Sync completed successfully at {last_sync_time}")
        return {
            "success": True,
            "new_mappings_count": len(new_mappings),
            "existing_mappings_count": len(existing_json),
            "timestamp": last_sync_time
        }
        
    except Exception as e:
        logger.error(f"Failed to sync mappings: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to sync mappings: {str(e)}",
            "timestamp": datetime.now()
        }
        
    finally:
        sync_task_running = False

@router.post("/mapping", response_model=SyncMappingsResponse)
def sync_mapping(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Manually trigger synchronization of mappings from Google Sheets.
    
    If a sync task is already running, returns a message indicating that.
    Otherwise, starts the sync process in the background.
    
    Returns:
        SyncMappingsResponse: Success status, message, and timestamp
    """
    if sync_task_running:
        return SyncMappingsResponse(
            success=False,
            message="Sync task is already running",
            timestamp=datetime.now()
        )
    
    # Start sync in the background
    background_tasks.add_task(perform_sync_mapping_task, db)
    
    return SyncMappingsResponse(
        success=True,
        message="Sync task started manually",
        timestamp=datetime.now()
    )


@router.get("/status", response_model=dict)
def sync_status(token: str = Depends(JWTBearer())):
    """
    Check the status of the sync task.
    
    Returns:
        Dict with the current status of the sync task
    """
    return {
        "is_running": sync_task_running,
        "last_sync_time": (last_sync_time.isoformat() 
                           if last_sync_time else None)
    }


@router.post("/update-invalid-mappings")
def update_invalid_mappings(
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Update all items with invalid mappings by finding matches in the 
    ItemsMapping table.
    
    Targets items where:
    - mpi_item is exactly "no match" (case insensitive)
    - mpi_item starts with "UIDI"
    
    For each item, tries to find a match in the ItemsMapping table based on the
    org_item (item) and org_description (description) fields.
    
    Returns:
        Dict with status and count of updated items
    """
    try:
        # Get items with invalid mappings
        invalid_items = db.query(InvoiceItem).filter(
            or_(
                InvoiceItem.mpi_item.ilike("no match"),
                InvoiceItem.mpi_item.startswith("UIDI")
            )
        ).all()
        
        if not invalid_items:
            return {
                "status": "success",
                "message": "No invalid mappings found"
            }
        
        # Fetch all existing mappings
        mappings = db.query(ItemsMapping).all()
        
        # Create a lookup dictionary for efficient searching
        # Using supplier_item_ids and supplier_id as a compound key
        mapping_lookup = {}
        for mapping in mappings:
            key = (f"{mapping.supplier_item_ids.lower()}-"
                   f"{mapping.supplier_id}")
            mapping_lookup[key] = mapping
        
        # Update invalid items if mappings are found
        updated_count = 0
        
        for item in invalid_items:
            # Try to find match by item number and supplier
            from mpi_backend.utils.export_utils import extract_supplier_id
            supplier_id, _ = extract_supplier_id(item.vendor)
            
            # Look for a match in the mappings
            key = (f"{item.item.lower()}-{supplier_id}" 
                   if item.item else "")
            mapping = mapping_lookup.get(key)
            
            if mapping:
                # Update the item with the mapping information
                item.mpi_item = mapping.mpi_code
                item.mpi_description = mapping.description
                item.sheet_name = mapping.google_sheet_name
                updated_count += 1
        
        # Commit the changes
        db.commit()
        
        return {
            "status": "success",
            "message": f"{updated_count} items updated"
        }
    
    except Exception as e:
        logger.error(f"Failed to update invalid mappings: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to update invalid mappings: {str(e)}"
        }


def perform_update_all_mappings(db: Session = None):
    """
    Internal implementation of update_all_mappings that can be called
    directly from the scheduler without authentication.
    
    Args:
        db: Database session. If None, a new session is created.
        
    Returns:
        Dict with status and count of updated items
    """
    # Create a new session if one wasn't provided
    if db is None:
        db = SessionLocal()
        close_db = True
    else:
        close_db = False
        
    try:
        # Fetch all mappings
        mappings = db.query(ItemsMapping).all()
        
        if not mappings:
            logger.info("No mappings found to apply")
            return {
                "status": "success",
                "message": "No mappings found to apply"
            }
        
        # Process each mapping to update related invoice items
        total_updated_count = 0
        total_mappings_processed = 0
        
        for mapping in mappings:
            total_mappings_processed += 1
            try:
                # Get vendor name from supplier_id
                from mpi_backend.database.models import Supplier
                supplier = db.query(Supplier).filter_by(
                    id=mapping.supplier_id
                ).first()
                
                if not supplier:
                    logger.warning(
                        f"Supplier with ID {mapping.supplier_id} not found"
                    )
                    continue
                    
                # Find all invoice items that match this item number and supplier
                # Finding records with matching item number and supplier name
                matching_items = db.query(InvoiceItem).filter(
                    InvoiceItem.item == mapping.supplier_item_ids,
                    InvoiceItem.vendor.contains(supplier.supplier_name)
                ).all()
                
                if not matching_items:
                    continue
                    
                # Update all matching items
                item_updated_count = 0
                for item in matching_items:
                    item.mpi_item = mapping.mpi_code
                    item.mpi_description = mapping.description
                    item.sheet_name = mapping.google_sheet_name
                    item_updated_count += 1
                
                total_updated_count += item_updated_count
                logger.info(
                    f"Updated {item_updated_count} items for mapping "
                    f"{mapping.supplier_item_ids}"
                )
                
                # Commit after each mapping batch to avoid large transactions
                db.commit()
                
            except Exception as e:
                logger.error(
                    f"Error updating items for mapping "
                    f"{mapping.supplier_item_ids}: {str(e)}"
                )
                db.rollback()
        
        logger.info(
            f"Update complete: {total_updated_count} items updated from "
            f"{total_mappings_processed} mappings"
        )
        return {
            "status": "success",
            "message": (f"{total_updated_count} items updated from "
                        f"{total_mappings_processed} mappings")
        }
    
    except Exception as e:
        logger.error(f"Failed to update all mappings: {str(e)}")
        if db.is_active:
            db.rollback()
        return {
            "status": "error",
            "message": f"Failed to update all mappings: {str(e)}"
        }
    finally:
        if close_db and db is not None:
            db.close()


@router.post("/update-all-mappings")
def update_all_mappings(
    db: Session = Depends(get_db),
    token: str = Depends(JWTBearer())
):
    """
    Update all invoice items by applying the latest mappings from the 
    ItemsMapping table.
    
    This is useful for propagating mapping changes to all related invoice items 
    after bulk changes to the mappings table or data migrations.
    
    Returns:
        Dict with status and count of updated items
    """
    return perform_update_all_mappings(db) 
    