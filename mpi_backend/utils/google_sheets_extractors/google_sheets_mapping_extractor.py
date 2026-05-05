#!/usr/bin/env python3
"""
Enhanced Google Sheet Data Extractor - Fixed version with proper temporary/permanent mapping handling.

This module provides enhanced functionality to extract and process data from Google Sheets,
with proper validation and categorization of temporary vs permanent mappings.
"""

from mpi_backend.utils.mapping_validators import (
    is_temporary_mapping,
    validate_mapping_for_permanent_storage,
    should_use_temporary_storage,
    clean_mapping_data
)
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID,
    GOOGLE_API_KEY,
    DEFAULT_OUTPUT_FILE
)
from mpi_backend.utils.supplier_suffix_manager import (
    UNKNOWN_SUPPLIER_ID,
    UNKNOWN_SUPPLIER_NAME
)
import os
import json
import logging
import re
import time
from typing import Dict, List, Any, Tuple, Optional

import pandas as pd
import requests
from googleapiclient.discovery import build
from rapidfuzz import fuzz
from io import StringIO
from datetime import datetime

# Import for sheet name management and supplier loading
from mpi_backend.database import SessionLocal
from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.utils.sheet_name_manager import SheetNameManager

# Set up logging
logger = logging.getLogger(__name__)

# Item code pattern to validate if an "item code" (AKA MPI Item Code) is valid
ITEM_CODE_PATTERN = re.compile(r'^[A-Za-z0-9\-./_ =()#%+&*" ]+$')


