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
from mpi_backend.utils.mapping_stats_manager import MappingStatsManager
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

# Set up logging
logger = logging.getLogger(__name__)

# Import spreadsheet configuration

# Import validation utilities


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
            "sheets_processed": 0
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
        self.output_file = output_file or os.environ.get(
            "MAPPING_OUTPUT_FILE",
            DEFAULT_OUTPUT_FILE
        )

        # Set batch size for processing
        self.batch_size = batch_size

        # Set default skip_sheets if None is provided
        self.skip_sheets = skip_sheets or [
            "(AB, ALL SYSTEMS)",
            "(AC, ITEMS WITHOUT TEMPORARY GROUP NAME)"
        ]

        # Set fuzzy matching threshold
        self.fuzzy_threshold = fuzzy_threshold

    def _setup_supplier_mapping(self):
        """Set up supplier mappings and extract key terms for matching."""
        # Define suppliers with their IDs and base names for matching
        # Updated to match actual database IDs from backup
        self.supplier_mapping = {
            "BMW Plumbing Supplies": {"id": 1},
            "World Wide Plumbing": {"id": 2},
            "Y & S Plumbing Supply": {"id": 3},
            "Supreme Plumbing Supply": {"id": 4},
            "Pyramid Plumbing": {"id": 5},
            "ABC Opus Services": {"id": 6},
            "Park Plumbing Supply": {"id": 7},
            "Gotham Plumbing Supply": {"id": 8},
            "FW Webb Plumbing Supply": {"id": 9},
            "Flow Mark Plumbing Supply": {"id": 10},
            "Plumbing Exchange": {"id": 11},  # Corrected from 14
            "AF Supply": {"id": 12},          # Corrected from 15
            "Lion Hvac Supplies": {"id": 13},  # Corrected from 16
            "Bruce": {"id": 14},              # Bruce supplier (B suffix)
            "Ferguson": {"id": 15},           # Ferguson supplier (F suffix)
            # Use a valid supplier ID for unknown suppliers instead of 999
            # Default to BMW Plumbing Supplies for unknown
            "Unknown": {"id": 1}
        }

        # Extract key terms from each supplier name for matching
        self._extract_key_terms()

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
                "world", "wide", "wwp", "wwps", "worldwide", "WWPS 1", "WWPS 2", "WWPS 3", "WWPS 4", "WWPS 5"
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
                "flow", "flowmark", "flowmarksupply", "Flow Mark 1", "FlowMark 1", "FlowMark 2", "Flow Mark 2", "flow 1", "flow 2", "flow 3",
            ])

        elif "AF Supply" in supplier:
            info["key_terms"].extend([
                "af", "supply", "afsupply", "AF Supply"
            ])

        elif "Ferguson" in supplier:
            info["key_terms"].extend([
                "ferguson", "Ferguson 1", "Ferguson 2", "Ferguson 3", "Ferguson 4", "Ferguson 5"
            ])
        elif "Bruce" in supplier:
            info["key_terms"].extend([
                "bruce", "Bruce 1", "Bruce 2", "Bruce 3", "Bruce 4", "Bruce 5"
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
            return "Unknown", 0, 0

        col_name_str = str(col_name).strip()
        if not col_name_str:
            return "Unknown", 0, 0

        col_name_lower = col_name_str.lower()
        best_match = None
        best_score = 0

        # Try exact matches first
        for supplier, info in self.supplier_mapping.items():
            if col_name_lower == supplier.lower():
                return supplier, self.supplier_ids[supplier], 100.0

        # Enhanced fuzzy matching for common patterns like "BMW 1", "WWPS 2", etc.
        import re
        base_name_match = re.match(r'^([A-Za-z&]+)\s*\d*$', col_name_str)
        if base_name_match:
            base_name = base_name_match.group(1).strip()
            for supplier, info in self.supplier_mapping.items():
                # Check if base name matches supplier name or codes
                supplier_base = re.sub(r'\s+', '', supplier.upper())
                base_upper = re.sub(r'\s+', '', base_name.upper())

                if supplier_base.startswith(base_upper) or base_upper.startswith(supplier_base):
                    return supplier, self.supplier_ids[supplier], 95.0

        # Try fuzzy matching with key terms
        for supplier, info in self.supplier_mapping.items():
            for term in info["key_terms"]:
                score = fuzz.ratio(col_name_lower, term.lower())
                if score > best_score and score >= self.fuzzy_threshold:
                    best_score = score
                    best_match = supplier

        # Additional check: if no match found, try partial matching
        if not best_match:
            for supplier, info in self.supplier_mapping.items():
                supplier_lower = supplier.lower()
                if col_name_lower in supplier_lower or supplier_lower in col_name_lower:
                    return supplier, self.supplier_ids[supplier], 85.0

        if best_match:
            return best_match, self.supplier_ids[best_match], best_score
        else:
            return "Unknown", 1, 0  # Return ID 1 for Unknown instead of 0

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
        for col_idx in range(4, len(df_full.columns)):
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

                if row1_empty and row2_empty:
                    # Check if Row 3 contains header-like content to confirm this is NOT a supplier column
                    if len(df_full) > 2:
                        row3_value = df_full.iloc[2, col_idx] if col_idx < len(
                            df_full.columns) else None
                        row3_str = str(row3_value).strip(
                        ).lower() if pd.notna(row3_value) else ""

                        # Special handling for "Original Item" - automatically detect next 4 columns as temporary mappings
                        if "original item" in row3_str:
                            logger.info(
                                f"Found 'Original Item' header at column {col_idx}, automatically detecting next 4 columns as temporary mappings")

                            # Automatically add the next 4 columns as temporary mappings
                            temp_mapping_columns = [
                                "Original Item", "Original Description", "Total Qty", "Unit Cost", "Total Amount"]

                            for i, header_name in enumerate(temp_mapping_columns):
                                temp_col_idx = col_idx + i
                                if temp_col_idx < len(df_full.columns):
                                    if "Temporary" not in supplier_columns:
                                        supplier_columns["Temporary"] = []
                                    supplier_columns["Temporary"].append(
                                        temp_col_idx)
                                    logger.info(
                                        f"Added temporary mapping column {temp_col_idx} as '{header_name}'")

                            # Skip the next 4 columns since we've already processed them
                            col_idx += 4
                            continue

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
                    # Extended range to scan deeper into columns to catch items like FLUX9-F
                    has_valid_data = False
                    # Check rows 4-20 (extended from 4-10)
                    for row_idx in range(3, min(20, len(df_full))):
                        if row_idx < len(df_full) and col_idx < len(df_full.columns):
                            cell_value = df_full.iloc[row_idx, col_idx]
                            if pd.notna(cell_value) and str(cell_value).strip():
                                # Check if it looks like a valid item code (not empty, not header-like)
                                cell_str = str(cell_value).strip()
                                header_terms = [
                                    "item code", "mpi", "code", "item", "description",
                                    "size", "supplier"
                                ]
                                if (len(cell_str) >= 2 and
                                    not any(term in cell_str.lower() for term in
                                            header_terms)):
                                    has_valid_data = True
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
                                f"Column {col_idx} detected as {detected_supplier} based on item patterns")
                        else:
                            # Assign to "Unknown" supplier to ensure these items are extracted
                            supplier_identifier = f"Unknown_{col_idx}"
                            logger.info(
                                f"Column {col_idx} has valid item data but no supplier identifier, assigning to Unknown supplier")

                if not supplier_identifier:
                    logger.debug(
                        f"Column {col_idx} has no valid supplier identifier in Row 1 or Row 2, skipping")
                    continue

                # Step 6: Fuzzy match to SUPPLIER_MAPPING
                logger.debug(
                    f"Attempting to match supplier identifier: '{supplier_identifier}' for column {col_idx}")
                supplier_name, supplier_id, confidence = self.match_supplier(
                    supplier_identifier)

                if confidence >= self.fuzzy_threshold and supplier_id > 0:
                    if supplier_name not in supplier_columns:
                        supplier_columns[supplier_name] = []
                    supplier_columns[supplier_name].append(col_idx)

                    logger.info(
                        f"Detected supplier column {col_idx}: '{supplier_identifier}' -> {supplier_name} "
                        f"(confidence: {confidence})"
                    )
                elif supplier_identifier.startswith("Unknown_"):
                    # Handle unknown supplier columns
                    supplier_name = "Unknown"
                    # Use BMW Plumbing Supplies (ID 1) for unknown suppliers
                    supplier_id = 1
                    if supplier_name not in supplier_columns:
                        supplier_columns[supplier_name] = []
                    supplier_columns[supplier_name].append(col_idx)

                    logger.info(
                        f"Detected unknown supplier column {col_idx}: '{supplier_identifier}' -> {supplier_name}"
                    )
                else:
                    logger.warning(
                        f"No supplier match found for column {col_idx}: '{supplier_identifier}' "
                        f"(confidence: {confidence})"
                    )

            except Exception as e:
                logger.error(f"Error processing column {col_idx}: {str(e)}")
                continue

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
        supplier_patterns = {
            "BMW Plumbing Supplies": ["-B", "bmw"],
            "World Wide Plumbing": ["-W", "wwp", "worldwide"],
            "Y & S Plumbing Supply": ["-Y", "y&s", "ys"],
            "Supreme Plumbing Supply": ["-S", "supreme"],
            "Pyramid Plumbing": ["-P", "pyramid"],
            "ABC Opus Services": ["-A", "abc", "opus"],
            "Park Plumbing Supply": ["-P", "park"],  # Corrected to -P
            "Gotham Plumbing Supply": ["-G", "gotham"],
            "FW Webb Plumbing Supply": ["-F", "fw", "webb"],
            "Flow Mark Plumbing Supply": ["-FM", "flowmark", "flow mark"],
            "Plumbing Exchange": ["-PE", "pex", "plumbing exchange"],
            "AF Supply": ["-AF", "af supply"],
            "Lion Hvac Supplies": ["-L", "lion", "hvac"],
            "Bruce": ["-BF", "bruce"],
            "Ferguson": ["-F", "ferguson"]
        }

        # Scan column for item patterns
        for row_idx in range(3, min(20, len(df_full))):
            if row_idx < len(df_full) and col_idx < len(df_full.columns):
                cell_value = df_full.iloc[row_idx, col_idx]
                if pd.notna(cell_value):
                    cell_str = str(cell_value).strip()
                    if len(cell_str) >= 2:
                        # Check each supplier pattern
                        for supplier, patterns in supplier_patterns.items():
                            for pattern in patterns:
                                if (pattern.lower() in cell_str.lower() or
                                        cell_str.lower().endswith(pattern.lower())):
                                    logger.debug(
                                        f"Found pattern '{pattern}' in '{cell_str}' "
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
            gid: Google Sheet ID

        Returns:
            List of extracted mappings
        """
        try:
            # Skip sheets that are in the skip list
            if any(skip_name in sheet_title for skip_name in self.skip_sheets):
                self.skipped_sheets.append(sheet_title)
                logger.debug(f"Skipping sheet: {sheet_title}")
                return []

            # Get sheet data
            df = self._get_sheet_dataframe(gid)

            if df is None or df.empty:
                self.empty_sheets.append(sheet_title)
                logger.debug(f"Sheet is empty: {sheet_title}")
                return []

            # Detect supplier columns
            supplier_columns = self.detect_supplier_columns(
                df.head(), df, sheet_title)

            # Log detected supplier columns
            if supplier_columns:
                logger.info(
                    f"Detected {len(supplier_columns)} supplier(s) in sheet {sheet_title}:")
                for supplier, columns in supplier_columns.items():
                    logger.info(f"  - {supplier}: columns {columns}")
            else:
                logger.warning(
                    f"No supplier columns detected in sheet: {sheet_title}")
                logger.debug(
                    f"Sheet {sheet_title} has {len(df.columns)} columns and {len(df)} rows")
                # Log first few rows to help debug
                for i in range(min(5, len(df))):
                    # First 10 columns
                    logger.debug(f"Row {i+1}: {df.iloc[i].tolist()[:10]}")
                return []

            # Process the sheet data for mapped items (start from Row 4, index 3)
            extracted_items = self._process_dataframe_chunk(
                df, supplier_columns, sheet_title, 3
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
        start_row: int
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
            sheet_title: Name of the sheet
            start_row: Starting row index (should be 3 for Row 4)

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

        # Step 3: Process each valid row in Column B
        # This ensures we only process rows that have Item Code data
        for row_idx in all_valid_rows_in_column_b:
            try:
                row = df.iloc[row_idx]
                actual_row = row_idx + 1  # 1-based row number

                # Extract MPI code and description from fixed columns (B, C, D)
                mpi_code = ""
                mpi_description = ""

                # Column B (index 1) - Item Code
                if len(row) > 1:
                    mpi_code = str(row.iloc[1]).strip()

                # Column C (index 2) - Description
                if len(row) > 2:
                    mpi_description = str(row.iloc[2]).strip()

                # Skip if no MPI code or no description
                if not mpi_code or mpi_code.lower() in ['nan', 'none', '']:
                    continue

                # Skip if no description or description is empty
                if not mpi_description or mpi_description.lower() in ['nan', 'none', '']:
                    continue

                # Process each supplier column for this row
                for supplier, col_indices in supplier_columns.items():
                    for col_idx in col_indices:
                        if col_idx < len(row):
                            supplier_value = str(row.iloc[col_idx]).strip()

                            # Skip empty supplier values
                            if not supplier_value or supplier_value.lower() in ['nan', 'none', '']:
                                continue

                            # Special handling for Temporary columns (Original Item, Original Description, etc.)
                            if supplier == "Temporary":
                                # For temporary columns, we don't validate as item codes
                                # These are temporary mappings that should go to temporary storage
                                mapping_data = {
                                    'sheet_title': sheet_title,
                                    'google_sheet_name': sheet_title,
                                    'mpi_code': mpi_code,
                                    'description': mpi_description,
                                    'supplier': 'Temporary',
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
                                    f"Created temporary mapping for '{supplier_value}' in column {col_idx} (row {actual_row})")
                                extracted_items.append(mapping_data)
                                continue

                            # For regular supplier columns, validate that supplier_value is actually an item code
                            if not self._is_valid_item_code(supplier_value):
                                logger.debug(
                                    f"Skipping invalid item code '{supplier_value}' in column {col_idx} (row {actual_row})")
                                continue

                            # Get supplier ID and validate it exists in database
                            # Default to BMW Plumbing Supplies (ID 1)
                            supplier_id = self.supplier_ids.get(supplier, 1)

                            # Log supplier mapping for debugging
                            logger.debug(
                                f"Mapping supplier '{supplier}' to ID {supplier_id} for item {supplier_value}")

                            # Create mapping entry with validated supplier_id
                            mapping_data = {
                                'sheet_title': sheet_title,
                                'google_sheet_name': sheet_title,
                                'mpi_code': mpi_code,
                                'description': mpi_description,
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

        logger.info(
            f"Successfully extracted {len(extracted_items)} mappings from {total_valid_rows} valid rows in sheet {sheet_title}")
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
            return None

    def process_all_sheets(self) -> Dict[str, Any]:
        """
        Process all sheets in the Google Sheet with enhanced validation.

        Returns:
            Dictionary with extraction results and statistics
        """
        logger.info(f"Processing Google Sheet: {self.sheet_id}")

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
            "sheets_processed": 0
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

        # Save to file with proper formatting and UTF-8 encoding for Windows compatibility
        try:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            logger.info(f"JSON data saved successfully to {self.output_file}")
        except Exception as e:
            logger.error(f"Error saving JSON file: {str(e)}")
            raise

        # Update statistics in the separate stats file
        try:
            stats_manager = MappingStatsManager()
            stats_manager.update_item_mapping_stats({
                "total_mappings": self.extraction_stats["total_extracted"],
                "permanent_mappings": self.extraction_stats["permanent_mappings"],
                "temporary_mappings": self.extraction_stats["temporary_mappings"],
                "invalid_mappings": self.extraction_stats["invalid_mappings"],
                "sheets_processed": self.extraction_stats["sheets_processed"]
            })
            stats_manager.update_sync_times("item_sync")
            logger.info("Updated mapping statistics in stats file")
        except Exception as e:
            logger.error(f"Error updating stats file: {str(e)}")
            # Don't raise here as the main operation succeeded

        logger.info(
            f"Extraction complete. Processed {self.extraction_stats['sheets_processed']} sheets, "
            f"extracted {self.extraction_stats['total_extracted']} items. "
            f"Permanent: {self.extraction_stats['permanent_mappings']}, "
            f"Temporary: {self.extraction_stats['temporary_mappings']}, "
            f"Invalid: {self.extraction_stats['invalid_mappings']}. "
            f"Output saved to {self.output_file}"
        )

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
                    cell_str = str(cell_value).strip().lower()
                    header_terms = ["item code", "mpi", "code",
                                    "item", "description", "size", "supplier"]

                    if not any(term in cell_str for term in header_terms):
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
        if not item_code or len(item_code.strip()) < 2:
            return False

        item_code = item_code.strip()

        # Skip if it's clearly a description (too long, contains spaces)
        if len(item_code) > 20 or ' ' in item_code:
            return False

        # Skip if it's a dollar amount
        if item_code.startswith('$') or item_code.replace('.', '').replace(',', '').isdigit():
            return False

        # Skip if it's just a number (likely a quantity or price)
        if item_code.replace('.', '').replace('-', '').replace('/', '').isdigit():
            return False

        # Skip common non-item patterns
        invalid_patterns = [
            'nan', 'none', 'n/a', 'tbd', 'pending', 'unknown',
            'item', 'code', 'description', 'quantity', 'price', 'amount',
            'total', 'subtotal', 'tax', 'shipping', 'discount'
        ]

        item_lower = item_code.lower()
        for pattern in invalid_patterns:
            if pattern in item_lower:
                return False

        # Valid item codes should contain alphanumeric characters and common item code symbols
        valid_chars = set(
            'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-./_')
        if not all(c in valid_chars for c in item_code):
            return False

        return True

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
