#!/usr/bin/env python3
"""
Enhanced Google Sheet Data Extractor - Fixed version with proper temporary/permanent mapping handling.

This module provides enhanced functionality to extract and process data from Google Sheets,
with proper validation and categorization of temporary vs permanent mappings.
"""

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

# Set up logging
logger = logging.getLogger(__name__)

# Import spreadsheet configuration
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID,
    GOOGLE_API_KEY,
    DEFAULT_OUTPUT_FILE
)

# Import validation utilities
from mpi_backend.utils.mapping_validators import (
    is_temporary_mapping,
    validate_mapping_for_permanent_storage,
    should_use_temporary_storage,
    clean_mapping_data
)


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
            "temporary_items": 0,
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
        # Updated to match actual database IDs
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
            "Plumbing Exchange": {"id": 14},  # Updated from 11
            "AF Supply": {"id": 15},          # Updated from 12
            "Lion Hvac Supplies": {"id": 16}, # Updated from 13
            "Bruce Ferguson": {"id": 17},     # Updated from 14
            "Unknown": {"id": 999}            # Special ID for unknown suppliers
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
            info["key_terms"].extend(["bmw", "plumbing", "supplies"])
        elif "World Wide" in supplier:
            info["key_terms"].extend(["world", "wide", "wwp"])
        elif "Y & S" in supplier:
            info["key_terms"].extend(["y&s", "ys", "plumbing", "supply"])

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
        
        if best_match:
            return best_match, self.supplier_ids[best_match], best_score
        else:
            return "Unknown", 0, 0

    def detect_supplier_columns(
        self, 
        df_head: pd.DataFrame,
        df_full: pd.DataFrame
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
        
        # Step 1: Determine number of rows to process using Column B (index 1)
        total_valid_rows = self._count_valid_rows_in_column_b(df_full)
        if total_valid_rows == 0:
            logger.warning("Column B has no valid rows, skipping sheet")
            return supplier_columns
        
        logger.info(f"Column B has {total_valid_rows} valid rows to process")
        
        # Step 2: Start scanning from Column E (index 4) onward
        for col_idx in range(4, len(df_full.columns)):
            try:
                # Step 3: Column Validation - Check Row 1 and Row 2
                row1_value = df_full.iloc[0, col_idx] if col_idx < len(df_full.columns) else None
                row2_value = df_full.iloc[1, col_idx] if col_idx < len(df_full.columns) else None
                
                # Check if both Row 1 and Row 2 are empty (potential temporary items block)
                row1_empty = pd.isna(row1_value) or str(row1_value).strip() == ""
                row2_empty = pd.isna(row2_value) or str(row2_value).strip() == ""
                
                if row1_empty and row2_empty:
                    # Check if Row 3 contains "Original Item" header to confirm this is the temporary items block
                    if len(df_full) > 2:
                        row3_value = df_full.iloc[2, col_idx] if col_idx < len(df_full.columns) else None
                        row3_str = str(row3_value).strip().lower() if pd.notna(row3_value) else ""
                        
                        if "original item" in row3_str:
                            logger.info(f"Found temporary items block at column {col_idx} (confirmed by 'Original Item' header), stopping supplier column detection")
                            break  # Early exit - confirmed temporary items block
                        else:
                            logger.debug(f"Column {col_idx} has empty Row 1 & 2 but no 'Original Item' header, continuing to scan")
                    else:
                        logger.debug(f"Column {col_idx} has empty Row 1 & 2 but not enough rows to check header, continuing to scan")
                
                # Step 4: Use single row for supplier identifier (Row 1 if available, otherwise Row 2)
                supplier_identifier = self._get_single_row_supplier_identifier(row1_value, row2_value)
                
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
                        # Assign to "Unknown" supplier to ensure these items are extracted
                        supplier_identifier = f"Unknown_{col_idx}"
                        logger.info(f"Column {col_idx} has valid item data but no supplier identifier, assigning to Unknown supplier")
                
                if not supplier_identifier:
                    logger.debug(f"Column {col_idx} has no valid supplier identifier in Row 1 or Row 2, skipping")
                    continue
                
                # Step 6: Fuzzy match to SUPPLIER_MAPPING
                supplier_name, supplier_id, confidence = self.match_supplier(supplier_identifier)
                
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
                    supplier_id = 999  # Use a special ID for unknown suppliers
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

    def _count_valid_rows_in_column_b(self, df: pd.DataFrame) -> int:
        """
        Count all non-empty rows in Column B (index 1) from Row 4 down.
        
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
        
        Args:
            row1_value: Value from Row 1
            row2_value: Value from Row 2
            
        Returns:
            Supplier identifier string from the best available row
        """
        row1_str = str(row1_value).strip() if pd.notna(row1_value) else ""
        row2_str = str(row2_value).strip() if pd.notna(row2_value) else ""
        
        # If Row 1 has data, use it
        if row1_str:
            return row1_str
        
        # If Row 1 is empty but Row 2 has data, use Row 2
        if not row1_str and row2_str:
            return row2_str
        
        # If both are empty, return empty (column will be skipped)
        return ""

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
            supplier_columns = self.detect_supplier_columns(df.head(), df)
            
            if not supplier_columns:
                logger.debug(f"No supplier columns detected in sheet: {sheet_title}")
                return []
            
            # Process the sheet data for mapped items (start from Row 4, index 3)
            extracted_items = self._process_dataframe_chunk(
                df, supplier_columns, sheet_title, 3
            )
            
            # Extract temporary items
            temporary_items = self.extract_temporary_items(df, sheet_title)
            
            # Update statistics for temporary items
            self.extraction_stats["temporary_items"] += len(temporary_items)
            
            # Combine both types of items
            all_items = extracted_items + temporary_items
            
            logger.info(
                f"Extracted {len(extracted_items)} mapped items and {len(temporary_items)} temporary items "
                f"from sheet: {sheet_title}"
            )
            
            return all_items
            
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
                logger.error(f"Failed to get sheet data: {response.status_code}")
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
        Process a chunk of DataFrame data and extract mappings using Zero Skipped Items Approach.
        
        Args:
            df: DataFrame to process
            supplier_columns: Dictionary mapping suppliers to column indices
            sheet_title: Name of the sheet
            start_row: Starting row index (should be 3 for Row 4)
            
        Returns:
            List of extracted mappings
        """
        extracted_items = []
        
        # Determine the total number of rows to process using Column B
        total_valid_rows = self._count_valid_rows_in_column_b(df)
        if total_valid_rows == 0:
            logger.warning(f"No valid rows found in Column B for sheet {sheet_title}")
            return extracted_items
        
        # Calculate the end row (Row 4 + total_valid_rows)
        end_row = min(start_row + total_valid_rows, len(df))
        
        logger.info(f"Processing rows {start_row + 1} to {end_row} for sheet {sheet_title}")
        
        # Process each row from Row 4 to the calculated end
        for row_idx in range(start_row, end_row):
            try:
                row = df.iloc[row_idx]
                actual_row = row_idx + 1  # 1-based row number
                
                # Extract MPI code and description from fixed columns (B, C, D)
                mpi_code = ""
                description = ""
                size = ""
                item_code = ""  # Add item_code field
                
                # Fixed column mapping: B=1, C=2, D=3 (0-based indexing)
                # Column B (index 1) = mpi_code or item_code
                if len(row) > 1:
                    mpi_code_val = row.iloc[1]
                    if not pd.isna(mpi_code_val):
                        mpi_code = str(mpi_code_val).strip()
                        item_code = mpi_code  # Store as item_code as well
                
                # Column C (index 2) = description
                if len(row) > 2:
                    desc_val = row.iloc[2]
                    if not pd.isna(desc_val):
                        description = str(desc_val).strip()
                
                # Column D (index 3) = size
                if len(row) > 3:
                    size_val = row.iloc[3]
                    if not pd.isna(size_val):
                        size = str(size_val).strip()
                
                # Fallback: If no MPI code in column B, check column A (index 0)
                if not mpi_code and len(row) > 0:
                    mpi_code_val = row.iloc[0]
                    if not pd.isna(mpi_code_val):
                        mpi_code_str = str(mpi_code_val).strip()
                        # Check if this looks like an MPI code
                        if (mpi_code_str and len(mpi_code_str) > 2 and 
                            not mpi_code_str.lower() in ['item code', 'mpi', 'code', 'item', 'description']):
                            mpi_code = mpi_code_str
                            item_code = mpi_code_str
                            
                            # Shift description and size columns
                            if len(row) > 1:
                                desc_val = row.iloc[1]
                                if not pd.isna(desc_val):
                                    description = str(desc_val).strip()
                            if len(row) > 2:
                                size_val = row.iloc[2]
                                if not pd.isna(size_val):
                                    size = str(size_val).strip()
                
                # Modified logic: Don't skip rows with empty MPI code if there's a valid item_code and description
                # This handles cases like FLUX9-F where MPI code is empty but item_code and description exist
                if not mpi_code and not item_code:
                    logger.debug(f"Skipping row {actual_row} - no MPI code or item code found")
                    continue
                    
                # Skip header rows
                header_terms = ["item code", "mpi", "code", "item", "description", "size", "supplier"]
                mpi_lower = mpi_code.lower() if mpi_code else ""
                
                if any(term in mpi_lower for term in header_terms) or (
                    description and any(
                        term in description.lower() for term in header_terms
                    )
                ):
                    logger.debug(f"Skipping header row {actual_row}: {mpi_code}")
                    continue
                
                # Create a combined description with size
                combined_description = description or ""
                if size:
                    combined_description = f"{size} {combined_description}"
                combined_description = combined_description.strip()
                
                # Process supplier columns for this row
                for supplier, col_indices in supplier_columns.items():
                    for col_idx in col_indices:
                        if col_idx >= len(row):
                            continue
                            
                        cell_value = row.iloc[col_idx]
                        
                        if pd.isna(cell_value):
                            continue
                        
                        # Convert to string and clean
                        supplier_value = str(cell_value).strip()
                        
                        # Skip empty cells
                        if not supplier_value:
                            continue
                        
                        # Skip cells that are just whitespace or special characters
                        if not re.search(r'[A-Za-z0-9]', supplier_value):
                            continue
                        
                        # With suffix standardization, we preserve the full item codes
                        # No suffix cleaning needed - items are stored with full suffixes
                        cleaned_value = supplier_value.strip()
                        
                        # Skip if cleaned value is empty
                        if not cleaned_value:
                            continue
                        
                        # Skip if the supplier ID field contains header-like text
                        if any(term in cleaned_value.lower() for term in 
                              ["supplier", "item", "id", "code", "description"]):
                            continue
                        
                        # Additional validation: Skip values that are too short
                        if len(cleaned_value) < 2:
                            continue
                        
                        # Get the original column name
                        supplier_column_name = str(df.columns[col_idx]) if col_idx < len(df.columns) else f"Column_{col_idx}"
                        
                        # Extract clean sheet name for classification
                        clean_sheet_name = self._extract_clean_sheet_name(sheet_title)
                        
                        # Create item mapping with enhanced data
                        # Handle case where MPI code is empty but item_code exists
                        effective_mpi_code = mpi_code if mpi_code else item_code
                        
                        item_mapping = {
                            "mpi_code": effective_mpi_code,
                            "description": combined_description,
                            "size": size if size else "",
                            "supplier_name": supplier,
                            "supplier_id": self.supplier_ids[supplier],
                            "supplier_item_ids": cleaned_value,  # Use plural form for consistency
                            "google_sheet_name": clean_sheet_name,
                            "row_index": actual_row,
                            "supplier_column_name": supplier_column_name,
                            "original_supplier_value": supplier_value
                        }
                        
                        # Validate and categorize the mapping
                        validated_mapping = self._validate_and_categorize_mapping(item_mapping)
                        
                        if validated_mapping:
                            extracted_items.append(validated_mapping)
                            
                            # Update statistics
                            self.extraction_stats["total_extracted"] += 1
                            if validated_mapping.get("mapping_type") == "permanent":
                                self.extraction_stats["permanent_mappings"] += 1
                            elif validated_mapping.get("mapping_type") == "temporary":
                                self.extraction_stats["temporary_mappings"] += 1
                            else:
                                self.extraction_stats["invalid_mappings"] += 1
                        
                        logger.debug(
                            f"Extracted mapping: MPI={mpi_code}, Supplier={supplier}, "
                            f"Original={supplier_value}, Cleaned={cleaned_value}, "
                            f"Type={validated_mapping.get('mapping_type', 'unknown') if validated_mapping else 'invalid'}"
                        )
            
            except Exception as e:
                logger.error(f"Error processing row {row_idx} in sheet {sheet_title}: {str(e)}")
                continue
        
        return extracted_items

    def extract_temporary_items(self, df: pd.DataFrame, sheet_title: str) -> List[Dict[str, Any]]:
        """
        Extract temporary items from the "Original Item" block.
        
        Args:
            df: DataFrame containing the sheet data
            sheet_title: Name of the sheet
            
        Returns:
            List of extracted temporary items
        """
        temporary_items = []
        
        # Enhanced temporary item block detection - More flexible approach
        # Look for "Original Item" header in any of the first few rows
        temp_block_start_col = None
        temp_block_header_row = None
        
        # Scan all columns and first few rows for "Original Item" header
        for col_idx in range(len(df.columns)):
            for row_idx in range(min(5, len(df))):  # Check first 5 rows
                try:
                    cell_value = df.iloc[row_idx, col_idx] if col_idx < len(df.columns) else None
                    if cell_value is not None:
                        cell_str = str(cell_value).strip().lower()
                        if "original item" in cell_str:
                            temp_block_start_col = col_idx
                            temp_block_header_row = row_idx
                            logger.info(f"Found 'Original Item' header at column {col_idx}, row {row_idx + 1} in sheet {sheet_title}")
                            break
                except Exception as e:
                    logger.error(f"Error checking cell at row {row_idx}, col {col_idx}: {str(e)}")
                    continue
            if temp_block_start_col is not None:
                break
        
        if temp_block_start_col is None:
            logger.debug(f"No 'Original Item' header found in sheet {sheet_title}")
            return temporary_items
        
        # Extract headers from the detected header row
        header_row = df.iloc[temp_block_header_row]
        header_values = [str(val).strip().lower() if not pd.isna(val) else "" for val in header_row]
        
        # Look for headers - only "Original Item" is required
        has_original_item = any("original item" in val for val in header_values)
        has_original_description = any("original description" in val for val in header_values)
        
        # Only "Original Item" is required - "Original Description" is optional
        if has_original_item:
            logger.info(f"Processing temporary item block in sheet {sheet_title}")
            logger.info(f"  - Original Item column: {'Found' if has_original_item else 'Not found'}")
            logger.info(f"  - Original Description column: {'Found' if has_original_description else 'Not found'}")
            
            # Find column indices for headers
            original_item_col = None
            original_description_col = None
            quantity_col = None
            unit_cost_col = None
            total_amount_col = None
            
            for col_idx, header_val in enumerate(header_values):
                if "original item" in header_val:
                    original_item_col = col_idx
                elif "original description" in header_val:
                    original_description_col = col_idx
                elif "total qty" in header_val or "quantity" in header_val:
                    quantity_col = col_idx
                elif "unit cost" in header_val:
                    unit_cost_col = col_idx
                elif "total amount" in header_val:
                    total_amount_col = col_idx
            
            # Extract data rows starting from the row after the header
            data_start_row = temp_block_header_row + 1
            
            for data_row_idx in range(data_start_row, len(df)):
                try:
                    data_row = df.iloc[data_row_idx]
                    
                    # Extract original item (required field)
                    original_item = ""
                    if original_item_col is not None and original_item_col < len(data_row):
                        item_val = data_row.iloc[original_item_col]
                        if not pd.isna(item_val):
                            original_item = str(item_val).strip()
                    
                    # Skip if no original item
                    if not original_item:
                        continue
                    
                    # Extract other fields
                    original_description = ""
                    if original_description_col is not None and original_description_col < len(data_row):
                        desc_val = data_row.iloc[original_description_col]
                        if not pd.isna(desc_val):
                            original_description = str(desc_val).strip()
                    
                    quantity = 1  # Default value
                    if quantity_col is not None and quantity_col < len(data_row):
                        qty_val = data_row.iloc[quantity_col]
                        if not pd.isna(qty_val):
                            try:
                                quantity = float(qty_val)
                            except (ValueError, TypeError):
                                quantity = 1
                    
                    unit_cost = 0.0  # Default value
                    if unit_cost_col is not None and unit_cost_col < len(data_row):
                        cost_val = data_row.iloc[unit_cost_col]
                        if not pd.isna(cost_val):
                            try:
                                unit_cost = float(cost_val)
                            except (ValueError, TypeError):
                                unit_cost = 0.0
                    
                    total_amount = unit_cost * quantity  # Calculate if not provided
                    if total_amount_col is not None and total_amount_col < len(data_row):
                        amount_val = data_row.iloc[total_amount_col]
                        if not pd.isna(amount_val):
                            try:
                                total_amount = float(amount_val)
                            except (ValueError, TypeError):
                                total_amount = unit_cost * quantity
                    
                    # Handle optional original_description
                    if original_description_col is not None and original_description_col < len(data_row):
                        original_description = str(data_row.iloc[original_description_col]).strip()
                    else:
                        original_description = f"Temporary item: {original_item}"  # Auto-generate
                    
                    # Create temporary item entry
                    temporary_item = {
                        "original_item": original_item,
                        "original_description": original_description,
                        "quantity": quantity,
                        "unit_cost": unit_cost,
                        "total_amount": total_amount,
                        "sheet_name": sheet_title,
                        "mapping_type": "temporary",
                        "validation_status": "valid_temporary"
                    }
                    
                    temporary_items.append(temporary_item)
                    logger.debug(
                        f"Extracted temporary item: {original_item} "
                        f"(description: {'provided' if original_description else 'auto-generated'})"
                    )
                    
                except Exception as e:
                    logger.error(f"Error extracting temporary item row {data_row_idx}: {str(e)}")
        return temporary_items

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
            if is_temporary_mapping(cleaned_data.get("mpi_code"), cleaned_data.get("description")):
                # This is a temporary mapping
                return {
                    **cleaned_data,
                    "mapping_type": "temporary",
                    "validation_status": "valid_temporary"
                }
            
            # Validate for permanent storage
            is_valid, validation_errors = validate_mapping_for_permanent_storage(cleaned_data)
            
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
            "temporary_items": 0,
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
                logger.error(f"Error processing sheet {sheet['title']}: {str(e)}")
        
        # Categorize items by type
        permanent_items = [item for item in self.all_items if item.get("mapping_type") == "permanent"]
        temporary_items = [item for item in self.all_items if item.get("mapping_type") == "temporary"]
        invalid_items = [item for item in self.all_items if item.get("mapping_type") == "invalid"]
        
        # Save extracted data to output file
        output_data = {
            "permanent_mappings": permanent_items,
            "temporary_mappings": temporary_items,
            "invalid_mappings": invalid_items,
            "statistics": self.extraction_stats,
            "extraction_timestamp": time.time()
        }
        
        with open(self.output_file, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        logger.info(
            f"Extraction complete. Processed {self.extraction_stats['sheets_processed']} sheets, "
            f"extracted {self.extraction_stats['total_extracted']} items. "
            f"Permanent: {self.extraction_stats['permanent_mappings']}, "
            f"Temporary: {self.extraction_stats['temporary_mappings']}, "
            f"Temporary Items: {self.extraction_stats['temporary_items']}, "
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


def extract_all_data_enhanced():
    """Extract all data from the Google Sheet using enhanced extractor."""
    extractor = EnhancedGoogleSheetDataExtractor()
    return extractor.process_all_sheets() 