class EnhancedGoogleSheetDataExtractor:
    """Enhanced extractor with proper temporary/permanent mapping handling."""

    def __init__(
        self,
        sheet_id: str = None,
        api_key: str = None,
        output_file: str = None,
        batch_size: int = 100,
        skip_sheets: List[str] = None,
        fuzzy_threshold: int = 75
    ):
        """
        Initialize the EnhancedGoogleSheetDataExtractor.

        Args:
            sheet_id: Google Sheet ID
            api_key: Google API key
            output_file: Output file path for extracted data
            batch_size: Number of rows to process at once
            skip_sheets: List of sheet names to skip
            fuzzy_threshold: Threshold for fuzzy matching
        """
        # Set up configuration
        self._setup_logging()
        self._setup_configuration(
            sheet_id, api_key, output_file, batch_size, skip_sheets,
            fuzzy_threshold
        )
        self._setup_supplier_mapping()

        # Initialize tracking variables
        self.skipped_sheets = []
        self.empty_sheets = []
        self.all_items = []
        self.extraction_stats = {
            "total_extracted": 0,
            "permanent_mappings": 0,
            "temporary_mappings": 0,
            "invalid_mappings": 0,
            "sheets_processed": 0,
            "skipped_invalid_items": 0,  # Track items skipped due to validation
            "unknown_supplier_items": 0,  # Track items assigned to Unknown supplier
            "rows_without_supplier_items": 0  # Track rows with MPI code but no supplier items
        }

    def _setup_logging(self):
        """Set up logging for the extractor."""
        self.logger = logging.getLogger(f"{__name__}")

    def _setup_configuration(
        self,
        sheet_id: str,
        api_key: str,
        output_file: str,
        batch_size: int,
        skip_sheets: List[str],
        fuzzy_threshold: int
    ):
        """Set up configuration parameters."""
        # Set Google Sheet ID
        self.sheet_id = sheet_id or os.environ.get(
            "GOOGLE_SHEET_ID",
            DEFAULT_SHEET_ID
        )

        # Set Google API key
        self.api_key = api_key or os.environ.get(
            "GOOGLE_API_KEY",
            GOOGLE_API_KEY
        )

        # Set output file path
        self.output_file = output_file

        # Set batch size for processing
        self.batch_size = batch_size

        # Set default skip_sheets if None is provided
        self.skip_sheets = skip_sheets or [
            "(AB, ALL SYSTEMS)",
            "(AC, ITEMS WITHOUT TEMPORARY GROUP NAME)"
        ]

        # Set fuzzy matching threshold
        self.fuzzy_threshold = fuzzy_threshold

    def _load_suppliers_from_db(self) -> List[Tuple[int, str]]:
        """
        Load suppliers from public.suppliers table with retry logic.

        Returns:
            List of (supplier_id, supplier_name) tuples

        Raises:
            RuntimeError: If all 3 attempts fail
        """
        max_retries = 3
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                db = SessionLocal()
                try:
                    suppliers = db.query(
                        Supplier.id, Supplier.supplier_name
                    ).all()
                    if not suppliers:
                        raise ValueError("Suppliers table is empty")
                    logger.info(
                        f"Loaded {len(suppliers)} suppliers from database"
                    )
                    return [(sid, name) for sid, name in suppliers]
                finally:
                    db.close()
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Failed to load suppliers from database "
                    f"(attempt {attempt}/{max_retries}): {e}"
                )
                if attempt < max_retries:
                    time.sleep(1)

        raise RuntimeError(
            f"Failed to load suppliers from database "
            f"after {max_retries} attempts: {last_error}"
        )

    def _setup_supplier_mapping(self):
        """
        Set up supplier mappings from the public.suppliers table
        and extract key terms for matching.
        """
        # Load suppliers from the database (source of truth)
        db_suppliers = self._load_suppliers_from_db()

        # Build supplier mapping, excluding Unknown Supplier from fuzzy-match candidates
        self.supplier_mapping = {}
        for supplier_id, supplier_name in db_suppliers:
            if supplier_id != UNKNOWN_SUPPLIER_ID:
                self.supplier_mapping[supplier_name] = {"id": supplier_id}

        # Extract key terms BEFORE adding Unknown so it is not a fuzzy-match candidate
        self._extract_key_terms()

        # Add Unknown as terminal fallback (not a match candidate).
        # key_terms is empty so match_supplier() won't score against it,
        # but the key must exist because match_supplier() iterates all
        # supplier_mapping entries and reads info["key_terms"].
        self.supplier_mapping[UNKNOWN_SUPPLIER_NAME] = {
            "id": UNKNOWN_SUPPLIER_ID,
            "key_terms": [],
        }

        # Create a simplified mapping of supplier names to IDs
        self.supplier_ids = {
            name: info["id"]
            for name, info in self.supplier_mapping.items()
        }

    def _extract_key_terms(self) -> None:
        """Extract key terms from supplier names for flexible matching."""
        for supplier, info in self.supplier_mapping.items():
            # Extract acronym from supplier name
            acronym = self._create_acronym(supplier)

            # Get individual words from supplier name
            words = self._extract_meaningful_words(supplier)

            # Save key terms for matching
            info["key_terms"] = words + [acronym]

            # Add specific known variations for some suppliers
            self._add_supplier_specific_terms(supplier, info)

            # Make all terms lowercase for case-insensitive matching
            info["key_terms"] = [term.lower() for term in info["key_terms"]]
            logger.debug(f"Key terms for {supplier}: {info['key_terms']}")

    def _create_acronym(self, text: str) -> str:
        """Create an acronym from a text string."""
        return ''.join(
            word[0] for word in text.split()
            if word.lower() not in ['and', '&']
        )

    def _extract_meaningful_words(self, text: str) -> List[str]:
        """Extract meaningful words from text."""
        return [
            word for word in re.findall(r'\b\w+\b', text)
            if word.lower() not in ['and', '&', 'the', 'of', 'for', 'with']
        ]

    def _add_supplier_specific_terms(self, supplier: str, info: Dict[str, Any]):
        """Add supplier-specific known variations."""
        if "BMW" in supplier:
            info["key_terms"].extend(
                ["bmw", "plumbing", "supplies", "BMW 1", "BMW 2", "BMW 3", "BMW 4"])

        elif "World Wide" in supplier:
            info["key_terms"].extend([
                "world", "wide", "wwp", "wwps", "worldwide", "WWPS 1", "WWPS 2", "WWPS 3", "WWPS 4", "WWPS 5", "WWPS2", "WWPS3", "WWPS4", "WWPS5"
            ])

        elif "Y & S" in supplier:
            info["key_terms"].extend(
                ["y&s", "ys", "plumbing", "supply", "Y&S 1", "Y&S 2", "Y&S 3", "Y&S 4", "Y&S 5"])

        elif "Supreme" in supplier:
            info["key_terms"].extend([
                "supreme", "supremeplumbing", "Supreme 1", "Supreme 2"
            ])

        elif "Pyramid" in supplier:
            info["key_terms"].extend([
                "pyramid", "pyramidplumbing", "Pyramid 1", "Pyramid 2"
            ])

        elif "Park Plumbing" in supplier:
            info["key_terms"].extend([
                "park", "parkplumbing", "parkplumbingsupply", "Park 1", "Park 2", "Park plum"
            ])

        elif "Gotham" in supplier:
            info["key_terms"].extend([
                "gotham", "gothamsupply", "Gotham 1", "Gotham 2"
            ])

        elif "Flow Mark" in supplier:
            info["key_terms"].extend([
                "flow", "flowmark", "flowmarksupply", "Flow Mark 1", "FlowMark 1", "FlowMark 2", "Flow Mark 2", "flow 1", "flow 2", "flow 3", "FLOW MARK", "FLOW 1", "FLOW 2", "FLOW 3"
            ])

        elif "AF Supply" in supplier:
            info["key_terms"].extend([
                "af", "supply", "afsupply", "AF Supply"
            ])

        elif "Plumbing Exchange" in supplier:
            info["key_terms"].extend([
                "-PE", "pex", "plumbing exchange"
            ])

    def _extract_clean_sheet_name(self, sheet_title: str) -> str:
        """
        Extract a clean sheet name for classification.

        Args:
            sheet_title: Raw sheet title from Google Sheets

        Returns:
            Clean sheet name suitable for classification
        """
        # Remove common prefixes and suffixes
        clean_name = sheet_title.strip()

        # Remove common prefixes
        prefixes_to_remove = [
            "Sheet", "Tab", "Page", "List", "Data", "Items", "Products"
        ]

        for prefix in prefixes_to_remove:
            if clean_name.lower().startswith(prefix.lower()):
                clean_name = clean_name[len(prefix):].strip()

        # Remove common suffixes
        suffixes_to_remove = [
            "List", "Data", "Items", "Products", "Catalog", "Inventory"
        ]

        for suffix in suffixes_to_remove:
            if clean_name.lower().endswith(suffix.lower()):
                clean_name = clean_name[:-len(suffix)].strip()

        # Remove special characters and normalize
        clean_name = re.sub(r'[^\w\s-]', '', clean_name)
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()

        # If we end up with nothing meaningful, use the original
        if not clean_name or len(clean_name) < 2:
            clean_name = sheet_title.strip()

        return clean_name

    def get_sheet_list(self) -> List[Dict[str, Any]]:
        """Get list of sheets in the Google Sheet."""
        try:
            return self._get_sheet_list_via_api()
        except Exception as e:
            logger.warning(f"API method failed, using fallback: {e}")
            return self._get_fallback_sheet_list()

    def _get_sheet_list_via_api(self) -> List[Dict[str, Any]]:
        """Get sheet list via Google Sheets API."""
        try:
            service = build('sheets', 'v4', developerKey=self.api_key)
            spreadsheet = service.spreadsheets().get(
                spreadsheetId=self.sheet_id
            ).execute()

            sheets = []
            for sheet in spreadsheet.get('sheets', []):
                sheet_props = sheet.get('properties', {})
                sheets.append({
                    'title': sheet_props.get('title', ''),
                    'gid': str(sheet_props.get('sheetId', ''))
                })

            return sheets
        except Exception as e:
            logger.error(f"Failed to get sheet list via API: {e}")
            raise

    def _get_fallback_sheet_list(self) -> List[Dict[str, Any]]:
        """Fallback method to get sheet list."""
        # This would be a simplified fallback - in practice, you might
        # have a cached list or alternative method
        return []

    def match_supplier(self, col_name: str) -> Tuple[str, int, float]:
        """
        Match a column name to a supplier using fuzzy matching.

        Args:
            col_name: Column name to match

        Returns:
            Tuple of (supplier_name, supplier_id, confidence_score)
        """
        if not col_name or pd.isna(col_name):
            return UNKNOWN_SUPPLIER_NAME, UNKNOWN_SUPPLIER_ID, 0

        col_name_str = str(col_name).strip()
        if not col_name_str:
            return UNKNOWN_SUPPLIER_NAME, UNKNOWN_SUPPLIER_ID, 0

        col_name_lower = col_name_str.lower()
        best_match = None
        best_score = 0

        # Try exact matches first
        for supplier, info in self.supplier_mapping.items():
            if col_name_lower == supplier.lower():
                return supplier, self.supplier_ids[supplier], 100.0

        # Enhanced fuzzy matching for common patterns like "BMW 1", "WWPS 2", etc.
        base_name_match = re.match(r'^([A-Za-z&]+)\s*\d*\.?$', col_name_str)
        if base_name_match:
            base_name = base_name_match.group(1).strip()
            for supplier, info in self.supplier_mapping.items():
                # Check if base name matches supplier name or codes
                supplier_base = re.sub(r'\s+', '', supplier.upper())
                base_upper = re.sub(r'\s+', '', base_name.upper())

                if supplier_base.startswith(base_upper) or base_upper.startswith(supplier_base):
                    return supplier, self.supplier_ids[supplier], 95.0

        # Try fuzzy matching with key terms (with lower threshold for better matching)
        for supplier, info in self.supplier_mapping.items():
            for term in info["key_terms"]:
                score = fuzz.ratio(col_name_lower, term.lower())
                if score > best_score and score >= 70:  # Lower threshold for better matching
                    best_score = score
                    best_match = supplier

        # Additional check: if no match found, try partial matching
        if not best_match:
            for supplier, info in self.supplier_mapping.items():
                supplier_lower = supplier.lower()
                if col_name_lower in supplier_lower or supplier_lower in col_name_lower:
                    return supplier, self.supplier_ids[supplier], 85.0

        # Enhanced partial matching for common patterns
        if not best_match:
            for supplier, info in self.supplier_mapping.items():
                for term in info["key_terms"]:
                    # Check if the column name contains the key term or vice versa
                    if term.lower() in col_name_lower or col_name_lower in term.lower():
                        return supplier, self.supplier_ids[supplier], 80.0

        if best_match:
            return best_match, self.supplier_ids[best_match], best_score
        else:
            return UNKNOWN_SUPPLIER_NAME, UNKNOWN_SUPPLIER_ID, 0

    def detect_supplier_columns(
        self,
        df_head: pd.DataFrame,
        df_full: pd.DataFrame,
        sheet_title: str = ""
    ) -> Dict[str, List[int]]:
        """
        Detect supplier columns using the Zero Skipped Items Approach.

        Args:
            df_head: First few rows of the DataFrame
            df_full: Full DataFrame

        Returns:
            Dictionary mapping supplier names to column indices
        """
        supplier_columns = {}

        # Step 1: Find the last row with data in Column B (index 1)
        last_valid_row = self._find_last_valid_row_in_column_b(df_full)
        if last_valid_row < 3:  # No valid rows found (Row 4 = index 3)
            logger.warning("Column B has no valid rows, skipping sheet")
            return supplier_columns

        # Calculate total valid rows for logging purposes
        total_valid_rows = self._count_valid_rows_in_column_b(df_full)
        logger.info(f"Column B has {total_valid_rows} valid rows "
                    f"(last data at row {last_valid_row + 1}) "
                    f"to process")

        # Step 2: Start scanning from Column E (index 4) onward
        # Scan ALL columns to ensure we don't miss any supplier columns
        max_cols_to_scan = min(len(df_full.columns), 200)  # Scan up to 200 columns
        columns_to_skip = set()  # Track columns already processed (e.g., temp mapping columns)
        for col_idx in range(4, max_cols_to_scan):
            # Skip columns that were already processed as part of a multi-column group
            if col_idx in columns_to_skip:
                logger.debug(
                    f"Skipping column {col_idx} - already processed as part of multi-column group")
                continue
            try:
                # Step 3: Column Validation - Check Row 1 and Row 2
                row1_value = df_full.iloc[0, col_idx] if col_idx < len(
                    df_full.columns) else None
                row2_value = df_full.iloc[1, col_idx] if col_idx < len(
                    df_full.columns) else None

                # Check if both Row 1 and Row 2 are empty (potential header column)
                row1_empty = pd.isna(row1_value) or str(
                    row1_value).strip() == ""
                row2_empty = pd.isna(row2_value) or str(
                    row2_value).strip() == ""

                # Check all rows (1, 2, 3) for "Original Item" header
                # This ensures we catch it regardless of which row it's in
                original_item_found = False
                original_item_row = None
                
                # Check row 1 (index 0)
                if len(df_full) > 0:
                    row1_check = df_full.iloc[0, col_idx] if col_idx < len(df_full.columns) else None
                    row1_check_str = str(row1_check).strip().lower() if pd.notna(row1_check) else ""
                    if "original item" in row1_check_str:
                        original_item_found = True
                        original_item_row = 0
                
                # Check row 2 (index 1)
                if not original_item_found and len(df_full) > 1:
                    row2_check = df_full.iloc[1, col_idx] if col_idx < len(df_full.columns) else None
                    row2_check_str = str(row2_check).strip().lower() if pd.notna(row2_check) else ""
                    if "original item" in row2_check_str:
                        original_item_found = True
                        original_item_row = 1
                
                # Check row 3 (index 2)
                if not original_item_found and len(df_full) > 2:
                    row3_value = df_full.iloc[2, col_idx] if col_idx < len(
                        df_full.columns) else None
                    row3_str = str(row3_value).strip(
                    ).lower() if pd.notna(row3_value) else ""
                    if "original item" in row3_str:
                        original_item_found = True
                        original_item_row = 2

                # Special handling for "Original Item" - ONLY extract this column as temporary mappings
                # The columns after it (Original Description, Total Qty, Unit Cost, Total Amount) are metadata, NOT mappings
                if original_item_found:
                    logger.info(
                        f"Found 'Original Item' header at column {col_idx} (row {original_item_row + 1})")

                    # ONLY add "Original Item" column to Temporary
                    if "Temporary" not in supplier_columns:
                        supplier_columns["Temporary"] = []
                    supplier_columns["Temporary"].append(col_idx)
                    columns_to_skip.add(col_idx)  # Mark column as processed
                    logger.info(f"Added 'Original Item' column {col_idx} as temporary mapping source")

                    # Mark the NEXT 4 columns as IGNORED (don't extract them - they're metadata, not mappings)
                    # These columns contain: Original Description, Total Qty, Unit Cost, Total Amount
                    ignored_headers = ["Original Description", "Total Qty", "Unit Cost", "Total Amount"]
                    for i, header_name in enumerate(ignored_headers, start=1):
                        ignored_col_idx = col_idx + i
                        if ignored_col_idx < len(df_full.columns):
                            columns_to_skip.add(ignored_col_idx)  # Skip but don't add to any supplier
                            logger.info(f"Marking column {ignored_col_idx} as IGNORED ('{header_name}' - metadata only)")

                    # Continue to next unprocessed column (columns_to_skip will handle skipping)
                    continue

                # Continue with existing logic for other header detection
                if row1_empty and row2_empty:
                    # Check if Row 3 contains header-like content to confirm this is NOT a supplier column
                    if len(df_full) > 2:
                        row3_value = df_full.iloc[2, col_idx] if col_idx < len(
                            df_full.columns) else None
                        row3_str = str(row3_value).strip(
                        ).lower() if pd.notna(row3_value) else ""

                        # Define other header terms that indicate this is NOT a supplier column
                        other_header_indicators = [
                            "original description", "item code", "mpi code", "description",
                            "size", "supplier", "cost", "price", "amount", "quantity", "qty",
                            "part number", "sku", "model", "type", "category",
                            "group", "class", "division", "section", "view",
                            "ready for", "gave for", "date", "all", "item2", "item4", "item6", "item7"
                        ]

                        if any(indicator in row3_str for indicator in other_header_indicators):
                            logger.info(
                                f"Column {col_idx} identified as header column (Row 1&2 empty, Row 3='{row3_str}'), skipping supplier detection")
                            continue  # Skip this column - it's a header, not a supplier column
                        else:
                            logger.debug(
                                f"Column {col_idx} has empty Row 1 & 2 but Row 3='{row3_str}' doesn't match header patterns, continuing to scan")
                    else:
                        logger.debug(
                            f"Column {col_idx} has empty Row 1 & 2 but not enough rows to check header, continuing to scan")

                # Step 4: Use single row for supplier identifier (Row 1 if available, otherwise Row 2)
                supplier_identifier = self._get_single_row_supplier_identifier(
                    row1_value, row2_value)

                # Step 5: Enhanced logic - if no supplier identifier but column has valid item data, assign to "Unknown" supplier
                if not supplier_identifier:
                    # Check if this column has any valid item data in the data rows (rows 4+)
                    # Scan DEEPER and MORE COMPREHENSIVELY to catch ALL items
                    has_valid_data = False
                    valid_item_found = None
                    # Scan a much larger range to ensure we catch all items
                    # Use last_valid_row as base, but extend significantly to catch items beyond Column B range
                    scan_end = min(max(last_valid_row + 50, 500), len(df_full))  # Scan up to 50 rows past last valid, or 500 rows, whichever is smaller
                    for row_idx in range(3, scan_end):
                        if row_idx < len(df_full) and col_idx < len(df_full.columns):
                            cell_value = df_full.iloc[row_idx, col_idx]
                            if pd.notna(cell_value) and str(cell_value).strip():
                                cell_str = str(cell_value).strip()
                                # Use the actual validation function to check if it's a valid item code
                                # This ensures we catch all valid items, not just simple patterns
                                if self._is_valid_item_code(cell_str):
                                    has_valid_data = True
                                    valid_item_found = cell_str
                                    logger.debug(
                                        f"Found valid item data in column {col_idx} "
                                        f"at row {row_idx}: '{cell_str}'"
                                    )
                                    break

                    if has_valid_data:
                        # Enhanced logic: Dynamically detect supplier based on item patterns in the column
                        # This ensures no columns are missed and works for any supplier
                        detected_supplier = self._detect_supplier_from_item_patterns(
                            df_full, col_idx, sheet_title)

                        if detected_supplier:
                            supplier_identifier = detected_supplier
                            logger.info(
                                f"Column {col_idx} detected as {detected_supplier} based on item patterns "
                                f"(found item: {valid_item_found})")
                        else:
                            # Assign to "Unknown" supplier to ensure these items are extracted
                            # DEFENSIVE STRATEGY: Rather than skip columns with unidentified suppliers,
                            # we extract them as "Unknown" to prevent data loss
                            supplier_identifier = f"Unknown_{col_idx}"
                            logger.warning(
                                f"Column {col_idx} has valid item data but no supplier identifier, "
                                f"assigning to Unknown supplier (found item: {valid_item_found}). "
                                f"This may indicate a new supplier or misspelled header in the spreadsheet.")
                    else:
                        # Final check: scan even deeper if we haven't found anything yet
                        # This catches items that might be very deep in the column
                        deep_scan_end = min(1000, len(df_full))  # Scan up to 1000 rows
                        for row_idx in range(scan_end, deep_scan_end):
                            if row_idx < len(df_full) and col_idx < len(df_full.columns):
                                cell_value = df_full.iloc[row_idx, col_idx]
                                if pd.notna(cell_value) and str(cell_value).strip():
                                    cell_str = str(cell_value).strip()
                                    if self._is_valid_item_code(cell_str):
                                        has_valid_data = True
                                        valid_item_found = cell_str
                                        supplier_identifier = f"Unknown_{col_idx}"
                                        logger.warning(
                                            f"Column {col_idx} found valid item in deep scan at row {row_idx}: '{cell_str}', "
                                            f"assigning to Unknown supplier. Deep scan indicates items far from headers.")
                                        break
                            if has_valid_data:
                                break

                if not supplier_identifier:
                    logger.debug(
                        f"Column {col_idx} has no valid supplier identifier in Row 1 or Row 2, skipping")
                    continue

                # Step 6: Fuzzy match to SUPPLIER_MAPPING
                logger.debug(
                    f"Attempting to match supplier identifier: '{supplier_identifier}' for column {col_idx}")
                supplier_name, supplier_id, confidence = self.match_supplier(
                    supplier_identifier)

                if confidence >= self.fuzzy_threshold and supplier_id is not None and supplier_id > 0:
                    if supplier_name not in supplier_columns:
                        supplier_columns[supplier_name] = []
                    supplier_columns[supplier_name].append(col_idx)

                    logger.info(
                        f"Detected supplier column {col_idx}: '{supplier_identifier}' -> {supplier_name} "
                        f"(confidence: {confidence})"
                    )
                elif confidence >= self.fuzzy_threshold and supplier_id is None:
                    # This is a supplier like Bruce or Ferguson that should be treated as temporary
                    if "Temporary" not in supplier_columns:
                        supplier_columns["Temporary"] = []
                    supplier_columns["Temporary"].append(col_idx)
                    logger.info(
                        f"Detected {supplier_name} column {col_idx} (no database ID), treating as temporary mapping"
                    )
                elif supplier_identifier.startswith("Unknown_"):
                    # Handle unknown supplier columns
                    # IMPORTANT: This is a defensive fallback to prevent data loss
                    # When a column has valid items but no recognizable supplier header:
                    # - Could be a new supplier added to spreadsheet without updating code
                    # - Could be a misspelled supplier name
                    # - Could be a custom/test column
                    # We assign to Unknown Supplier as a placeholder rather than losing the data
                    # This allows items to be extracted and manually reviewed/corrected later
                    supplier_name = UNKNOWN_SUPPLIER_NAME
                    supplier_id = UNKNOWN_SUPPLIER_ID  # Unknown Supplier as safe default
                    if supplier_name not in supplier_columns:
                        supplier_columns[supplier_name] = []
                    supplier_columns[supplier_name].append(col_idx)

                    logger.warning(
                        f"Detected unknown supplier column {col_idx}: '{supplier_identifier}' -> {supplier_name} "
                        f"(assigned to supplier_id={supplier_id} as fallback). "
                        f"Manual review recommended to identify correct supplier."
                    )
                else:
                    # If supplier identifier exists but doesn't match well, still extract items
                    # DEFENSIVE FALLBACK: Check if column has valid item data before skipping
                    # This ensures we don't lose data from columns with unrecognized headers
                    logger.debug(
                        f"Low confidence match for column {col_idx}: '{supplier_identifier}' "
                        f"(confidence: {confidence}), scanning for valid items...")
                    
                    has_valid_data = False
                    valid_item_found = None
                    scan_end = min(max(last_valid_row + 50, 500), len(df_full))  # Extended scan range
                    
                    for row_idx in range(3, scan_end):
                        if row_idx < len(df_full) and col_idx < len(df_full.columns):
                            cell_value = df_full.iloc[row_idx, col_idx]
                            if pd.notna(cell_value) and str(cell_value).strip():
                                cell_str = str(cell_value).strip()
                                if self._is_valid_item_code(cell_str):
                                    has_valid_data = True
                                    valid_item_found = cell_str
                                    logger.debug(
                                        f"Found valid item '{cell_str}' in column {col_idx} at row {row_idx + 1}")
                                    break
                    
                    # If still not found, do a deep scan up to 1000 rows
                    if not has_valid_data:
                        deep_scan_end = min(1000, len(df_full))
                        logger.debug(
                            f"No items found in initial scan, performing deep scan to row {deep_scan_end}")
                        for row_idx in range(scan_end, deep_scan_end):
                            if row_idx < len(df_full) and col_idx < len(df_full.columns):
                                cell_value = df_full.iloc[row_idx, col_idx]
                                if pd.notna(cell_value) and str(cell_value).strip():
                                    cell_str = str(cell_value).strip()
                                    if self._is_valid_item_code(cell_str):
                                        has_valid_data = True
                                        valid_item_found = cell_str
                                        logger.debug(
                                            f"Deep scan found valid item '{cell_str}' in column {col_idx} at row {row_idx + 1}")
                                        break
                    
                    if has_valid_data:
                        # Assign to Unknown Supplier to ensure items are extracted
                        # This prevents data loss from columns with unrecognized headers
                        supplier_name = UNKNOWN_SUPPLIER_NAME
                        supplier_id = UNKNOWN_SUPPLIER_ID
                        if supplier_name not in supplier_columns:
                            supplier_columns[supplier_name] = []
                        supplier_columns[supplier_name].append(col_idx)
                        logger.warning(
                            f"Column {col_idx}: '{supplier_identifier}' has low confidence ({confidence}) "
                            f"but contains valid items (e.g., '{valid_item_found}'), "
                            f"assigning to Unknown supplier to prevent data loss. "
                            f"Manual review recommended.")
                    else:
                        logger.debug(
                            f"Column {col_idx}: '{supplier_identifier}' has no supplier match "
                            f"(confidence: {confidence}) and no valid items found, skipping"
                        )

            except Exception as e:
                logger.error(f"Error processing column {col_idx}: {str(e)}")
                continue

        # Log comprehensive summary of column detection
        total_columns_detected = sum(len(cols) for cols in supplier_columns.values())
        logger.info(
            f"Column detection complete for sheet '{sheet_title}': "
            f"Detected {len(supplier_columns)} supplier(s) across {total_columns_detected} column(s)")
        
        for supplier_name, col_indices in supplier_columns.items():
            logger.info(
                f"  - {supplier_name}: {len(col_indices)} column(s) at indices {col_indices}")
        
        if not supplier_columns:
            logger.error(
                f"CRITICAL: No supplier columns detected in sheet '{sheet_title}'. "
                f"This will result in zero items extracted. Check sheet format and headers.")
        
        return supplier_columns

    def _find_last_valid_row_in_column_b(self, df: pd.DataFrame) -> int:
        """
        Find the last row with data in Column B (index 1) from Row 4 down.

        Args:
            df: Full DataFrame

        Returns:
            Index of the last row containing data in Column B
        """
        if len(df.columns) < 2:
            return 3  # Return Row 4 (index 3) as default

        last_valid_row = 3  # Start with Row 4 (index 3)

        # Scan all rows from Row 4 (index 3) down
        for row_idx in range(3, len(df)):
            try:
                cell_value = df.iloc[row_idx, 1]  # Column B (index 1)
                if pd.notna(cell_value) and str(cell_value).strip():
                    last_valid_row = row_idx
            except (IndexError, KeyError):
                continue

        return last_valid_row

    def _count_valid_rows_in_column_b(self, df: pd.DataFrame) -> int:
        """
        Count all non-empty rows in Column B (index 1) from Row 4 down.
        This method is kept for backward compatibility and logging purposes.

        Args:
            df: Full DataFrame

        Returns:
            Number of valid rows in Column B
        """
        if len(df.columns) < 2:
            return 0

        valid_count = 0
        # Start from Row 4 (index 3) down
        for row_idx in range(3, len(df)):
            try:
                cell_value = df.iloc[row_idx, 1]  # Column B (index 1)
                if pd.notna(cell_value) and str(cell_value).strip():
                    valid_count += 1
            except (IndexError, KeyError):
                continue

        return valid_count

    def _get_single_row_supplier_identifier(self, row1_value, row2_value) -> str:
        """
        Get supplier identifier from a single row (Row 1 if available, otherwise Row 2).
        Smart logic to prefer valid supplier names over invalid item codes.

        Args:
            row1_value: Value from Row 1
            row2_value: Value from Row 2

        Returns:
            Supplier identifier string from the best available row
        """
        row1_str = str(row1_value).strip() if pd.notna(row1_value) else ""
        row2_str = str(row2_value).strip() if pd.notna(row2_value) else ""

        # Define known supplier names and keywords
        supplier_keywords = [
            "bmw", "world wide", "wwp", "y&s", "ys", "supreme", "pyramid",
            "abc", "opus", "park", "gotham", "flow mark", "flowmark",
            "plumbing exchange", "pex", "af supply", "lion", "hvac",
            "bruce", "ferguson", "fw webb", "webb"
        ]

        # Check if row1 looks like a valid supplier name
        row1_lower = row1_str.lower()
        row1_is_supplier = any(
            keyword in row1_lower for keyword in supplier_keywords)

        # Check if row2 looks like a valid supplier name
        row2_lower = row2_str.lower()
        row2_is_supplier = any(
            keyword in row2_lower for keyword in supplier_keywords)

        # Smart logic: prefer supplier names over item codes
        if row1_is_supplier:
            return row1_str
        elif row2_is_supplier:
            return row2_str
        elif row1_str:  # If row1 has data but not a supplier name, use it
            return row1_str
        elif row2_str:  # If row2 has data but not a supplier name, use it
            return row2_str

        # If both are empty, return empty (column will be skipped)
        return ""

    def _detect_supplier_from_item_patterns(
        self,
        df_full: pd.DataFrame,
        col_idx: int,
        sheet_title: str
    ) -> Optional[str]:
        """
        Dynamically detect supplier based on item patterns in the column.

        Args:
            df_full: Full DataFrame
            col_idx: Column index to check
            sheet_title: Sheet title for context

        Returns:
            Supplier name if detected, None otherwise
        """
        # Define supplier patterns based on item suffixes and keywords
        # Uses centralized supplier_suffix_manager for suffix mappings
        # CRITICAL: Check suffixes FIRST, then keywords as fallback
        # Suffixes are more reliable for detection (e.g., SP00009939-W clearly indicates World Wide)
        # Order: [suffix, keywords...] - suffix checked first for accuracy
        supplier_patterns = {
            "BMW Plumbing Supplies": ["-B", "bmw"],
            "World Wide Plumbing": ["-W", "wwp", "worldwide"],
            "Y & S Plumbing Supply": ["-Y", "y&s", "ys"],
            "Supreme Plumbing Supply": ["-S", "supreme"],
            "Pyramid Plumbing": ["-P", "pyramid"],
            "ABC Opus Services": ["-A", "abc", "opus"],
            "Park Plumbing Supply": ["-P", "park"],
            "Gotham Plumbing Supply": ["-G", "gotham"],
            "FW Webb Plumbing Supply": ["-F", "fw", "webb"],
            "Flow Mark Plumbing Supply": ["-FM", "flowmark", "flow mark"],
            "Plumbing Exchange": ["-PE", "pex", "plumbing exchange"],
            "AF Supply": ["-AF", "af supply"],
            "Lion Hvac Supplies": ["-L", "lion", "hvac"],
            "Bruce Supply Corp.": ["-BR", "bruce"]
        }

        # Build suffix list sorted by length descending so longer suffixes
        # (e.g. "-BR") are matched before shorter ones (e.g. "-B") that would
        # otherwise shadow them via substring containment.
        suffix_entries = []
        keyword_entries = []
        for supplier, patterns in supplier_patterns.items():
            for pattern in patterns:
                if pattern.startswith("-"):
                    suffix_entries.append((supplier, pattern))
                else:
                    keyword_entries.append((supplier, pattern))
        suffix_entries.sort(key=lambda x: len(x[1]), reverse=True)

        # Scan column for item patterns - scan deeper to catch all items
        # Use last_valid_row from Column B to determine scan range, but extend significantly
        last_valid_row = self._find_last_valid_row_in_column_b(df_full)
        scan_end = min(max(last_valid_row + 50, 500), len(df_full))  # Extended scan range

        for row_idx in range(3, scan_end):
            if row_idx < len(df_full) and col_idx < len(df_full.columns):
                cell_value = df_full.iloc[row_idx, col_idx]
                if pd.notna(cell_value):
                    cell_str = str(cell_value).strip()
                    # Use validation function to ensure we're checking valid item codes
                    if self._is_valid_item_code(cell_str):
                        cell_lower = cell_str.lower()
                        # Pass 1: exact suffix match (longest first to avoid shadowing)
                        for supplier, suffix in suffix_entries:
                            if cell_lower.endswith(suffix.lower()):
                                logger.debug(
                                    f"Found suffix '{suffix}' in '{cell_str}' "
                                    f"for supplier '{supplier}' in column {col_idx}"
                                )
                                return supplier
                        # Pass 2: keyword substring fallback
                        for supplier, keyword in keyword_entries:
                            if keyword.lower() in cell_lower:
                                logger.debug(
                                    f"Found keyword '{keyword}' in '{cell_str}' "
                                    f"for supplier '{supplier}' in column {col_idx}"
                                )
                                return supplier

        return None

    def _validate_first_two_rows_have_supplier_data(
        self,
        df_full: pd.DataFrame,
        col_idx: int
    ) -> bool:
        """
        Validate that a column contains actual supplier data in the first few rows.

        Args:
            df_full: Full DataFrame
            col_idx: Column index to validate

        Returns:
            True if column contains valid supplier data
        """
        if col_idx >= len(df_full.columns):
            return False

        # Check first few rows for actual data
        for row_idx in range(min(5, len(df_full))):
            try:
                cell_value = df_full.iloc[row_idx, col_idx]
                if pd.notna(cell_value):
                    cell_str = str(cell_value).strip()
                    if (cell_str and
                        len(cell_str) >= 2 and
                        not any(term in cell_str.lower() for term in
                                ["item", "code", "description", "supplier", "header"])):
                        return True
            except (IndexError, KeyError):
                continue

        return False

    def process_sheet(self, sheet_title: str, gid: str) -> List[Dict[str, Any]]:
        """
        Process a single sheet and extract mappings.

        Args:
            sheet_title: Title of the sheet
            gid: Google Sheet ID (sheet_id)

        Returns:
            List of extracted mappings
        """
        try:
            # Get canonical sheet name from metadata table
            canonical_sheet_name = sheet_title  # Default to provided title
            try:
                db = SessionLocal()
                try:
                    sheet_manager = SheetNameManager(db, self.sheet_id, self.api_key)
                    canonical = sheet_manager.get_canonical_sheet_name(gid)
                    if canonical:
                        canonical_sheet_name = canonical
                        logger.debug(f"Using canonical name '{canonical_sheet_name}' for gid {gid}")
                finally:
                    db.close()
            except Exception as e:
                logger.warning(f"Failed to get canonical name for gid {gid}, using '{sheet_title}': {str(e)}")

            # Skip sheets that are in the skip list
            if any(skip_name in canonical_sheet_name for skip_name in self.skip_sheets):
                self.skipped_sheets.append(canonical_sheet_name)
                logger.debug(f"Skipping sheet: {canonical_sheet_name}")
                return []

            # Get sheet data
            df = self._get_sheet_dataframe(gid)

            if df is None or df.empty:
                self.empty_sheets.append(canonical_sheet_name)
                logger.debug(f"Sheet is empty: {canonical_sheet_name}")
                return []

            # Detect supplier columns
            supplier_columns = self.detect_supplier_columns(
                df.head(), df, canonical_sheet_name)

            # Log detected supplier columns with comprehensive summary
            if supplier_columns:
                total_columns = sum(len(cols) for cols in supplier_columns.values())
                logger.info(
                    f"Detected {len(supplier_columns)} supplier(s) across {total_columns} column(s) in sheet '{canonical_sheet_name}':")
                for supplier, columns in supplier_columns.items():
                    if supplier == UNKNOWN_SUPPLIER_NAME:
                        logger.warning(f"  {supplier}: columns {columns} - REQUIRES MANUAL REVIEW")
                    else:
                        logger.info(f"  {supplier}: columns {columns}")
            else:
                logger.error(
                    f"NO supplier columns detected in sheet: '{canonical_sheet_name}'. "
                    f"This sheet will be skipped. Possible causes: "
                    f"1) Empty sheet, 2) No recognizable headers, 3) Data format changed")
                logger.debug(
                    f"Sheet {canonical_sheet_name} has {len(df.columns)} columns and {len(df)} rows")
                # Log first few rows to help debug
                for i in range(min(5, len(df))):
                    # First 10 columns
                    logger.debug(f"Row {i+1}: {df.iloc[i].tolist()[:10]}")
                return []

            # Process the sheet data for mapped items (start from Row 4, index 3)
            # Pass the gid (sheet_id) to the processing method
            extracted_items = self._process_dataframe_chunk(
                df, supplier_columns, canonical_sheet_name, 3, gid
            )

            # Enhanced extractor focuses only on item mapping (permanent mappings)
            # Temporary items are handled by the dedicated TemporaryMappingExtractor
            logger.info(
                f"Extracted {len(extracted_items)} mapped items from sheet: {sheet_title}"
            )

            return extracted_items

        except Exception as e:
            logger.error(f"Error processing sheet {sheet_title}: {str(e)}")
            return []

    def _get_sheet_dataframe(self, gid: str) -> Optional[pd.DataFrame]:
        """Get DataFrame from Google Sheet."""
        try:
            url = f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export"
            params = {
                'format': 'csv',
                'gid': gid
            }

            response = requests.get(url, params=params)
            if response.status_code == 200:
                # Read CSV data
                df = pd.read_csv(
                    StringIO(response.text),
                    header=None,
                    na_filter=False
                )
                return df
            else:
                logger.error(
                    f"Failed to get sheet data: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error getting sheet data: {e}")
            return None

    def _process_dataframe_chunk(
        self,
        df: pd.DataFrame,
        supplier_columns: Dict[str, List[int]],
        sheet_title: str,
        start_row: int,
        sheet_id: str = None
    ) -> List[Dict[str, Any]]:
        """
        Process a chunk of DataFrame data and extract mappings using Comprehensive Data Cluster Approach.

        Enhanced to handle:
        - Data clusters with gaps (empty rows between data)
        - Data appearing after 300+ empty rows
        - All valid rows in Column B to determine processing range for all supplier columns

        Args:
            df: DataFrame to process
            supplier_columns: Dictionary mapping suppliers to column indices
            sheet_title: Name of the sheet (canonical name)
            start_row: Starting row index (should be 3 for Row 4)
            sheet_id: Google Sheets gid for tracking

        Returns:
            List of extracted mappings
        """
        extracted_items = []

        # Step 1: Find ALL valid rows in Column B (Item Code column)
        # This will handle data clusters with gaps and data appearing after many empty rows
        all_valid_rows_in_column_b = self._find_all_valid_rows_in_column_b(
            df, start_row)

        if not all_valid_rows_in_column_b:
            logger.warning(
                f"No valid rows found in Column B for sheet {sheet_title}")

            # Check for "original item" column and extract orignal items
            # For example, the "FIXTURES" sheet doesn't have any permanent items
            mask = (df == "Original Item")
            locations = mask.stack()[mask.stack()].index.tolist()

            # Check if locations is empty before accessing
            if not locations:
                logger.warning(
                    f"No 'Original Item' column found in sheet {sheet_title}. "
                    f"Cannot extract temporary items without valid Column B data or Original Item column."
                )
                return extracted_items

            if len(locations) > 1:
                logger.warning(f"Found more than one 'Original Item' column: {locations}. Using the first one")

            row, col = locations[0]

            # Extract the values
            items = df.loc[row + 1:, col].tolist()
            for idx, item in enumerate(items, start=2):
                # For temporary mappings, we set mpi_code and description to None
                # These are items that haven't been assigned an MPI code yet
                # They only have: sheet_name (for categorization) and supplier_item_ids (the original item code)
                mapping_data = {
                    'sheet_title': sheet_title,
                    'google_sheet_name': sheet_title,
                    'sheet_id': sheet_id,  # Add sheet_id for tracking
                    'mpi_code': None,  # NO MPI CODE for temporary mappings
                    'description': None,  # NO DESCRIPTION for temporary mappings
                    'supplier': 'Temporary',
                    'supplier_id': None,  # No specific supplier ID for temporary
                    'supplier_item_ids': item,  # The actual item code from "Original Item" column
                    'original_supplier_item_id': item,
                    'row_number': row + idx, # 1-based index
                    'column_index': col + 1,
                    'extraction_timestamp': datetime.now().isoformat(),
                    'mapping_type': 'temporary',
                    'validation_status': 'valid_temporary'
                }

                extracted_items.append(mapping_data)

            return extracted_items

        # Step 2: Log the comprehensive data analysis
        total_valid_rows = len(all_valid_rows_in_column_b)
        first_valid_row = min(all_valid_rows_in_column_b)
        last_valid_row = max(all_valid_rows_in_column_b)

        logger.info(f"Column B Analysis for {sheet_title}:")
        logger.info(f"  - Total valid rows found: {total_valid_rows}")
        logger.info(f"  - First valid row: {first_valid_row + 1}")
        logger.info(f"  - Last valid row: {last_valid_row + 1}")
        logger.info(
            f"  - Row range: {last_valid_row - first_valid_row + 1} rows")

        # Step 3: Process rows - be more flexible to catch all items
        # Process both rows with valid Column B data AND scan all rows for supplier items
        # This ensures we don't miss items in rows where Column B/C might be empty
        rows_to_process = set(all_valid_rows_in_column_b)
        
        # Also scan additional rows around valid rows to catch items that might be
        # in rows without MPI codes/descriptions
        for valid_row in all_valid_rows_in_column_b:
            # Include rows before and after valid rows (within reason)
            for offset in range(-2, 3):  # Check 2 rows before and 2 rows after
                check_row = valid_row + offset
                if 1 <= check_row < len(df):  # Start from row 2 (index 1) to catch first data rows
                    rows_to_process.add(check_row)
        
        # Additionally, scan ALL rows in supplier columns to ensure we don't miss any items
        # This is critical for catching items that might be in rows without Column B data
        if supplier_columns:
            # Determine the range to scan - scan ENTIRE DataFrame to ensure no items are missed
            # Start from row 2 (index 1) to catch headers in row 2 or 3, and first data row in row 3 or 4
            # This ensures we never miss the first data row after headers
            scan_start = 1  # Start from row 2 (index 1) to catch all possible header positions
            scan_end = len(df)  # Scan to the very end of the DataFrame
            
            # Scan all rows in this range for supplier items
            for row_idx in range(scan_start, scan_end):
                if row_idx not in rows_to_process:
                    # Check if this row has any valid supplier items
                    has_supplier_item = False
                    for supplier, col_indices in supplier_columns.items():
                        for col_idx in col_indices:
                            if col_idx < len(df.columns):
                                cell_value = df.iloc[row_idx, col_idx] if row_idx < len(df) else None
                                if pd.notna(cell_value) and str(cell_value).strip():
                                    cell_str = str(cell_value).strip()
                                    
                                    # Special logging for FLGP336-B during scanning
                                    if 'FLGP336-B' in cell_str.upper():
                                        logger.info(
                                            f"*** SCANNING: Found FLGP336-B in sheet '{sheet_title}', "
                                            f"row {row_idx + 1}, column {col_idx + 1}, "
                                            f"supplier: {supplier}, value: '{cell_str}' ***")
                                    
                                    if cell_str.lower() not in ['nan', 'none', '']:
                                        # Check if it's a valid item code
                                        if self._is_valid_item_code(cell_str) or supplier == "Temporary":
                                            if 'FLGP336-B' in cell_str.upper():
                                                logger.info(
                                                    f"*** SCANNING: FLGP336-B qualifies for processing "
                                                    f"in sheet '{sheet_title}', row {row_idx + 1} ***")
                                            has_supplier_item = True
                                            break
                        if has_supplier_item:
                            break
                    
                    if has_supplier_item:
                        rows_to_process.add(row_idx)
                        if any('FLGP336-B' in str(df.iloc[row_idx, col_idx]).upper() 
                               for supplier, col_indices in supplier_columns.items() 
                               for col_idx in col_indices 
                               if col_idx < len(df.columns) and row_idx < len(df)):
                            logger.info(
                                f"*** SCANNING: Row {row_idx + 1} with FLGP336-B added to rows_to_process ***")
        
        # Process all identified rows
        for row_idx in sorted(rows_to_process):
            try:
                row = df.iloc[row_idx]
                actual_row = row_idx + 1  # 1-based row number

                # Extract MPI code and description from fixed columns (B, C, D)
                mpi_code = ""
                mpi_description = ""

                # Column B (index 1) - Item Code
                if len(row) > 1:
                    mpi_code = str(row.iloc[1]).strip()
                    if mpi_code.lower() in ['nan', 'none', '']:
                        mpi_code = ""
                    # Skip if it's a header value
                    elif mpi_code.lower() in ['item code', 'mpi code', 'description']:
                        logger.debug(f"Skipping header row {actual_row} with Column B = '{mpi_code}'")
                        continue

                # Column C (index 2) - Description
                if len(row) > 2:
                    mpi_description = str(row.iloc[2]).strip()
                    if mpi_description.lower() in ['nan', 'none', '']:
                        mpi_description = ""

                # Process each supplier column for this row
                # Extract items even if MPI code or description is missing
                for supplier, col_indices in supplier_columns.items():
                    for col_idx in col_indices:
                        if col_idx < len(row):
                            supplier_value = str(row.iloc[col_idx]).strip()

                            # Skip empty supplier values
                            if not supplier_value or supplier_value.lower() in ['nan', 'none', '']:
                                # Track rows that have MPI code but no supplier item
                                if mpi_code:
                                    self.extraction_stats["rows_without_supplier_items"] += 1
                                continue
                            
                            # If MPI code is missing, try to use supplier item as MPI code
                            # This helps extract items that don't have MPI codes in Column B
                            # BUT: We must validate that the supplier_value is suitable as an MPI code
                            if mpi_code:
                                effective_mpi_code = mpi_code
                            else:
                                # Only use supplier_value as MPI code if it passes MPI code validation
                                if self._is_valid_item_code(supplier_value):
                                    effective_mpi_code = supplier_value
                                else:
                                    # Skip this row - we can't create a valid mapping without a valid MPI code
                                    self.extraction_stats["skipped_invalid_items"] += 1
                                    logger.debug(
                                        f"Skipping row {actual_row} col {col_idx}: No valid MPI code in Column B, "
                                        f"and supplier value '{supplier_value}' is not a valid MPI code")
                                    continue

                            effective_description = mpi_description if mpi_description else f"Item: {supplier_value}"

                            # Special handling for Temporary columns (Original Item ONLY)
                            # Temporary mappings are items WITHOUT MPI codes yet - they only have supplier_item_ids and sheet_name
                            if supplier == "Temporary":
                                # Special logging for FLGP336-B
                                if 'FLGP336-B' in supplier_value.upper():
                                    logger.info(
                                        f"*** FOUND FLGP336-B in sheet '{sheet_title}', row {actual_row}, "
                                        f"column {col_idx + 1}, value: '{supplier_value}' ***")

                                # Skip header rows - check if this looks like a header
                                supplier_lower = supplier_value.lower().strip()
                                header_terms = [
                                    "original item", "original description", "total qty",
                                    "unit cost", "total amount", "item code", "mpi code",
                                    "description", "supplier"
                                ]
                                if supplier_lower in header_terms:
                                    if 'FLGP336-B' in supplier_value.upper():
                                        logger.warning(
                                            f"*** FLGP336-B was filtered as header in sheet '{sheet_title}', "
                                            f"row {actual_row}, column {col_idx + 1} ***")
                                    logger.debug(
                                        f"Skipping header row '{supplier_value}' in column {col_idx} (row {actual_row})")
                                    continue

                                # Validate this looks like an item code, not a price or description
                                # This prevents extracting values from wrong columns if they slip through
                                if not self._is_valid_item_code(supplier_value):
                                    logger.debug(
                                        f"Skipping invalid temporary item '{supplier_value}' - not a valid item code")
                                    continue

                                # For temporary mappings, we set mpi_code and description to None
                                # These are items that haven't been assigned an MPI code yet
                                # They only have: sheet_name (for categorization) and supplier_item_ids (the original item code)
                                mapping_data = {
                                    'sheet_title': sheet_title,
                                    'google_sheet_name': sheet_title,
                                    'sheet_id': sheet_id,  # Add sheet_id for tracking
                                    'mpi_code': None,  # NO MPI CODE for temporary mappings
                                    'description': None,  # NO DESCRIPTION for temporary mappings
                                    'supplier': 'Temporary',
                                    'supplier_id': None,  # No specific supplier ID for temporary
                                    'supplier_item_ids': supplier_value,  # The actual item code from "Original Item" column
                                    'original_supplier_item_id': supplier_value,
                                    'row_number': actual_row,
                                    'column_index': col_idx + 1,
                                    'extraction_timestamp': datetime.now().isoformat(),
                                    'mapping_type': 'temporary',
                                    'validation_status': 'valid_temporary'
                                }

                                logger.debug(
                                    f"Created temporary mapping for '{supplier_value}' in column {col_idx} (row {actual_row})")
                                extracted_items.append(mapping_data)
                                continue

                            # For regular supplier columns, validate that supplier_value is actually an item code
                            if not self._is_valid_item_code(supplier_value):
                                self.extraction_stats["skipped_invalid_items"] += 1
                                logger.debug(
                                    f"Skipping invalid item code '{supplier_value}' in column {col_idx} (row {actual_row})")
                                continue

                            # Get supplier ID and validate it exists in database
                            # Default to Unknown Supplier (ID 0)
                            supplier_id = self.supplier_ids.get(supplier, UNKNOWN_SUPPLIER_ID)

                            # Track Unknown supplier assignments
                            if supplier == UNKNOWN_SUPPLIER_NAME:
                                self.extraction_stats["unknown_supplier_items"] += 1
                            
                            # If supplier_id is None (e.g., Bruce, Ferguson), treat as temporary mapping
                            if supplier_id is None:
                                mapping_data = {
                                    'sheet_title': sheet_title,
                                    'google_sheet_name': sheet_title,
                                    'sheet_id': sheet_id,
                                    'mpi_code': effective_mpi_code,
                                    'description': effective_description,
                                    'supplier': supplier,
                                    'supplier_id': 0,  # No specific supplier ID for temporary
                                    'supplier_item_ids': supplier_value,
                                    'original_supplier_item_id': supplier_value,
                                    'row_number': actual_row,
                                    'column_index': col_idx + 1,
                                    'extraction_timestamp': datetime.now().isoformat(),
                                    'mapping_type': 'temporary',
                                    'validation_status': 'valid_temporary'
                                }
                                logger.debug(
                                    f"Created temporary mapping for '{supplier_value}' from {supplier} column (row {actual_row})")
                                extracted_items.append(mapping_data)
                                continue

                            # Log supplier mapping for debugging
                            logger.debug(
                                f"Mapping supplier '{supplier}' to ID {supplier_id} for item {supplier_value}")

                            # Create mapping entry with validated supplier_id
                            # Use effective values (may be derived from supplier item if MPI code/description missing)
                            mapping_data = {
                                'sheet_title': sheet_title,
                                'google_sheet_name': sheet_title,
                                'sheet_id': sheet_id,  # Add sheet_id for tracking
                                'mpi_code': effective_mpi_code,
                                'description': effective_description,
                                'supplier': supplier,
                                'supplier_id': supplier_id,
                                'supplier_item_ids': self._clean_supplier_item_id(supplier_value, supplier),
                                'original_supplier_item_id': supplier_value,
                                'row_number': actual_row,
                                'column_index': col_idx + 1,
                                'extraction_timestamp': datetime.now().isoformat()
                            }

                            # Log supplier mapping for debugging
                            logger.debug(
                                f"Mapping supplier '{supplier}' to ID {supplier_id} for item {supplier_value}")

                            # Validate and categorize the mapping
                            validated_mapping = self._validate_and_categorize_mapping(
                                mapping_data)
                            if validated_mapping:
                                extracted_items.append(validated_mapping)

            except Exception as e:
                logger.error(
                    f"Error processing row {row_idx + 1} in sheet {sheet_title}: {str(e)}")
                continue

        # Validation: Check if extraction rate is reasonable
        extraction_rate = (len(extracted_items) / total_valid_rows * 100) if total_valid_rows > 0 else 0
        
        # Count items by supplier and mapping type
        items_by_supplier = {}
        items_by_type = {"permanent": 0, "temporary": 0, "invalid": 0}
        
        for item in extracted_items:
            supplier = item.get("supplier", "Unknown")
            items_by_supplier[supplier] = items_by_supplier.get(supplier, 0) + 1
            mapping_type = item.get("mapping_type", "unknown")
            if mapping_type in items_by_type:
                items_by_type[mapping_type] += 1
        
        logger.info(
            f"Extraction complete for sheet '{sheet_title}': "
            f"{len(extracted_items)} total items from {total_valid_rows} valid rows "
            f"(extraction rate: {extraction_rate:.1f}%)")
        logger.info(
            f"  Breakdown: {items_by_type['permanent']} permanent, "
            f"{items_by_type['temporary']} temporary, {items_by_type['invalid']} invalid")
        
        # Log items per supplier
        for supplier, count in sorted(items_by_supplier.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  - {supplier}: {count} items")
        
        # Warning if extraction rate is suspiciously low
        if total_valid_rows > 0 and extraction_rate < 50:
            logger.warning(
                f"Low extraction rate ({extraction_rate:.1f}%) in sheet '{sheet_title}'. "
                f"Expected ~{total_valid_rows} items but only extracted {len(extracted_items)}. "
                f"Possible causes: 1) Many rows without supplier items, 2) Invalid item codes, "
                f"3) Supplier columns not detected properly. Manual review recommended.")
        
        # Log extraction statistics
        logger.info(
            f"Extraction statistics for '{sheet_title}': "
            f"skipped_invalid={self.extraction_stats.get('skipped_invalid_items', 0)}, "
            f"unknown_supplier={self.extraction_stats.get('unknown_supplier_items', 0)}, "
            f"rows_without_supplier={self.extraction_stats.get('rows_without_supplier_items', 0)}")
        
        return extracted_items

    def _clean_supplier_item_id(self, supplier_value: str, supplier: str) -> str:
        """
        With suffix standardization, we preserve the full item codes.
        This method is kept for backward compatibility but no longer removes suffixes.

        Args:
            supplier_value: Raw supplier item value
            supplier: Supplier name

        Returns:
            Item value with full suffixes preserved
        """
        # With suffix standardization, return the item as-is
        return supplier_value.strip()

    def _validate_and_categorize_mapping(self, mapping_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Validate and categorize a mapping as permanent, temporary, or invalid.

        Args:
            mapping_data: Raw mapping data

        Returns:
            Validated mapping with type information, or None if invalid
        """
        try:
            # Clean the mapping data
            cleaned_data = clean_mapping_data(mapping_data)

            # Check if this is a temporary mapping
            if is_temporary_mapping(cleaned_data.get("mpi_code"), cleaned_data.get("description"), cleaned_data.get("supplier")):
                # This is a temporary mapping
                return {
                    **cleaned_data,
                    "mapping_type": "temporary",
                    "validation_status": "valid_temporary"
                }

            # Validate for permanent storage
            is_valid, validation_errors = validate_mapping_for_permanent_storage(
                cleaned_data)

            if is_valid:
                # This is a valid permanent mapping
                return {
                    **cleaned_data,
                    "mapping_type": "permanent",
                    "validation_status": "valid_permanent"
                }
            else:
                # This is an invalid mapping
                logger.warning(
                    f"Invalid mapping detected: {cleaned_data.get('mpi_code')} - {validation_errors}"
                )
                return {
                    **cleaned_data,
                    "mapping_type": "invalid",
                    "validation_status": "invalid",
                    "validation_errors": validation_errors
                }

        except Exception as e:
            logger.error(f"Error validating mapping: {e}")
            # Return invalid mapping instead of None to ensure it's tracked
            return {
                **mapping_data,
                "mapping_type": "invalid",
                "validation_status": "error",
                "validation_errors": [f"Validation exception: {e!s}"]
            }

    def process_all_sheets(self) -> Dict[str, Any]:
        """
        Process all sheets in the Google Sheet with enhanced validation.

        Returns:
            Dictionary with extraction results and statistics
        """
        logger.info(f"Processing Google Sheet: {self.sheet_id}")

        # Sync sheet metadata BEFORE processing to ensure we have latest canonical names
        try:
            db = SessionLocal()
            try:
                sheet_manager = SheetNameManager(db, self.sheet_id, self.api_key)
                sync_result = sheet_manager.sync_sheet_metadata_from_google()
                logger.info(f"Sheet metadata sync result: {sync_result['message']}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to sync sheet metadata (proceeding anyway): {str(e)}")

        # Get list of sheets
        sheets = self.get_sheet_list()

        if not sheets:
            logger.warning("No sheets found")
            return {
                "success": False,
                "message": "No sheets found",
                "statistics": self.extraction_stats
            }

        logger.info(f"Found {len(sheets)} sheets")

        # Reset tracking variables
        self.all_items = []
        self.skipped_sheets = []
        self.empty_sheets = []
        self.extraction_stats = {
            "total_extracted": 0,
            "permanent_mappings": 0,
            "temporary_mappings": 0,
            "invalid_mappings": 0,
            "sheets_processed": 0,
            "skipped_invalid_items": 0,
            "unknown_supplier_items": 0,
            "rows_without_supplier_items": 0
        }

        # Process each sheet
        for sheet in sheets:
            try:
                sheet_items = self.process_sheet(
                    sheet_title=sheet['title'],
                    gid=sheet['gid']
                )
                self.all_items.extend(sheet_items)
                self.extraction_stats["sheets_processed"] += 1

                # Short pause to avoid overwhelming the API
                time.sleep(0.1)
            except Exception as e:
                logger.error(
                    f"Error processing sheet {sheet['title']}: {str(e)}")

        # Categorize items based on their mapping_type
        permanent_items = [item for item in self.all_items if item.get(
            "mapping_type") == "permanent"]
        temporary_items = [item for item in self.all_items if item.get(
            "mapping_type") == "temporary"]
        invalid_items = [item for item in self.all_items if item.get(
            "mapping_type") == "invalid"]

        # Update statistics based on actual extracted items
        self.extraction_stats["total_extracted"] = len(self.all_items)
        self.extraction_stats["permanent_mappings"] = len(
            [item for item in self.all_items if item.get("mapping_type") == "permanent"])
        self.extraction_stats["temporary_mappings"] = len(
            [item for item in self.all_items if item.get("mapping_type") == "temporary"])
        self.extraction_stats["invalid_mappings"] = len(invalid_items)

        # Save only mappings to output file (statistics are handled separately)
        output_data = {
            "permanent_mappings": permanent_items,
            "temporary_mappings": temporary_items,
            "invalid_mappings": invalid_items
        }

        # Validate JSON structure before saving
        self._validate_json_structure(output_data)

        # Save to file only if output_file is specified (optional for direct database loading)
        if self.output_file:
            try:
                with open(self.output_file, 'w', encoding='utf-8') as f:
                    json.dump(output_data, f, indent=2, ensure_ascii=False)

                # Verify file was written successfully
                file_size = os.path.getsize(self.output_file)
                logger.info(
                    f"JSON data saved successfully to {self.output_file} "
                    f"(file size: {file_size:,} bytes, "
                    f"{len(permanent_items)} permanent, "
                    f"{len(temporary_items)} temporary, "
                    f"{len(invalid_items)} invalid)")

                # Verify we can read it back
                with open(self.output_file, 'r', encoding='utf-8') as f:
                    verification_data = json.load(f)
                    if len(verification_data.get("permanent_mappings", [])) != len(permanent_items):
                        logger.error(
                            f"JSON verification failed: Expected {len(permanent_items)} permanent items, "
                            f"but file contains {len(verification_data.get('permanent_mappings', []))}")
                    else:
                        logger.info("JSON file verification passed")

            except Exception as e:
                logger.error(f"Error saving JSON file: {str(e)}", exc_info=True)
                raise
        else:
            logger.info("Skipping JSON file save (output_file not specified, data will be returned in memory)")

        # Final validation summary with comprehensive statistics
        logger.info("-" * 80)
        logger.info("EXTRACTION COMPLETE - DETAILED SUMMARY")
        logger.info("-" * 80)
        logger.info(f"Sheets processed: {self.extraction_stats['sheets_processed']}")
        logger.info(f"Total items extracted: {self.extraction_stats['total_extracted']}")
        logger.info(f"  - Permanent mappings: {self.extraction_stats['permanent_mappings']}")
        logger.info(f"  - Temporary mappings: {self.extraction_stats['temporary_mappings']}")
        logger.info(f"  - Invalid mappings: {self.extraction_stats['invalid_mappings']}")
        logger.info(f"")
        logger.info(f"Data Quality Metrics:")
        logger.info(f"  - Skipped invalid items: {self.extraction_stats['skipped_invalid_items']}")
        logger.info(f"  - Unknown supplier items: {self.extraction_stats['unknown_supplier_items']}")
        logger.info(f"  - Rows without supplier items: {self.extraction_stats['rows_without_supplier_items']}")
        logger.info(f"")
        logger.info(f"Output saved to: {self.output_file}")
        
        # Warning if no items extracted
        if self.extraction_stats['total_extracted'] == 0:
            logger.error(
                "CRITICAL: No items were extracted! "
                "This indicates a serious problem with the extraction process or spreadsheet format. "
                "Check: 1) Spreadsheet access, 2) Sheet format, 3) Supplier headers")
        
        # Warning if high invalid rate
        if self.extraction_stats['total_extracted'] > 0:
            invalid_rate = (self.extraction_stats['invalid_mappings'] / 
                          self.extraction_stats['total_extracted'] * 100)
            if invalid_rate > 10:
                logger.warning(
                    f"High invalid mapping rate ({invalid_rate:.1f}%). "
                    f"Manual review recommended to identify data quality issues.")
        
        # Warning if many Unknown supplier items
        if self.extraction_stats['unknown_supplier_items'] > 0:
            unknown_rate = (self.extraction_stats['unknown_supplier_items'] / 
                          self.extraction_stats['total_extracted'] * 100) if self.extraction_stats['total_extracted'] > 0 else 0
            logger.warning(
                f"{self.extraction_stats['unknown_supplier_items']} items ({unknown_rate:.1f}%) "
                f"assigned to Unknown supplier. Manual review recommended to identify correct suppliers.")
        
        # Warning if many skipped items
        if self.extraction_stats['skipped_invalid_items'] > 50:
            logger.warning(
                f"{self.extraction_stats['skipped_invalid_items']} items skipped due to validation failures. "
                f"Review item code validation rules if this seems excessive.")
        
        logger.info("-" * 80)

        # Log skipped and empty sheets
        if self.skipped_sheets:
            logger.info(
                f"Skipped {len(self.skipped_sheets)} sheets: {self.skipped_sheets}"
            )
        if self.empty_sheets:
            logger.info(
                f"Empty sheets: {len(self.empty_sheets)} sheets: {self.empty_sheets}"
            )

        return {
            "success": True,
            "message": "Extraction completed successfully",
            "statistics": self.extraction_stats,
            "permanent_mappings": permanent_items,
            "temporary_mappings": temporary_items,
            "invalid_mappings": invalid_items,
            "skipped_sheets": self.skipped_sheets,
            "empty_sheets": self.empty_sheets
        }

    def _find_all_valid_rows_in_column_b(self, df: pd.DataFrame, start_row: int) -> List[int]:
        """
        Find all valid rows in Column B (index 1) starting from a given row.
        This includes data clusters with gaps and data appearing after many empty rows.

        Args:
            df: Full DataFrame
            start_row: The row index to start searching from

        Returns:
            List of row indices (0-based) that contain valid data in Column B
        """
        valid_rows = []

        if len(df.columns) < 2:
            return valid_rows

        # Scan all rows from start_row to the end of the DataFrame
        for row_idx in range(start_row, len(df)):
            try:
                cell_value = df.iloc[row_idx, 1]  # Column B (index 1)

                # Check if the cell has valid data
                if pd.notna(cell_value) and str(cell_value).strip():
                    # Additional validation: skip header-like content
                    # Only skip if it's an EXACT match or the cell is ONLY header text
                    cell_str = str(cell_value).strip().lower()
                    header_terms = ["item code", "mpi code", "description", "size", "supplier"]

                    # Only skip if the entire cell is just a header term (not part of an item code)
                    # This prevents skipping valid items that contain header terms as part of their item codes
                    is_header = cell_str in header_terms or (
                        len(cell_str) < 15 and any(cell_str == term for term in header_terms)
                    )
                    
                    if not is_header:
                        valid_rows.append(row_idx)

            except (IndexError, KeyError):
                continue

        return valid_rows

    def _is_valid_item_code(self, item_code: str) -> bool:
        """
        Validate if a string is a valid item code.

        Args:
            item_code: The string to validate

        Returns:
            True if it's a valid item code, False otherwise
        """
        if not item_code or len(item_code.strip()) < 1:
            return False

        item_code = item_code.strip()

        # Skip if it's clearly a description (too long)
        if len(item_code) > 1000:
            return False

        # Skip if it's a dollar amount
        if item_code.startswith('$') or item_code.replace('.', '').replace(',', '').isdigit():
            return False

        # Skip if it's just a number (likely a quantity or price)
        # But allow single characters or very short codes if they have letters
        cleaned = item_code.replace('.', '').replace('-', '').replace('/', '').replace(' ', '')
        if cleaned.isdigit():
            return False
        
        # Additional check: if it's a single digit, reject it
        if len(item_code) == 1 and item_code.isdigit():
            return False

        # Skip common non-item patterns
        # Note: Check for exact matches or standalone words, not substrings
        # This prevents rejecting valid item codes that contain these terms as part of the code
        invalid_patterns = [
            'none', 'n/a', 'tbd', 'pending', 'unknown',
            'item', 'code', 'description', 'quantity', 'price', 'amount',
            'total', 'subtotal', 'tax', 'shipping'
        ]
        
        # Only reject if the entire item code is exactly "nan" (case-insensitive)
        # Allow item codes that contain "nan" as part of the code
        if item_code.lower().strip() == 'nan':
            return False

        item_lower = item_code.lower()
        # Check if any invalid pattern appears as a whole word or exact match
        for pattern in invalid_patterns:
            # Use word boundaries to avoid false positives
            if re.search(r'\b' + re.escape(pattern) + r'\b', item_lower):
                # But allow if it's part of a longer code where the pattern appears within a valid item code
                # Only reject if pattern is the entire code or a significant portion
                if len(pattern) >= len(item_code) * 0.8:  # Pattern is 80%+ of the code
                    return False

        # Valid item codes should contain alphanumeric characters and common item code symbols
        # Allow spaces in item codes
        # Added: =, (, ), #, %, + to support item codes with equations, dimensions, percentages, and special characters
        # Added: &, " to support item codes with ampersands and quotation marks in measurements
        # Using regex a compiled regex provides a more efficient scan
        return bool(ITEM_CODE_PATTERN.match(item_code))


    def _validate_json_structure(self, output_data: Dict[str, Any]) -> None:
        """
        Validate the JSON structure before saving to ensure compatibility.

        Args:
            output_data: The data structure to validate
        """
        try:
            required_keys = ["permanent_mappings",
                             "temporary_mappings", "invalid_mappings"]

            # Check required keys
            for key in required_keys:
                if key not in output_data:
                    raise ValueError(
                        f"Missing required key in JSON structure: {key}")

            # Validate mapping structures
            for mapping_list in ["permanent_mappings", "temporary_mappings", "invalid_mappings"]:
                if not isinstance(output_data[mapping_list], list):
                    raise ValueError(f"{mapping_list} must be a list")

                # Validate each mapping has required fields
                for i, mapping in enumerate(output_data[mapping_list]):
                    if not isinstance(mapping, dict):
                        raise ValueError(
                            f"Mapping {i} in {mapping_list} must be a dictionary")

                    # Check for required fields in permanent mappings
                    if mapping_list == "permanent_mappings":
                        required_fields = [
                            "mpi_code", "description", "supplier_item_ids", "supplier_id", "google_sheet_name"]
                        for field in required_fields:
                            if field not in mapping:
                                logger.warning(
                                    f"Missing field '{field}' in permanent mapping {i}")

            logger.info("JSON structure validation passed")

        except Exception as e:
            logger.error(f"JSON structure validation failed: {str(e)}")
            raise


def extract_all_data_enhanced():
    """Extract all data from the Google Sheet using enhanced extractor."""
    extractor = EnhancedGoogleSheetDataExtractor()
    return extractor.process_all_sheets()
