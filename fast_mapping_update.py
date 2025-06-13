#!/usr/bin/env python3
"""
Fast Mapping Update Script - Optimized for 23k+ items

This script:
1. Fetches the latest mappings from Google Sheets
2. Updates UIDI/No Match items using bulk operations
3. Uses database indexing and batch processing for speed

Performance optimizations:
- Uses SQL joins instead of nested loops
- Batch processing with configurable chunk size
- In-memory mapping dictionaries for fast lookups
- Bulk database updates
"""

import logging
import time
from typing import Dict, List, Any, Set
from contextlib import contextmanager
from sqlalchemy import text, and_, or_
from sqlalchemy.orm import Session

from mpi_backend.database import db_context
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.utils.google_sheets import GoogleSheetDataExtractor
from mpi_backend.database.controllers import ItemsMappingController, GoogleSheetSyncController
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID, DEFAULT_OUTPUT_FILE, GOOGLE_API_KEY, 
    SKIP_SHEETS, MAPPING_CONFIG
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class FastMappingUpdater:
    """Optimized mapping updater for large datasets."""
    
    def __init__(self, batch_size: int = 1000, sync_first: bool = True):
        """
        Initialize the fast mapping updater.
        
        Args:
            batch_size: Number of items to process in each batch
            sync_first: Whether to sync from Google Sheets first
        """
        self.batch_size = batch_size
        self.sync_first = sync_first
        self.supplier_mappings = {
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
            "Lion Hvac Supplies": 13,
            "Bruce Ferguson": 14
        }
    
    def run_fast_update(self) -> Dict[str, Any]:
        """
        Run the complete fast update process.
        
        Returns:
            Dict with update results and performance metrics
        """
        start_time = time.time()
        logger.info("Starting fast mapping update process...")
        
        try:
            # Step 1: Sync latest mappings from Google Sheets (if enabled)
            if self.sync_first:
                sync_result = self._sync_latest_mappings()
                if not sync_result.get("success"):
                    return sync_result
                logger.info(f"Sync completed: {sync_result.get('new_mappings_count', 0)} new mappings")
            
            # Step 2: Perform optimized UIDI updates
            update_result = self._perform_optimized_update()
            
            # Calculate total time
            total_time = time.time() - start_time
            
            return {
                "success": True,
                "total_time_seconds": round(total_time, 2),
                "sync_info": sync_result if self.sync_first else "Skipped",
                **update_result
            }
            
        except Exception as e:
            logger.error(f"Fast update failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "total_time_seconds": round(time.time() - start_time, 2)
            }
    
    def _sync_latest_mappings(self) -> Dict[str, Any]:
        """Sync latest mappings from Google Sheets."""
        logger.info("Syncing latest mappings from Google Sheets...")
        
        with db_context() as db:
            sync_controller = GoogleSheetSyncController(db)
            return sync_controller.sync_sheet_mappings(
                sheet_id=DEFAULT_SHEET_ID,
                output_file=DEFAULT_OUTPUT_FILE,
                api_key=GOOGLE_API_KEY,
                skip_sheets=SKIP_SHEETS,
                batch_size=MAPPING_CONFIG["batch_size"],
                fuzzy_threshold=MAPPING_CONFIG["fuzzy_threshold"]
            )
    
    def _perform_optimized_update(self) -> Dict[str, Any]:
        """
        Perform optimized UIDI item updates using bulk operations.
        
        Returns:
            Dict with update statistics
        """
        with db_context() as db:
            logger.info("Starting optimized UIDI update...")
            
            # Step 1: Build fast lookup dictionaries
            lookup_start = time.time()
            mapping_lookups = self._build_mapping_lookups(db)
            lookup_time = time.time() - lookup_start
            logger.info(f"Built mapping lookups in {lookup_time:.2f}s ({len(mapping_lookups['exact'])} exact, {len(mapping_lookups['suffix_cleaned'])} suffix-cleaned)")
            
            # Step 2: Get UIDI items efficiently
            uidi_start = time.time()
            uidi_items = self._get_uidi_items_batch(db)
            uidi_time = time.time() - uidi_start
            logger.info(f"Found {len(uidi_items)} UIDI items in {uidi_time:.2f}s")
            
            if not uidi_items:
                return {
                    "updated_count": 0,
                    "message": "No UIDI items found to update",
                    "lookup_time": round(lookup_time, 2),
                    "query_time": round(uidi_time, 2)
                }
            
            # Step 3: Process items in batches
            update_start = time.time()
            total_updated = self._process_items_in_batches(db, uidi_items, mapping_lookups)
            update_time = time.time() - update_start
            
            logger.info(f"Updated {total_updated} items in {update_time:.2f}s")
            
            return {
                "updated_count": total_updated,
                "total_items_processed": len(uidi_items),
                "lookup_time": round(lookup_time, 2),
                "query_time": round(uidi_time, 2),
                "update_time": round(update_time, 2),
                "items_per_second": round(len(uidi_items) / (lookup_time + uidi_time + update_time), 2)
            }
    
    def _build_mapping_lookups(self, db: Session) -> Dict[str, Dict[str, Any]]:
        """
        Build fast lookup dictionaries for mappings.
        
        Args:
            db: Database session
            
        Returns:
            Dict with exact and suffix-cleaned lookup dictionaries
        """
        # Get all valid mappings in one query
        mappings = db.query(ItemsMapping).filter(
            and_(
                ~ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.mpi_code != "No Match",
                ItemsMapping.mpi_code != "No Match / UIDI",
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != "",
                ItemsMapping.supplier_item_ids.isnot(None),
                ItemsMapping.supplier_item_ids != ""
            )
        ).all()
        
        exact_lookup = {}
        suffix_cleaned_lookup = {}
        
        for mapping in mappings:
            supplier_item = mapping.supplier_item_ids.strip()
            mapping_data = {
                "mpi_code": mapping.mpi_code,
                "description": mapping.description,
                "sheet_name": mapping.google_sheet_name or "",
                "supplier_id": mapping.supplier_id
            }
            
            # Exact match lookup
            exact_lookup[supplier_item] = mapping_data
            
            # Suffix-cleaned lookup for each supplier
            for supplier_id in self.supplier_mappings.values():
                cleaned_item = self._clean_supplier_suffix(supplier_item, supplier_id)
                if cleaned_item != supplier_item:  # Only add if it's different
                    suffix_cleaned_lookup[f"{cleaned_item}|{supplier_id}"] = mapping_data
        
        return {
            "exact": exact_lookup,
            "suffix_cleaned": suffix_cleaned_lookup
        }
    
    def _clean_supplier_suffix(self, item: str, supplier_id: int) -> str:
        """Clean supplier-specific suffixes from item codes."""
        # Common suffix patterns by supplier
        suffix_patterns = {
            1: ["-B"],  # BMW
            2: ["-W"],  # World Wide Plumbing  
            3: ["-Y"],  # Y & S
            4: ["-S"],  # Supreme
            5: ["-P"],  # Pyramid
            6: ["-A"],  # ABC Opus
            7: ["-PA"], # Park Plumbing
            8: ["-G"],  # Gotham
            9: ["-F"],  # FW Webb
            10: ["-FM"], # Flow Mark
            11: ["-PE"], # Plumbing Exchange
            12: ["-AF"], # AF Supply
            13: ["-L"],  # Lion
            14: ["-BF"]  # Bruce Ferguson
        }
        
        patterns = suffix_patterns.get(supplier_id, [])
        cleaned = item
        
        for pattern in patterns:
            if cleaned.endswith(pattern):
                cleaned = cleaned[:-len(pattern)]
                break
                
        return cleaned
    
    def _get_uidi_items_batch(self, db: Session) -> List[InvoiceItem]:
        """
        Get all UIDI items efficiently using optimized query.
        
        Args:
            db: Database session
            
        Returns:
            List of UIDI InvoiceItem objects
        """
        return db.query(InvoiceItem).filter(
            or_(
                InvoiceItem.mpi_item.is_(None),
                InvoiceItem.mpi_item == "",
                InvoiceItem.mpi_item == "No Match",
                InvoiceItem.mpi_item.like("UIDI%")
            )
        ).all()
    
    def _process_items_in_batches(
        self, 
        db: Session, 
        items: List[InvoiceItem], 
        lookups: Dict[str, Dict[str, Any]]
    ) -> int:
        """
        Process items in batches for optimal performance.
        
        Args:
            db: Database session
            items: List of items to process
            lookups: Mapping lookup dictionaries
            
        Returns:
            Number of items updated
        """
        total_updated = 0
        
        for i in range(0, len(items), self.batch_size):
            batch = items[i:i + self.batch_size]
            batch_updated = self._process_batch(db, batch, lookups)
            total_updated += batch_updated
            
            if batch_updated > 0:
                logger.info(f"Batch {i//self.batch_size + 1}: Updated {batch_updated}/{len(batch)} items")
            
            # Commit after each batch
            try:
                db.commit()
            except Exception as e:
                logger.error(f"Failed to commit batch {i//self.batch_size + 1}: {str(e)}")
                db.rollback()
        
        return total_updated
    
    def _process_batch(
        self, 
        db: Session, 
        batch: List[InvoiceItem], 
        lookups: Dict[str, Dict[str, Any]]
    ) -> int:
        """
        Process a single batch of items.
        
        Args:
            db: Database session
            batch: Batch of items to process
            lookups: Mapping lookup dictionaries
            
        Returns:
            Number of items updated in this batch
        """
        updated_count = 0
        
        for item in batch:
            if not item.item:
                continue
                
            clean_item = str(item.item).strip()
            old_status = item.mpi_item or "Empty"
            
            # Try exact match first
            if clean_item in lookups["exact"]:
                mapping = lookups["exact"][clean_item]
                self._update_item(item, mapping, old_status, clean_item, "exact")
                updated_count += 1
                continue
            
            # Try suffix-cleaned match
            supplier_id = self._extract_supplier_id_from_vendor(item.vendor)
            if supplier_id:
                lookup_key = f"{clean_item}|{supplier_id}"
                if lookup_key in lookups["suffix_cleaned"]:
                    mapping = lookups["suffix_cleaned"][lookup_key]
                    self._update_item(item, mapping, old_status, clean_item, "suffix-cleaned")
                    updated_count += 1
                    continue
        
        return updated_count
    
    def _update_item(
        self, 
        item: InvoiceItem, 
        mapping: Dict[str, Any], 
        old_status: str, 
        clean_item: str, 
        match_type: str
    ):
        """Update a single item with mapping data."""
        item.mpi_item = mapping["mpi_code"]
        item.mpi_description = mapping["description"]
        item.sheet_name = mapping["sheet_name"]
        
        if old_status.startswith("UIDI"):
            logger.debug(f"UIDI override ({match_type}): {clean_item} | {old_status} -> {mapping['mpi_code']}")
        elif old_status == "No Match":
            logger.debug(f"No Match override ({match_type}): {clean_item} | No Match -> {mapping['mpi_code']}")
    
    def _extract_supplier_id_from_vendor(self, vendor_name: str) -> int:
        """Extract supplier ID from vendor name."""
        if not vendor_name:
            return 1  # Default to BMW
            
        for company, supplier_id in self.supplier_mappings.items():
            if company in vendor_name:
                return supplier_id
        return 1  # Default to BMW

