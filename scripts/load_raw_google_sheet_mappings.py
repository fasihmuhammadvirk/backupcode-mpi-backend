#!/usr/bin/env python3
"""
Load Google Sheet Mappings to Raw Table

This script loads data from Google Sheets directly (or optionally from a JSON file)
into the raw.raw_google_sheet_mappings table for dbt to consume.

The raw table serves as the source of truth for dbt models that will replace
the current Python-based mapping logic with more efficient SQL JOINs.

Usage:
    # Load directly from Google Sheets (recommended):
    python scripts/load_raw_google_sheet_mappings.py

    # Load from JSON file (legacy mode):
    python scripts/load_raw_google_sheet_mappings.py --from-json

    # Save JSON backup while loading from Google Sheets:
    python scripts/load_raw_google_sheet_mappings.py --save-json

Design:
    - Loads directly from Google Sheets via EnhancedGoogleSheetDataExtractor (default)
    - JSON file is now optional (--from-json for legacy mode, --save-json for backup)
    - Truncates and reloads the raw table each run (ensures clean state)
    - Preserves all metadata for debugging (row_number, column_index, etc.)
    - Combines permanent, temporary, and invalid mappings into one table
    - mapping_type column allows dbt to filter as needed
"""

import sys
import os
import json
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

# Avoid circular imports by using lazy imports for the extractor
# The extractor has a circular dependency: extractor → sheet_name_manager → controllers → extractor
from mpi_backend.database import SessionLocal
from mpi_backend.config.spreadsheet_config import DEFAULT_OUTPUT_FILE

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RawMappingLoader:
    """
    Loads extracted Google Sheet data into the raw.raw_google_sheet_mappings table.
    """

    def __init__(self, db_session):
        """
        Initialize the loader.

        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session
        self.stats = {
            "permanent_count": 0,
            "temporary_count": 0,
            "invalid_count": 0,
            "total_loaded": 0,
            "errors": []
        }

    def _ensure_raw_schema_exists(self):
        """Create the raw schema if it doesn't exist."""
        try:
            self.db.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
            self.db.commit()
            logger.info("Ensured 'raw' schema exists")
        except SQLAlchemyError as e:
            logger.warning(f"Could not create raw schema (may already exist): {e}")
            self.db.rollback()

    def _truncate_raw_table(self):
        """Truncate the raw table for a clean reload."""
        try:
            self.db.execute(text("TRUNCATE TABLE raw.raw_google_sheet_mappings RESTART IDENTITY"))
            self.db.commit()
            logger.info("Truncated raw.raw_google_sheet_mappings table")
        except SQLAlchemyError as e:
            logger.warning(f"Could not truncate table (may not exist yet): {e}")
            self.db.rollback()

    def _load_mappings_batch(self, mappings: List[Dict[str, Any]], batch_size: int = 500) -> int:
        """
        Load mappings into the raw table in batches using raw SQL.

        Args:
            mappings: List of mapping dictionaries
            batch_size: Number of records per batch

        Returns:
            Number of records loaded
        """
        loaded = 0

        for i in range(0, len(mappings), batch_size):
            batch = mappings[i:i + batch_size]
            try:
                # Build batch insert
                values = []
                for m in batch:
                    # Parse extraction_timestamp
                    extraction_ts = m.get('extraction_timestamp')
                    if extraction_ts:
                        extraction_ts = f"'{extraction_ts}'"
                    else:
                        extraction_ts = "NULL"

                    # Escape single quotes in strings
                    def escape(val):
                        if val is None:
                            return "NULL"
                        if isinstance(val, int):
                            return str(val)
                        return "'" + str(val).replace("'", "''") + "'"

                    values.append(f"""(
                        {escape(m.get('sheet_title', ''))},
                        {escape(m.get('google_sheet_name'))},
                        {escape(m.get('sheet_id'))},
                        {escape(m.get('mpi_code'))},
                        {escape(m.get('description'))},
                        {escape(m.get('supplier'))},
                        {m.get('supplier_id') or 'NULL'},
                        {escape(m.get('supplier_item_ids'))},
                        {escape(m.get('original_supplier_item_id'))},
                        {m.get('row_number') or 'NULL'},
                        {m.get('column_index') or 'NULL'},
                        {escape(m.get('mapping_type', 'unknown'))},
                        {escape(m.get('validation_status'))},
                        {extraction_ts}
                    )""")

                insert_sql = f"""
                    INSERT INTO raw.raw_google_sheet_mappings (
                        sheet_title, google_sheet_name, sheet_id,
                        mpi_code, description,
                        supplier, supplier_id,
                        supplier_item_ids, original_supplier_item_id,
                        row_number, column_index,
                        mapping_type, validation_status,
                        extraction_timestamp
                    ) VALUES {', '.join(values)}
                """

                self.db.execute(text(insert_sql))
                self.db.commit()
                loaded += len(batch)
                logger.info(f"Loaded batch {i // batch_size + 1}: {len(batch)} records")
            except SQLAlchemyError as e:
                logger.error(f"Error loading batch: {e}")
                self.db.rollback()
                self.stats["errors"].append(str(e))

        return loaded

    def load_from_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Load data from extracted dictionary into raw table.

        Args:
            data: Dictionary with mapping data (from extractor or JSON)

        Returns:
            Dictionary with load statistics
        """
        logger.info("=" * 80)
        logger.info("LOADING GOOGLE SHEET MAPPINGS TO RAW TABLE")
        logger.info("=" * 80)

        start_time = datetime.now()

        # Ensure schema exists
        self._ensure_raw_schema_exists()

        # Get mappings from data
        permanent_mappings = data.get('permanent_mappings', [])
        temporary_mappings = data.get('temporary_mappings', [])
        invalid_mappings = data.get('invalid_mappings', [])

        self.stats["permanent_count"] = len(permanent_mappings)
        self.stats["temporary_count"] = len(temporary_mappings)
        self.stats["invalid_count"] = len(invalid_mappings)

        logger.info(f"Found: {len(permanent_mappings)} permanent, "
                   f"{len(temporary_mappings)} temporary, "
                   f"{len(invalid_mappings)} invalid")

        # Truncate existing data for clean reload
        self._truncate_raw_table()

        # Combine all mappings (mapping_type already set by extractor)
        all_mappings = permanent_mappings + temporary_mappings + invalid_mappings

        # Filter out header rows and invalid entries
        filtered_mappings = []
        for m in all_mappings:
            supplier_item = m.get('supplier_item_ids', '')
            mpi_code = m.get('mpi_code', '')

            # Skip header-like entries
            if supplier_item in ('WWPS 1', 'WWPS 2', 'BMW 1', 'BMW 2', 'Y&S 1', 'Y&S 2',
                                'GOTHAM 1', 'GOTHAM 2', 'SUPREME 1', 'SUPREME 2'):
                continue
            if mpi_code == 'Item Code':
                continue
            # Skip entries with empty supplier_item_ids
            if not supplier_item or not supplier_item.strip():
                continue

            filtered_mappings.append(m)

        logger.info(f"After filtering headers: {len(filtered_mappings)} mappings")

        # Load into raw table
        logger.info("Loading mappings into raw table...")
        self.stats["total_loaded"] = self._load_mappings_batch(filtered_mappings)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info("=" * 80)
        logger.info("LOAD COMPLETE")
        logger.info(f"Total loaded: {self.stats['total_loaded']} records")
        logger.info(f"Duration: {duration:.2f} seconds")
        logger.info("=" * 80)

        return {
            "success": len(self.stats["errors"]) == 0,
            "stats": self.stats,
            "duration_seconds": duration
        }

    def load_from_json(self, json_path: str) -> Dict[str, Any]:
        """
        Load data from JSON file into raw table (legacy mode).

        Args:
            json_path: Path to the JSON file with mapping data

        Returns:
            Dictionary with load statistics
        """
        logger.info(f"Loading from JSON file: {json_path}")

        # Load data from JSON file
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            logger.info("JSON file loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load JSON file: {e}")
            return {
                "success": False,
                "error": str(e),
                "stats": self.stats
            }

        # Use the common load_from_data method
        return self.load_from_data(data)


def extract_from_google_sheets(save_json: bool = False) -> Dict[str, Any]:
    """
    Extract data directly from Google Sheets.

    Args:
        save_json: If True, save the extracted data to JSON file as backup

    Returns:
        Dictionary with extracted mapping data, or None if extraction failed
    """
    logger.info("Extracting data from Google Sheets...")
    try:
        # Lazy imports to avoid circular dependency
        from mpi_backend.database.controllers.ItemsMappingController import ItemsMappingController  # noqa: F401
        from mpi_backend.utils.google_sheets_extractors.google_sheets_mapping_extractor import (
            EnhancedGoogleSheetDataExtractor
        )
        from mpi_backend.config.spreadsheet_config import (
            DEFAULT_SHEET_ID,
            GOOGLE_API_KEY,
            SKIP_SHEETS
        )

        # Create extractor with conditional JSON output
        output_file = DEFAULT_OUTPUT_FILE if save_json else None

        extractor = EnhancedGoogleSheetDataExtractor(
            sheet_id=DEFAULT_SHEET_ID,
            api_key=GOOGLE_API_KEY,
            output_file=output_file,
            skip_sheets=SKIP_SHEETS
        )

        # Extract data - this returns the data and optionally writes to JSON
        result = extractor.process_all_sheets()

        if not result.get('success'):
            logger.error(f"Extraction failed: {result.get('message', 'Unknown error')}")
            return None

        logger.info(
            f"Extraction complete: {len(result.get('permanent_mappings', []))} permanent, "
            f"{len(result.get('temporary_mappings', []))} temporary, "
            f"{len(result.get('invalid_mappings', []))} invalid mappings"
        )

        if save_json and output_file:
            logger.info(f"JSON backup saved to: {output_file}")

        return result

    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Load Google Sheet mappings to raw table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Load directly from Google Sheets (default):
  python scripts/load_raw_google_sheet_mappings.py

  # Load from JSON file (legacy mode):
  python scripts/load_raw_google_sheet_mappings.py --from-json

  # Load from Google Sheets and save JSON backup:
  python scripts/load_raw_google_sheet_mappings.py --save-json

  # Load from specific JSON file:
  python scripts/load_raw_google_sheet_mappings.py --from-json --json-file path/to/file.json
        """
    )
    parser.add_argument("--from-json", action="store_true",
                       help="Load from JSON file instead of Google Sheets (legacy mode)")
    parser.add_argument("--save-json", action="store_true",
                       help="Save extracted data to JSON file as backup (only used with direct extraction)")
    parser.add_argument("--json-file", default=DEFAULT_OUTPUT_FILE,
                       help=f"Path to JSON file for --from-json mode (default: {DEFAULT_OUTPUT_FILE})")
    args = parser.parse_args()

    logger.info("Starting raw mapping load process")

    # Use SessionLocal from database module (safe now that imports are in correct order)
    db = SessionLocal()

    try:
        loader = RawMappingLoader(db)

        if args.from_json:
            # Legacy mode: load from JSON file
            logger.info("Using legacy mode: loading from JSON file")

            if not os.path.exists(args.json_file):
                logger.error(f"JSON file not found: {args.json_file}")
                logger.error("Run without --from-json to extract directly from Google Sheets")
                return 1

            result = loader.load_from_json(args.json_file)
        else:
            # New mode: extract directly from Google Sheets
            logger.info("Extracting directly from Google Sheets (recommended)")

            # Extract data from Google Sheets
            extraction_result = extract_from_google_sheets(save_json=args.save_json)

            if extraction_result is None:
                logger.error("Extraction failed, cannot load to database")
                return 1

            # Load the extracted data directly
            result = loader.load_from_data(extraction_result)

        if result["success"]:
            logger.info("Load completed successfully!")
            return 0
        else:
            logger.error(f"Load completed with errors: {result.get('error', result['stats']['errors'])}")
            return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
