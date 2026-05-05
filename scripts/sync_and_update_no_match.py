#!/usr/bin/env python3
"""
Sync Mappings and Update No Match Items Script

This script performs ONLY two operations:
1. Sync mappings from Google Sheet into the database
2. Update all "No Match" items using the latest mappings

DOES NOT:
- Reprocess invoices
- Run price comparisons
- Trigger background workflows
- Modify any other system functionality

Usage:
    python scripts/sync_and_update_no_match.py
"""

import sys
import os
import logging
from datetime import datetime
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
from mpi_backend.database.controllers.ItemsMappingController import ItemsMappingController
from mpi_backend.database.controllers.TemporaryItemMappingController import (
    TemporaryItemMappingController
)
from mpi_backend.utils.google_sheets_extractors.google_sheets_mapping_extractor import (
    EnhancedGoogleSheetDataExtractor
)
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID,
    GOOGLE_API_KEY,
    DEFAULT_OUTPUT_FILE,
    SKIP_SHEETS,
    MAPPING_CONFIG
)
from mpi_backend.utils.mapping_validators import (
    is_temporary_mapping,
    validate_mapping_for_permanent_storage,
    clean_mapping_data
)
from sqlalchemy import or_

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MappingSyncAndNoMatchUpdater:
    """
    Handles syncing mappings from Google Sheet and updating No Match items.
    Uses existing system functions and business logic.
    """

    def __init__(self, db_session):
        """
        Initialize the sync and update handler.

        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session
        self.mapping_controller = ItemsMappingController(db_session)
        self.temp_mapping_controller = TemporaryItemMappingController(db_session)
        self.stats = {
            "permanent_extracted": 0,
            "permanent_saved": 0,
            "permanent_updated": 0,
            "permanent_created": 0,
            "permanent_errors": 0,
            "temporary_extracted": 0,
            "temporary_saved": 0,
            "temporary_errors": 0,
            "no_match_items_found": 0,
            "no_match_items_updated": 0,
            "no_match_items_unchanged": 0
        }

    def run(self) -> Dict[str, Any]:
        """
        Execute the complete sync and update process.

        Returns:
            Dictionary with operation results
        """
        logger.info("=" * 80)
        logger.info("STARTING MAPPING SYNC AND NO MATCH UPDATE")
        logger.info("=" * 80)
        start_time = datetime.now()

        try:
            # Step 1: Sync mappings from Google Sheet
            logger.info("\n" + "=" * 80)
            logger.info("STEP 1: SYNCING MAPPINGS FROM GOOGLE SHEET")
            logger.info("=" * 80)
            sync_result = self._sync_mappings_from_google_sheet()

            if not sync_result["success"]:
                logger.error(f"Mapping sync failed: {sync_result['message']}")
                return {
                    "success": False,
                    "message": f"Mapping sync failed: {sync_result['message']}",
                    "stats": self.stats
                }

            logger.info(f"✓ Mapping sync completed successfully")
            logger.info(f"  Permanent Mappings:")
            logger.info(f"    - Extracted: {self.stats['permanent_extracted']}")
            logger.info(f"    - Saved: {self.stats['permanent_saved']}")
            logger.info(f"    - Created: {self.stats['permanent_created']}")
            logger.info(f"    - Updated: {self.stats['permanent_updated']}")
            logger.info(f"    - Errors: {self.stats['permanent_errors']}")
            logger.info(f"  Temporary Mappings:")
            logger.info(f"    - Extracted: {self.stats['temporary_extracted']}")
            logger.info(f"    - Saved: {self.stats['temporary_saved']}")
            logger.info(f"    - Errors: {self.stats['temporary_errors']}")

            # Step 2: Update No Match items
            logger.info("\n" + "=" * 80)
            logger.info("STEP 2: UPDATING NO MATCH ITEMS")
            logger.info("=" * 80)
            update_result = self._update_no_match_items()

            if not update_result["success"]:
                logger.error(f"No Match update failed: {update_result['message']}")
                return {
                    "success": False,
                    "message": f"No Match update failed: {update_result['message']}",
                    "stats": self.stats
                }

            logger.info(f"✓ No Match update completed successfully")
            logger.info(f"  - Items found: {self.stats['no_match_items_found']}")
            logger.info(f"  - Items updated: {self.stats['no_match_items_updated']}")
            logger.info(f"    • From permanent mappings: {update_result.get('updated_from_permanent', 0)}")
            logger.info(f"    • From temporary mappings: {update_result.get('updated_from_temp', 0)}")
            logger.info(f"  - Items unchanged: {self.stats['no_match_items_unchanged']}")

            # Final summary
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            logger.info("\n" + "=" * 80)
            logger.info("OPERATION COMPLETED SUCCESSFULLY")
            logger.info("=" * 80)
            logger.info(f"Duration: {duration:.2f} seconds")
            logger.info(f"Permanent mappings synced: {self.stats['permanent_saved']}")
            logger.info(f"Temporary mappings synced: {self.stats['temporary_saved']}")
            logger.info(f"Total mappings synced: {self.stats['permanent_saved'] + self.stats['temporary_saved']}")
            logger.info(f"No Match items updated: {self.stats['no_match_items_updated']}")
            logger.info("=" * 80)

            return {
                "success": True,
                "message": "Sync and update completed successfully",
                "stats": self.stats,
                "duration_seconds": duration
            }

        except Exception as e:
            logger.error(f"Operation failed with error: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Operation failed: {str(e)}",
                "stats": self.stats
            }

    def _sync_mappings_from_google_sheet(self) -> Dict[str, Any]:
        """
        Step 1: Extract and sync both permanent and temporary mappings from Google Sheet.
        Uses existing EnhancedGoogleSheetDataExtractor and controllers.

        Returns:
            Dictionary with sync results
        """
        try:
            # Extract mappings from Google Sheet using existing extractor
            logger.info("Extracting mappings from Google Sheet...")
            extractor = EnhancedGoogleSheetDataExtractor(
                sheet_id=DEFAULT_SHEET_ID,
                api_key=GOOGLE_API_KEY,
                output_file=DEFAULT_OUTPUT_FILE,
                skip_sheets=SKIP_SHEETS,
                batch_size=MAPPING_CONFIG["batch_size"],
                fuzzy_threshold=MAPPING_CONFIG["fuzzy_threshold"]
            )

            # Process all sheets
            extract_result = extractor.process_all_sheets()

            if not extract_result["success"]:
                return {
                    "success": False,
                    "message": f"Extraction failed: {extract_result['message']}"
                }

            # Get extracted mappings (both permanent and temporary)
            permanent_mappings = extract_result.get("permanent_mappings", [])
            temporary_mappings = extract_result.get("temporary_mappings", [])
            
            self.stats["permanent_extracted"] = len(permanent_mappings)
            self.stats["temporary_extracted"] = len(temporary_mappings)

            logger.info(f"Extracted {len(permanent_mappings)} permanent mappings from Google Sheet")
            logger.info(f"Extracted {len(temporary_mappings)} temporary mappings from Google Sheet")

            # Save permanent mappings to database
            logger.info("Saving permanent mappings to database...")
            save_permanent_result = self._save_permanent_mappings_to_database(permanent_mappings)

            if not save_permanent_result["success"]:
                return {
                    "success": False,
                    "message": f"Failed to save permanent mappings: {save_permanent_result['message']}"
                }

            # Save temporary mappings to database
            logger.info("Saving temporary mappings to database...")
            save_temp_result = self._save_temporary_mappings_to_database(temporary_mappings)

            if not save_temp_result["success"]:
                logger.warning(f"Failed to save temporary mappings: {save_temp_result['message']}")
                # Don't fail the entire operation if temporary mappings fail

            return {
                "success": True,
                "message": "Mappings synced successfully"
            }

        except Exception as e:
            logger.error(f"Error syncing mappings: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Error syncing mappings: {str(e)}"
            }

    def _save_permanent_mappings_to_database(self, mappings: list) -> Dict[str, Any]:
        """
        Save permanent mappings to database directly without propagation.
        Applies suffix-cleaning rules through existing business logic.
        
        OPTIMIZATION: Saves mappings directly to avoid slow propagation step.
        We'll update No Match items separately in Step 2.

        Args:
            mappings: List of permanent mapping dictionaries

        Returns:
            Dictionary with save results
        """
        try:
            total_mappings = len(mappings)
            logger.info(f"Processing {total_mappings} permanent mappings...")
            logger.info("OPTIMIZATION: Skipping propagation during sync (will update No Match items in Step 2)")

            for idx, mapping in enumerate(mappings, 1):
                try:
                    # Validate mapping data
                    if not self._validate_mapping_data(mapping):
                        self.stats["permanent_errors"] += 1
                        logger.warning(f"Invalid mapping data at index {idx}, skipping")
                        continue

                    # Prepare mapping data (cleaned through existing validators)
                    supplier_item_ids = mapping["supplier_item_ids"]
                    mpi_code = mapping["mpi_code"]
                    description = mapping["description"]
                    google_sheet_name = mapping["google_sheet_name"]
                    supplier_id = mapping["supplier_id"]

                    # Check if mapping already exists
                    existing_mapping = self.db.query(ItemsMapping).filter_by(
                        supplier_id=supplier_id,
                        supplier_item_ids=supplier_item_ids,
                        mpi_code=mpi_code
                    ).first()

                    if existing_mapping:
                        # Mapping already exists - skip (no need to update)
                        self.stats["permanent_saved"] += 1
                        logger.debug(f"Mapping already exists: {supplier_item_ids} -> {mpi_code}")
                    else:
                        # Check if there's a conflicting mapping (same item, different code)
                        conflicting_mapping = self.db.query(ItemsMapping).filter_by(
                            supplier_id=supplier_id,
                            supplier_item_ids=supplier_item_ids
                        ).filter(
                            ItemsMapping.mpi_code != mpi_code
                        ).first()

                        if conflicting_mapping:
                            # Update existing mapping
                            conflicting_mapping.mpi_code = mpi_code
                            conflicting_mapping.description = description
                            conflicting_mapping.google_sheet_name = google_sheet_name
                            self.stats["permanent_saved"] += 1
                            self.stats["permanent_updated"] += 1
                            logger.debug(f"Updated mapping: {supplier_item_ids} -> {mpi_code}")
                        else:
                            # Create new mapping
                            new_mapping = ItemsMapping(
                                supplier_id=supplier_id,
                                supplier_item_ids=supplier_item_ids,
                                mpi_code=mpi_code,
                                description=description,
                                google_sheet_name=google_sheet_name
                            )
                            self.db.add(new_mapping)
                            self.stats["permanent_saved"] += 1
                            self.stats["permanent_created"] += 1
                            logger.debug(f"Created mapping: {supplier_item_ids} -> {mpi_code}")

                    # Commit every 100 mappings to avoid large transactions
                    if idx % 100 == 0:
                        self.db.commit()
                        progress = (idx / total_mappings) * 100
                        logger.info(
                            f"Progress: {progress:.1f}% ({idx}/{total_mappings}) - "
                            f"Saved: {self.stats['permanent_saved']}, Errors: {self.stats['permanent_errors']}"
                        )

                except Exception as e:
                    self.stats["permanent_errors"] += 1
                    logger.error(f"Error saving mapping at index {idx}: {str(e)}")
                    # Rollback and continue
                    try:
                        self.db.rollback()
                    except Exception:
                        pass
                    continue

            # Final commit
            self.db.commit()
            logger.info(f"Permanent mapping save completed: {self.stats['permanent_saved']} saved, {self.stats['permanent_errors']} errors")

            return {
                "success": True,
                "message": "Permanent mappings saved successfully"
            }

        except Exception as e:
            logger.error(f"Error in save_permanent_mappings_to_database: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Error saving permanent mappings: {str(e)}"
            }

    def _save_temporary_mappings_to_database(self, mappings: list) -> Dict[str, Any]:
        """
        Save temporary mappings to database using existing controller.
        Temporary mappings store original_item -> sheet_name mappings.

        Args:
            mappings: List of temporary mapping dictionaries

        Returns:
            Dictionary with save results
        """
        try:
            total_mappings = len(mappings)
            logger.info(f"Processing {total_mappings} temporary mappings...")

            for idx, mapping in enumerate(mappings, 1):
                try:
                    # Extract temporary mapping data
                    original_item = mapping.get("supplier_item_ids", "")
                    original_description = mapping.get("description", "")
                    sheet_name = mapping.get("google_sheet_name", "")

                    if not original_item or not sheet_name:
                        self.stats["temporary_errors"] += 1
                        logger.debug(f"Skipping temporary mapping with missing data at index {idx}")
                        continue

                    # Use existing controller to save temporary mapping
                    success = self.temp_mapping_controller.create_temporary_mapping(
                        original_item=original_item,
                        original_description=original_description,
                        sheet_name=sheet_name
                    )

                    if success:
                        self.stats["temporary_saved"] += 1
                        logger.debug(f"Saved temporary mapping: {original_item} -> {sheet_name}")
                    else:
                        self.stats["temporary_errors"] += 1
                        logger.warning(f"Failed to save temporary mapping at index {idx}")

                    # Log progress every 100 mappings
                    if idx % 100 == 0:
                        progress = (idx / total_mappings) * 100
                        logger.info(
                            f"Progress: {progress:.1f}% ({idx}/{total_mappings}) - "
                            f"Saved: {self.stats['temporary_saved']}, Errors: {self.stats['temporary_errors']}"
                        )

                except Exception as e:
                    self.stats["temporary_errors"] += 1
                    logger.error(f"Error saving temporary mapping at index {idx}: {str(e)}")
                    continue

            logger.info(f"Temporary mapping save completed: {self.stats['temporary_saved']} saved, {self.stats['temporary_errors']} errors")

            return {
                "success": True,
                "message": "Temporary mappings saved successfully"
            }

        except Exception as e:
            logger.error(f"Error in save_temporary_mappings_to_database: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Error saving temporary mappings: {str(e)}"
            }

    def _validate_mapping_data(self, mapping: dict) -> bool:
        """
        Validate mapping data using existing validators.

        Args:
            mapping: Mapping dictionary to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            # Check required fields
            required_fields = ["mpi_code", "description", "supplier_item_ids", "supplier_id"]
            for field in required_fields:
                if field not in mapping or not mapping[field]:
                    logger.debug(f"Missing required field: {field}")
                    return False

            # Use existing validation logic
            cleaned_data = clean_mapping_data(mapping)
            is_valid, validation_errors = validate_mapping_for_permanent_storage(cleaned_data)

            if not is_valid:
                logger.debug(f"Validation failed: {validation_errors}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating mapping: {str(e)}")
            return False

    def _update_no_match_items(self) -> Dict[str, Any]:
        """
        Step 2: Update all "No Match" items using the latest mappings from database.
        Uses existing database functions and matching logic.

        Returns:
            Dictionary with update results
        """
        try:
            # Query all No Match items using existing patterns
            logger.info("Querying No Match items...")
            no_match_items = self.db.query(InvoiceItem).filter(
                or_(
                    InvoiceItem.mpi_item.is_(None),
                    InvoiceItem.mpi_item == "",
                    InvoiceItem.mpi_item == "No Match",
                    InvoiceItem.mpi_item.like("UIDI%")
                )
            ).all()

            self.stats["no_match_items_found"] = len(no_match_items)
            logger.info(f"Found {len(no_match_items)} No Match items")

            if not no_match_items:
                logger.info("No items to update")
                return {
                    "success": True,
                    "message": "No items to update"
                }

            # Build mapping lookup from database (both permanent and temporary)
            logger.info("Building mapping lookup from database...")
            permanent_lookup, temp_lookup = self._build_mapping_lookup()

            # Update No Match items
            logger.info("Updating No Match items...")
            logger.info("Priority order: 1) Permanent mappings, 2) Temporary mappings")
            update_result = self._apply_mappings_to_no_match_items(
                no_match_items,
                permanent_lookup,
                temp_lookup
            )

            if not update_result["success"]:
                return {
                    "success": False,
                    "message": f"Failed to update items: {update_result['message']}"
                }

            # Commit changes
            self.db.commit()
            logger.info("Changes committed successfully")

            return {
                "success": True,
                "message": "No Match items updated successfully"
            }

        except Exception as e:
            logger.error(f"Error updating No Match items: {str(e)}", exc_info=True)
            try:
                self.db.rollback()
            except Exception:
                pass
            return {
                "success": False,
                "message": f"Error updating No Match items: {str(e)}"
            }

    def _build_mapping_lookup(self) -> tuple:
        """
        Build lookup dictionaries from both permanent and temporary mappings.
        Uses existing database queries and follows the same pattern as ItemsMappingController.
        
        Returns:
            Tuple of (permanent_lookup, temp_lookup)
            - permanent_lookup: Dict mapping item codes to permanent mapping objects
            - temp_lookup: Dict mapping item codes to temporary mapping objects
        """
        try:
            # PRIORITY 1: Get valid permanent mappings (exclude temporary/UIDI)
            valid_mappings = self.db.query(ItemsMapping).filter(
                ~ItemsMapping.mpi_code.like("UIDI%"),
                ItemsMapping.mpi_code != "No Match",
                ItemsMapping.mpi_code != "No Match / UIDI",
                ItemsMapping.mpi_code.isnot(None),
                ItemsMapping.mpi_code != ""
            ).all()

            # Build permanent lookup dictionary
            # Key: clean item code, Value: mapping object
            permanent_lookup = {}

            for mapping in valid_mappings:
                # Skip temporary mappings
                if is_temporary_mapping(mapping.mpi_code, mapping.description):
                    continue

                # Clean the supplier item ID (strip whitespace)
                clean_item = mapping.supplier_item_ids.strip() if mapping.supplier_item_ids else ""
                if clean_item:
                    # Store mapping by clean item code
                    # Note: Suffix cleaning is already applied in the database
                    permanent_lookup[clean_item] = mapping

            logger.info(f"Built permanent mapping lookup with {len(permanent_lookup)} entries")

            # PRIORITY 2: Get temporary mappings (for items without permanent mappings)
            temp_mappings = self.db.query(TempItemMapping).all()
            
            # Build temporary lookup dictionary
            # Key: clean item code, Value: temporary mapping object
            temp_lookup = {}
            
            for temp_mapping in temp_mappings:
                if temp_mapping.original_item is None:
                    continue
                
                clean_item = temp_mapping.original_item.strip()
                if clean_item and clean_item not in permanent_lookup:  # Don't override permanent
                    temp_lookup[clean_item] = temp_mapping
            
            logger.info(f"Built temporary mapping lookup with {len(temp_lookup)} entries")
            logger.info(f"Total mappings available: {len(permanent_lookup) + len(temp_lookup)}")

            return permanent_lookup, temp_lookup

        except Exception as e:
            logger.error(f"Error building mapping lookup: {str(e)}")
            return {}, {}

    def _apply_mappings_to_no_match_items(
        self,
        no_match_items: list,
        permanent_lookup: dict,
        temp_lookup: dict
    ) -> Dict[str, Any]:
        """
        Apply mappings to No Match items using exact matching.
        
        PRIORITY ORDER (strictly enforced):
        1. PERMANENT mappings FIRST (highest priority)
           - Updates: mpi_item, mpi_description, sheet_name
           - If found, temporary mapping is NOT checked
        
        2. TEMPORARY mappings SECOND (only if no permanent mapping found)
           - Updates: sheet_name ONLY
           - Keeps: mpi_item and mpi_description unchanged
        
        3. NO MATCH (if neither permanent nor temporary mapping found)
           - Item remains as "No Match"

        Follows the same priority pattern as ItemsMappingController._perform_uidi_update().

        Args:
            no_match_items: List of InvoiceItem objects with No Match
            permanent_lookup: Dictionary of permanent mappings (checked FIRST)
            temp_lookup: Dictionary of temporary mappings (checked SECOND)

        Returns:
            Dictionary with update results
        """
        try:
            total_items = len(no_match_items)
            logger.info(f"Processing {total_items} No Match items...")
            
            # Track statistics by mapping type
            updated_from_permanent = 0
            updated_from_temp = 0

            for idx, item in enumerate(no_match_items, 1):
                try:
                    # Clean the invoice item code
                    clean_item_code = item.item.strip() if item.item else ""

                    if not clean_item_code:
                        self.stats["no_match_items_unchanged"] += 1
                        continue

                    # ============================================================
                    # PRIORITY ORDER: Permanent FIRST, then Temporary
                    # ============================================================
                    
                    # STEP 1: Check PERMANENT mappings FIRST (highest priority)
                    if clean_item_code in permanent_lookup:
                        mapping = permanent_lookup[clean_item_code]
                        old_mpi_item = item.mpi_item or "Empty"

                        # Apply permanent mapping (update all fields)
                        item.mpi_item = mapping.mpi_code
                        item.mpi_description = mapping.description
                        item.sheet_name = mapping.google_sheet_name or ""

                        self.stats["no_match_items_updated"] += 1
                        updated_from_permanent += 1

                        logger.debug(
                            f"Updated item {item.id} (PERMANENT): '{clean_item_code}' -> "
                            f"'{mapping.mpi_code}' (was: '{old_mpi_item}')"
                        )
                    
                    # STEP 2: Only if NO permanent mapping found, check TEMPORARY mappings
                    elif clean_item_code in temp_lookup:
                        temp_mapping = temp_lookup[clean_item_code]
                        
                        # Apply temporary mapping (update sheet_name only)
                        # Keep mpi_item and mpi_description unchanged
                        item.sheet_name = temp_mapping.sheet_name or ""

                        self.stats["no_match_items_updated"] += 1
                        updated_from_temp += 1

                        logger.debug(
                            f"Updated item {item.id} (TEMPORARY): '{clean_item_code}' -> "
                            f"sheet: '{temp_mapping.sheet_name}' (mpi_item unchanged)"
                        )
                    
                    # STEP 3: No mapping found in either permanent or temporary
                    else:
                        # No mapping found, leave as No Match
                        self.stats["no_match_items_unchanged"] += 1

                except Exception as e:
                    logger.error(f"Error processing item {item.id}: {str(e)}")
                    self.stats["no_match_items_unchanged"] += 1
                    continue

                # Log progress every 100 items
                if idx % 100 == 0:
                    progress = (idx / total_items) * 100
                    logger.info(
                        f"Progress: {progress:.1f}% ({idx}/{total_items}) - "
                        f"Updated: {self.stats['no_match_items_updated']} "
                        f"(Permanent: {updated_from_permanent}, Temp: {updated_from_temp}), "
                        f"Unchanged: {self.stats['no_match_items_unchanged']}"
                    )

            logger.info(
                f"No Match update completed: {self.stats['no_match_items_updated']} updated "
                f"(Permanent: {updated_from_permanent}, Temp: {updated_from_temp}), "
                f"{self.stats['no_match_items_unchanged']} unchanged"
            )

            return {
                "success": True,
                "message": "Items updated successfully",
                "updated_from_permanent": updated_from_permanent,
                "updated_from_temp": updated_from_temp
            }

        except Exception as e:
            logger.error(f"Error applying mappings: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Error applying mappings: {str(e)}"
            }


def main():
    """Main entry point for the script."""
    logger.info("=" * 80)
    logger.info("MAPPING SYNC AND NO MATCH UPDATE SCRIPT")
    logger.info("=" * 80)
    logger.info("This script performs two operations:")
    logger.info("1. Sync mappings from Google Sheet to database")
    logger.info("2. Update all No Match items with latest mappings")
    logger.info("=" * 80)

    # Create database session
    db = SessionLocal()

    try:
        # Create updater instance
        updater = MappingSyncAndNoMatchUpdater(db)

        # Run the sync and update process
        result = updater.run()

        # Exit with appropriate code
        if result["success"]:
            logger.info("✓ Script completed successfully")
            sys.exit(0)
        else:
            logger.error(f"✗ Script failed: {result['message']}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)

    finally:
        # Close database session
        try:
            db.close()
        except Exception as e:
            logger.error(f"Error closing database: {str(e)}")


if __name__ == "__main__":
    main()