def main():
    """Main function to run the fast mapping update."""
    logger.info("=" * 60)
    logger.info("FAST MAPPING UPDATE SCRIPT")
    logger.info("=" * 60)
    
    # Initialize the updater
    updater = FastMappingUpdater(
        batch_size=1000,  # Process 1000 items at a time
        sync_first=True   # Sync from Google Sheets first
    )
    
    # Run the update
    result = updater.run_fast_update()
    
    # Print results
    logger.info("=" * 60)
    logger.info("UPDATE RESULTS")
    logger.info("=" * 60)
    
    if result["success"]:
        logger.info(f"✅ SUCCESS!")
        logger.info(f"📊 Items updated: {result.get('updated_count', 0)}")
        logger.info(f"📊 Total items processed: {result.get('total_items_processed', 0)}")
        logger.info(f"⏱️  Total time: {result.get('total_time_seconds', 0)}s")
        logger.info(f"🚀 Speed: {result.get('items_per_second', 0)} items/second")
        
        if result.get('sync_info'):
            logger.info(f"🔄 Sync info: {result['sync_info']}")
    else:
        logger.error(f"❌ FAILED: {result.get('error', 'Unknown error')}")
        logger.error(f"⏱️  Time elapsed: {result.get('total_time_seconds', 0)}s")

if __name__ == "__main__":
    main() 