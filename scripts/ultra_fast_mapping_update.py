#!/usr/bin/env python3
"""
Ultra Fast Mapping Update Script

Optimized for large datasets:
- 25k+ items to update
- 100k+ database items
- 30k+ mappings

Performance features:
- Single database transaction
- In-memory hash lookups (O(1) performance)
- Bulk operations
- Minimal object creation
- Raw SQL for maximum speed
"""

import logging
import time
import sys
import os
from typing import Dict, Set, Tuple, Any
from collections import defaultdict

# Add parent directory to path for imports and change working directory
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.append(parent_dir)

# Change to parent directory so .env file is found
original_cwd = os.getcwd()
os.chdir(parent_dir)

try:
    from sqlalchemy import text, create_engine
    from sqlalchemy.orm import sessionmaker
    from mpi_backend.database import db_context
    from mpi_backend.database.controllers import GoogleSheetSyncController
    from mpi_backend.config.spreadsheet_config import (
        DEFAULT_SHEET_ID, DEFAULT_OUTPUT_FILE, GOOGLE_API_KEY, 
        SKIP_SHEETS, MAPPING_CONFIG
    )
    from mpi_backend.config import SQLALCHEMY_DATABASE_URI
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running from the correct directory and all dependencies are installed.")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class UltraFastMappingUpdater:
    """Ultra-fast mapping updater optimized for large datasets."""
    
    def __init__(self):
        # Check database connection on initialization
        self._check_database_connection()
        
        # Supplier suffix patterns for cleaning
        self.suffix_patterns = {
            1: "-B", 2: "-W", 3: "-Y", 4: "-S", 5: "-P",
            6: "-A", 7: "-PA", 8: "-G", 9: "-F", 10: "-FM",
            11: "-PE", 12: "-AF", 13: "-L", 14: "-BF"
        }
        
        # Supplier name mappings
        self.supplier_names = {
            "BMW Plumbing Supplies": 1, "World Wide Plumbing": 2,
            "Y & S Plumbing Supply": 3, "Supreme Plumbing Supply": 4,
            "Pyramid Plumbing": 5, "ABC Opus Services": 6,
            "Park Plumbing Supply": 7, "Gotham Plumbing Supply": 8,
            "FW Webb Plumbing Supply": 9, "Flow Mark Plumbing Supply": 10,
            "Plumbing Exchange": 11, "AF Supply": 12,
            "Lion Hvac Supplies": 13, "Bruce Ferguson": 14
        }
    
    def _check_database_connection(self):
        """Check if database connection is working."""
        try:
            with db_context() as db:
                db.execute(text("SELECT 1"))
            logger.info(" Database connection verified")
        except Exception as e:
            logger.error(f"❌ Database connection failed: {str(e)}")
            logger.error("Please check your database configuration and ensure the database is running")
            raise ConnectionError(f"Database connection failed: {str(e)}")
    
    def run_update(self, force_full_sync: bool = True) -> Dict[str, Any]:
        """Run the complete update process: sync mappings first, then ultra-fast UIDI update."""
        total_start = time.time()
        logger.info(" Starting Complete Mapping Update Process")
        logger.info(f"Target: 25k+ items | DB: 100k+ items | Mappings: 30k+")
        
        try:
            sync_time = 0
            
            # Step 1: MANDATORY - Update all existing mappings from Google Sheets
            if force_full_sync:
                logger.info(" Step 1: Updating ALL mappings from Google Sheets...")
                sync_start = time.time()
                sync_result = self._complete_mapping_sync()
                sync_time = time.time() - sync_start
                logger.info(f" Mapping sync completed in {sync_time:.2f}s")
                
                if not sync_result.get("success"):
                    logger.error("❌ Critical: Mapping sync failed!")
                    return {
                        "success": False,
                        "error": f"Mapping sync failed: {sync_result.get('error', 'Unknown error')}",
                        "total_time": round(time.time() - total_start, 2)
                    }
                
                logger.info(f" Successfully synced {sync_result.get('new_mappings_count', 0)} mappings")
            
            # Step 2: Ultra-fast UIDI item updates using refreshed mappings
            logger.info(" Step 2: Ultra-fast UIDI item updates...")
            update_start = time.time()
            update_result = self._ultra_fast_bulk_update()
            update_time = time.time() - update_start
            
            total_time = time.time() - total_start
            
            return {
                "success": True,
                "total_time": round(total_time, 2),
                "update_time": round(update_time, 2),
                "sync_time": round(sync_time, 2),
                "sync_result": sync_result if force_full_sync else None,
                **update_result
            }
            
        except Exception as e:
            logger.error(f"❌ Complete update failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "total_time": round(time.time() - total_start, 2)
            }
    
    def _complete_mapping_sync(self) -> Dict[str, Any]:
        """Complete mapping sync - updates ALL mappings in database from Google Sheets."""
        try:
            with db_context() as db:
                sync_controller = GoogleSheetSyncController(db)
                
                logger.info(" Extracting ALL mappings from Google Sheets...")
                result = sync_controller.sync_sheet_mappings(
                    sheet_id=DEFAULT_SHEET_ID,
                    output_file=DEFAULT_OUTPUT_FILE,
                    api_key=GOOGLE_API_KEY,
                    skip_sheets=SKIP_SHEETS,
                    batch_size=200,  # Larger batches for speed
                    fuzzy_threshold=MAPPING_CONFIG["fuzzy_threshold"]
                )
                
                if result.get("success"):
                    logger.info(f" Extraction complete:")
                    logger.info(f"   • Total mappings extracted: {result.get('total_mappings_extracted', 0):,}")
                    logger.info(f"   • New mappings added: {result.get('new_mappings_count', 0):,}")
                    logger.info(f"   • Updated mappings: {result.get('updated_mappings_count', 0):,}")
                    logger.info(f"   • Sheets processed: {result.get('sheets_processed', 0)}")
                
                return result
                
        except Exception as e:
            logger.error(f"Complete mapping sync failed: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _ultra_fast_bulk_update(self) -> Dict[str, Any]:
        """Ultra-fast bulk update using raw SQL and hash lookups."""
        logger.info("  Building ultra-fast lookup tables...")
        lookup_start = time.time()
        
        with db_context() as db:
            # Step 1: Build super-fast lookup using raw SQL
            mappings_lookup = self._build_ultra_fast_lookup(db)
            lookup_time = time.time() - lookup_start
            logger.info(f"  Built {len(mappings_lookup):,} lookups in {lookup_time:.3f}s")
            
            # Step 2: Get all UIDI items with raw SQL
            logger.info(" Fetching UIDI items...")
            fetch_start = time.time()
            
            uidi_items = self._fetch_uidi_items_raw(db)
            fetch_time = time.time() - fetch_start
            logger.info(f" Fetched {len(uidi_items):,} UIDI items in {fetch_time:.3f}s")
            
            if not uidi_items:
                return {
                    "updated_count": 0,
                    "total_items": 0,
                    "lookup_time": round(lookup_time, 3),
                    "fetch_time": round(fetch_time, 3),
                    "message": "No UIDI items found"
                }
            
            # Step 3: Ultra-fast bulk matching and update
            logger.info(" Processing matches and executing bulk update...")
            update_start = time.time()
            
            # Process all items at once for maximum speed
            updates = []
            exact_hits = 0
            suffix_hits = 0
            
            for item_id, item_code, vendor in uidi_items:
                # Try exact match first (fastest - O(1) lookup)
                if item_code in mappings_lookup:
                    mpi_code, description, sheet_name = mappings_lookup[item_code]
                    updates.append((item_id, mpi_code, description, sheet_name))
                    exact_hits += 1
                else:
                    # Try suffix-cleaned match
                    supplier_id = self._fast_supplier_lookup(vendor)
                    suffix_key = f"{item_code}|{supplier_id}"
                    if suffix_key in mappings_lookup:
                        mpi_code, description, sheet_name = mappings_lookup[suffix_key]
                        updates.append((item_id, mpi_code, description, sheet_name))
                        suffix_hits += 1
            
            # Execute single bulk update for all matches
            updated_count = self._execute_bulk_updates(db, updates)
            
            update_time = time.time() - update_start
            total_time = lookup_time + fetch_time + update_time
            
            logger.info(f" Processed {len(uidi_items):,} items, updated {updated_count:,} in {update_time:.3f}s")
            logger.info(f" Exact matches: {exact_hits:,} | Suffix matches: {suffix_hits:,}")
            
            return {
                "updated_count": updated_count,
                "total_items": len(uidi_items),
                "exact_matches": exact_hits,
                "suffix_matches": suffix_hits,
                "lookup_time": round(lookup_time, 3),
                "fetch_time": round(fetch_time, 3),
                "update_time": round(update_time, 3),
                "items_per_second": round(len(uidi_items) / total_time, 1) if total_time > 0 else 0
            }
    
    def _build_ultra_fast_lookup(self, db) -> Dict[str, Tuple[str, str, str]]:
        """Build ultra-fast lookup table using raw SQL."""
        # Single raw SQL query to get all mappings
        query = text("""
            SELECT supplier_item_ids, mpi_code, description, 
                   COALESCE(google_sheet_name, '') as sheet_name, supplier_id
            FROM supplier_item_mappings 
            WHERE mpi_code NOT LIKE 'UIDI%' 
            AND mpi_code NOT IN ('No Match', 'No Match / UIDI', '')
            AND mpi_code IS NOT NULL 
            AND supplier_item_ids IS NOT NULL 
            AND supplier_item_ids != ''
        """)
        
        result = db.execute(query)
        
        # Build lookup dictionary - key: item, value: (mpi_code, description, sheet_name)
        lookup = {}
        suffix_lookup = defaultdict(dict)  # suffix_lookup[supplier_id][cleaned_item] = mapping
        
        for row in result:
            item = row.supplier_item_ids.strip()
            mapping = (row.mpi_code, row.description or "", row.sheet_name)
            
            # Exact match lookup
            lookup[item] = mapping
            
            # Suffix-cleaned lookup for faster suffix matching
            supplier_id = row.supplier_id or 1
            if supplier_id in self.suffix_patterns:
                suffix = self.suffix_patterns[supplier_id]
                if item.endswith(suffix):
                    cleaned_item = item[:-len(suffix)]
                    suffix_lookup[supplier_id][cleaned_item] = mapping
        
        # Merge suffix lookups into main lookup with special keys
        for supplier_id, cleaned_items in suffix_lookup.items():
            for cleaned_item, mapping in cleaned_items.items():
                key = f"{cleaned_item}|{supplier_id}"
                lookup[key] = mapping
        
        return lookup
    
    def _fetch_uidi_items_raw(self, db) -> list:
        """Fetch UIDI items using raw SQL for maximum speed."""
        query = text("""
            SELECT id, item, vendor
            FROM invoice_items 
            WHERE (mpi_item IS NULL OR mpi_item = '' OR mpi_item = 'No Match' OR mpi_item LIKE 'UIDI%')
            AND item IS NOT NULL 
            AND item != ''
        """)
        
        result = db.execute(query)
        return [(row.id, row.item.strip(), row.vendor) for row in result if row.item]
    

    def _fast_supplier_lookup(self, vendor: str) -> int:
        """Fast supplier ID lookup."""
        if not vendor:
            return 1
        
        vendor_lower = vendor.lower()
        for name, supplier_id in self.supplier_names.items():
            if name.lower() in vendor_lower:
                return supplier_id
        return 1
    
    def _execute_bulk_updates(self, db, updates: list) -> int:
        """Execute ultra-fast bulk updates using optimized SQL."""
        if not updates:
            return 0
        
        # Use optimized bulk updates
        if len(updates) < 1000:
            # For smaller batches, use VALUES with JOIN
            values_list = []
            for item_id, mpi_code, description, sheet_name in updates:
                # Escape single quotes and handle NULL values
                mpi_code = mpi_code.replace("'", "''") if mpi_code else ''
                description = description.replace("'", "''") if description else ''
                sheet_name = sheet_name.replace("'", "''") if sheet_name else ''
                values_list.append(f"({item_id}, '{mpi_code}', '{description}', '{sheet_name}')")
            
            values_str = ",".join(values_list)
            
            bulk_query = text(f"""
                UPDATE invoice_items 
                SET mpi_item = v.mpi_code,
                    mpi_description = v.description,
                    sheet_name = v.sheet_name
                FROM (VALUES {values_str}) AS v(id, mpi_code, description, sheet_name)
                WHERE invoice_items.id = v.id
            """)
            
            db.execute(bulk_query)
        else:
            # For larger batches, use temporary table approach
            # Create temporary table
            db.execute(text("""
                CREATE TEMPORARY TABLE temp_updates (
                    id INTEGER,
                    mpi_code VARCHAR,
                    description VARCHAR,
                    sheet_name VARCHAR
                )
            """))
            
            # Insert data into temp table in chunks
            chunk_size = 1000
            for i in range(0, len(updates), chunk_size):
                chunk = updates[i:i + chunk_size]
                values_list = []
                for item_id, mpi_code, description, sheet_name in chunk:
                    # Escape single quotes
                    mpi_code = mpi_code.replace("'", "''")
                    description = description.replace("'", "''")
                    sheet_name = sheet_name.replace("'", "''")
                    values_list.append(f"({item_id}, '{mpi_code}', '{description}', '{sheet_name}')")
                
                values_str = ",".join(values_list)
                db.execute(text(f"INSERT INTO temp_updates VALUES {values_str}"))
            
            # Perform bulk update using temp table
            db.execute(text("""
                UPDATE invoice_items 
                SET mpi_item = temp_updates.mpi_code,
                    mpi_description = temp_updates.description,
                    sheet_name = temp_updates.sheet_name
                FROM temp_updates
                WHERE invoice_items.id = temp_updates.id
            """))
            
            # Drop temp table
            db.execute(text("DROP TABLE temp_updates"))
        
        db.commit()
        return len(updates)

def main():
    """Main execution function."""
    logger.info("=" * 60)
    logger.info(" COMPLETE MAPPING UPDATE PROCESS")
    logger.info("=" * 60)
    
    try:
        # Parse command line arguments
        skip_sync = "--no-sync" in sys.argv
        
        if skip_sync:
            logger.info("⏭  Skipping Google Sheets sync (NOT RECOMMENDED)")
            logger.warning("⚠  This will only update UIDI items with existing mappings!")
        else:
            logger.info(" Will update ALL mappings from Google Sheets first")
        
        # Check database URI
        logger.info(f" Database URI check: {SQLALCHEMY_DATABASE_URI[:50]}...")
        
        # Create updater and run
        logger.info(" Initializing updater...")
        updater = UltraFastMappingUpdater()
        
        logger.info(" Starting update process...")
        result = updater.run_update(force_full_sync=not skip_sync)
        
    except ConnectionError as e:
        logger.error("❌ Database connection error - cannot proceed")
        result = {"success": False, "error": str(e), "total_time": 0}
    except Exception as e:
        logger.error(f"❌ Initialization failed: {str(e)}")
        result = {"success": False, "error": str(e), "total_time": 0}
    
    # Print results
    logger.info("=" * 60)
    logger.info(" RESULTS")
    logger.info("=" * 60)
    
    if result["success"]:
        logger.info(f" SUCCESS!")
        logger.info(f" Items updated: {result.get('updated_count', 0):,}")
        logger.info(f" Items processed: {result.get('total_items', 0):,}")
        logger.info(f" Speed: {result.get('items_per_second', 0):,.1f} items/second")
        logger.info(f"⏱  Total time: {result.get('total_time', 0)}s")
        
        logger.info(f" Mapping sync time: {result.get('sync_time', 0)}s")
        
        # Show sync details if available
        sync_result = result.get('sync_result')
        if sync_result:
            logger.info(f" Sync details:")
            logger.info(f"   • Total extracted: {sync_result.get('total_mappings_extracted', 0):,}")
            logger.info(f"   • New mappings: {sync_result.get('new_mappings_count', 0):,}")
            logger.info(f"   • Updated mappings: {sync_result.get('updated_mappings_count', 0):,}")
        logger.info(f" Lookup time: {result.get('lookup_time', 0)}s")
        logger.info(f" Fetch time: {result.get('fetch_time', 0)}s")
        logger.info(f" Update time: {result.get('update_time', 0)}s")
        
        # Performance summary
        total_items = result.get('total_items', 0)
        if total_items > 0:
            efficiency = (result.get('updated_count', 0) / total_items) * 100
            logger.info(f" Update efficiency: {efficiency:.1f}%")
    else:
        logger.error(f"❌ FAILED: {result.get('error', 'Unknown error')}")
        logger.error(f"⏱  Time elapsed: {result.get('total_time', 0)}s")
    
    logger.info("=" * 60)

if __name__ == "__main__":
    main() 