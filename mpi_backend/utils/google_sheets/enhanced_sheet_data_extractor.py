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
            "(AC, ITEMS WITHOUT TEMPORARY GROUP NAME)",
            "(Z, ADDITIONAL FEES)"
        ]
        
        # Set fuzzy matching threshold
        self.fuzzy_threshold = fuzzy_threshold

    def _setup_supplier_mapping(self):
        """Set up supplier mappings and extract key terms for matching."""
        # Define suppliers with their IDs and base names for matching
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
            "Plumbing Exchange": {"id": 11},
            "AF Supply": {"id": 12},
            "Lion Hvac Supplies": {"id": 13},
            "Bruce Ferguson": {"id": 14}
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
            
            # Start with the full supplier name and individual words
            key_terms = [supplier.lower()] + words + [acronym]
            
            # Add specific known variations for some suppliers
            self._add_supplier_specific_terms(supplier, info)
            key_terms.extend(info.get("additional_terms", []))
            
            # Remove duplicates while preserving order
            seen = set()
            unique_terms = []
            for term in key_terms:
                term_lower = term.lower()
                if term_lower not in seen:
                    seen.add(term_lower)
                    unique_terms.append(term_lower)
            
            # Save key terms for matching
            info["key_terms"] = unique_terms
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
        additional_terms = []
        
        if "BMW" in supplier:
            additional_terms.extend(["bmw", "plumbing", "supplies"])
        elif "World Wide" in supplier:
            additional_terms.extend(["world", "wide", "wwp"])
        elif "Y & S" in supplier:
            additional_terms.extend(["y&s", "ys", "plumbing", "supply"])
        
        # Store additional terms for later use
        info["additional_terms"] = additional_terms

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
        Match a column name to a supplier using fuzzy matching and keyword matching.
        
        Args:
            col_name: Column name to match
            
        Returns:
            Tuple of (supplier_name, supplier_id, confidence_score)
        """
        col_name_lower = col_name.lower()
        best_match = None
        best_score = 0
        
        for supplier, info in self.supplier_mapping.items():
            # Check against all key terms
            for term in info["key_terms"]:
                # Try fuzzy matching
                score = fuzz.ratio(col_name_lower, term)
                if score > best_score and score >= self.fuzzy_threshold:
                    best_score = score
                    best_match = supplier
                
                # Also try partial matching for multi-word combinations
                if term in col_name_lower or col_name_lower in term:
                    partial_score = 85 + (fuzz.ratio(col_name_lower, term) * 0.15)
                    if partial_score > best_score:
                        best_score = partial_score
                        best_match = supplier
            
            # Additional check: if column contains key supplier identifiers
            supplier_keywords = {
                "BMW Plumbing Supplies": ["bmw"],
                "World Wide Plumbing": ["wwps", "world wide", "www"],
                "Y & S Plumbing Supply": ["y&s", "ys"],
                "Supreme Plumbing Supply": ["supreme"],
                "Pyramid Plumbing": ["pyramid"],
                "Park Plumbing Supply": ["park"],
                "Gotham Plumbing Supply": ["gotham"],
                "Flow Mark Plumbing Supply": ["flow", "flowmark"],
                "FW Webb Plumbing Supply": ["webb"],
                "Plumbing Exchange": ["exchange"],
                "AF Supply": ["af supply", "af"],
                "Lion Hvac Supplies": ["lion"],
                "ABC Opus Services": ["abc"],
                "Bruce Ferguson": ["ferguson"]
            }
            
            if supplier in supplier_keywords:
                for keyword in supplier_keywords[supplier]:
                    if keyword in col_name_lower:
                        keyword_score = 90
                        if keyword_score > best_score:
                            best_score = keyword_score
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
        Detect supplier columns in the DataFrame based on exact mapping sheet structure.
        
        Supplier columns have:
        - Row 0: Supplier name (e.g., "WWPS", "BMW", "Y&S", "SUPREME") or empty
        - Row 1: Specific identifier (e.g., "WWPS1", "WWPS2", "BMW1", "BMW2")
        - Data starts from row 3
        
        Args:
            df_head: First few rows of the DataFrame (not used in new logic)
            df_full: Full DataFrame
            
        Returns:
            Dictionary mapping supplier names to column indices
        """
        supplier_columns = {}
        
        if len(df_full) < 3:
            logger.warning("DataFrame has less than 3 rows, cannot detect supplier columns")
            return supplier_columns
        
        # Check each column for supplier pattern
        for col_idx in range(len(df_full.columns)):
            try:
                # Get values from first two rows
                row_0_val = df_full.iloc[0, col_idx] if len(df_full) > 0 else None
                row_1_val = df_full.iloc[1, col_idx] if len(df_full) > 1 else None
                
                # Convert to strings, handling NaN values
                row_0_str = str(row_0_val).strip() if pd.notna(row_0_val) else ""
                row_1_str = str(row_1_val).strip() if pd.notna(row_1_val) else ""
                
                # Skip if both rows are empty
                if not row_0_str and not row_1_str:
                    continue
                
                # Combine both rows for matching
                combined = f"{row_0_str} {row_1_str}".strip()
                
                # Check against supplier patterns
                supplier_name, supplier_id, confidence = self.match_supplier(combined)
                
                if confidence >= self.fuzzy_threshold and supplier_id > 0:
                    # Additional validation: check if this column has actual supplier data
                    if self._validate_supplier_column_data(df_full, col_idx):
                        if supplier_name not in supplier_columns:
                            supplier_columns[supplier_name] = []
                        supplier_columns[supplier_name].append(col_idx)
                        
                        logger.debug(
                            f"Detected supplier column: Col {col_idx} -> {supplier_name} "
                            f"(Row 0: '{row_0_str}', Row 1: '{row_1_str}', confidence: {confidence})"
                        )
                
            except (IndexError, KeyError) as e:
                logger.debug(f"Error processing column {col_idx}: {e}")
                continue
        
        # If no supplier columns detected with strict matching, try lenient approach
        if not supplier_columns:
            logger.warning("No supplier columns detected with strict matching, trying lenient approach")
            supplier_columns = self._detect_supplier_columns_lenient(df_full)
        
        return supplier_columns

    def _detect_supplier_columns_lenient(self, df_full: pd.DataFrame) -> Dict[str, List[int]]:
        """
        More lenient supplier column detection for cases where strict matching fails.
        
        Args:
            df_full: Full DataFrame
            
        Returns:
            Dictionary mapping supplier names to column indices
        """
        supplier_columns = {}
        
        # Lower the threshold for lenient detection
        lenient_threshold = max(50, self.fuzzy_threshold - 25)
        
        for col_idx, col_name in enumerate(df_full.columns):
            supplier_name, supplier_id, confidence = self.match_supplier(str(col_name))
            
            if confidence >= lenient_threshold and supplier_id > 0:
                # More lenient validation
                if self._validate_column_has_data(df_full, col_idx):
                    if supplier_name not in supplier_columns:
                        supplier_columns[supplier_name] = []
                    supplier_columns[supplier_name].append(col_idx)
                    
                    logger.debug(
                        f"Lenient detection: {col_name} -> {supplier_name} "
                        f"(confidence: {confidence})"
                    )
        
        return supplier_columns

    def _validate_column_has_data(self, df_full: pd.DataFrame, col_idx: int) -> bool:
        """
        Simple validation that a column has some data.
        
        Args:
            df_full: Full DataFrame
            col_idx: Column index to validate
            
        Returns:
            True if column has any data
        """
        if col_idx >= len(df_full.columns):
            return False
        
        # Check first 10 rows for any non-empty data
        for row_idx in range(min(10, len(df_full))):
            try:
                cell_value = df_full.iloc[row_idx, col_idx]
                if pd.notna(cell_value):
                    cell_str = str(cell_value).strip()
                    if cell_str and len(cell_str) >= 1:
                        return True
            except (IndexError, KeyError):
                continue
        
        return False

    def _validate_supplier_column_data(self, df_full: pd.DataFrame, col_idx: int) -> bool:
        """
        Validate that a supplier column contains actual supplier item data.
        
        Args:
            df_full: Full DataFrame
            col_idx: Column index to validate
            
        Returns:
            True if column contains valid supplier data
        """
        if col_idx >= len(df_full.columns):
            return False
        
        # Check for actual supplier data starting from row 3 (where data should begin)
        data_found = False
        for row_idx in range(3, min(10, len(df_full))):  # Check first 7 data rows
            try:
                cell_value = df_full.iloc[row_idx, col_idx]
                if pd.notna(cell_value):
                    cell_str = str(cell_value).strip()
                    if (cell_str and 
                        len(cell_str) >= 2 and 
                        not any(term in cell_str.lower() for term in 
                               ["item", "code", "description", "supplier", "header", "original"])):
                        data_found = True
                        break
            except (IndexError, KeyError):
                continue
        
        return data_found

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
            
            # FIXED: Log sheet dimensions for debugging
            logger.info(f"Processing sheet '{sheet_title}': {len(df)} rows, {len(df.columns)} columns")
            
            # Detect supplier columns
            supplier_columns = self.detect_supplier_columns(df.head(), df)
            
            if not supplier_columns:
                logger.warning(f"No supplier columns detected in sheet: {sheet_title}")
                # FIXED: Try to extract any data even without supplier columns
                return self._extract_generic_mappings(df, sheet_title)
            
            # Process the sheet data
            extracted_items = self._process_dataframe_chunk(
                df, supplier_columns, sheet_title, 0
            )
            
            logger.info(
                f"Extracted {len(extracted_items)} items from sheet: {sheet_title}"
            )
            
            return extracted_items
            
        except Exception as e:
            logger.error(f"Error processing sheet {sheet_title}: {str(e)}")
            return []

    def _extract_generic_mappings(self, df: pd.DataFrame, sheet_title: str) -> List[Dict[str, Any]]:
        """
        Extract generic mappings when no supplier columns are detected.
        
        Args:
            df: DataFrame to process
            sheet_title: Name of the sheet
            
        Returns:
            List of extracted mappings
        """
        extracted_items = []
        
        # Try to extract any meaningful data from the sheet
        for row_idx in range(len(df)):
            try:
                row = df.iloc[row_idx]
                
                # Look for any non-empty cells that might be item codes
                for col_idx in range(min(5, len(row))):  # Check first 5 columns
                    cell_value = row.iloc[col_idx]
                    if pd.notna(cell_value):
                        cell_str = str(cell_value).strip()
                        if (cell_str and len(cell_str) >= 3 and 
                            not any(term in cell_str.lower() for term in 
                                   ["item", "code", "description", "supplier", "header", "total"])):
                            
                            # Create a generic mapping
                            item_mapping = {
                                "mpi_code": cell_str,
                                "description": "",
                                "size": "",
                                "supplier_name": "Unknown",
                                "supplier_id": 0,
                                "supplier_item_ids": cell_str,
                                "google_sheet_name": self._extract_clean_sheet_name(sheet_title),
                                "row_index": row_idx + 1,
                                "supplier_column_name": f"Column_{col_idx}",
                                "original_supplier_value": cell_str
                            }
                            
                            # Validate and categorize the mapping
                            validated_mapping = self._validate_and_categorize_mapping(item_mapping)
                            
                            if validated_mapping:
                                extracted_items.append(validated_mapping)
                                self.extraction_stats["total_extracted"] += 1
                                if is_temporary_mapping(validated_mapping.get("mpi_code"), validated_mapping.get("description")):
                                    self.extraction_stats["temporary_mappings"] += 1
                                else:
                                    self.extraction_stats["invalid_mappings"] += 1
                            
                            break  # Only extract one item per row
                
            except Exception as e:
                logger.error(f"Error processing row {row_idx} in generic extraction: {str(e)}")
                continue
        
        logger.info(f"Extracted {len(extracted_items)} generic items from sheet: {sheet_title}")
        return extracted_items

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
        Process a chunk of DataFrame data and extract mappings.
        
        Args:
            df: DataFrame to process
            supplier_columns: Dictionary mapping suppliers to column indices
            sheet_title: Name of the sheet
            start_row: Starting row index
            
        Returns:
            List of extracted mappings
        """
        extracted_items = []
        
        # Process data rows starting from row 3 (based on mapping sheet structure)
        # Rows 0-1: Supplier headers, Row 2: Additional headers, Data starts from row 3
        actual_start_row = max(3, start_row)
        for row_idx in range(actual_start_row, len(df)):
            try:
                row = df.iloc[row_idx]
                actual_row = row_idx + 1  # 1-based row number
                
                # Extract MPI code and description from first few columns
                mpi_code = ""
                description = ""
                size = ""
                
                # FIXED: More flexible MPI code detection
                mpi_code = self._extract_mpi_code(row)
                description = self._extract_description(row)
                size = self._extract_size(row)
                
                # Skip row if no MPI code found
                if not mpi_code:
                    continue
                    
                # Skip header rows
                if self._is_header_row(mpi_code, description):
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
                        
                        # Clean the supplier_item_ids by removing suffix patterns
                        cleaned_value = self._clean_supplier_item_id(
                            supplier_value, supplier
                        )
                        
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
                        item_mapping = {
                            "mpi_code": mpi_code,
                            "description": combined_description,
                            "size": size if size else "",
                            "supplier_name": supplier,
                            "supplier_id": self.supplier_ids[supplier],
                            "supplier_item_ids": cleaned_value,
                            "google_sheet_name": clean_sheet_name,
                            "row_index": actual_row,
                            "supplier_column_name": supplier_column_name,
                            "original_supplier_value": supplier_value
                        }
                        
                        # Validate and categorize the mapping
                        validated_mapping = self._validate_and_categorize_mapping(item_mapping)
                        
                        if validated_mapping:
                            extracted_items.append(validated_mapping)
                            
                            # Update statistics based on validation
                            self.extraction_stats["total_extracted"] += 1
                            if is_temporary_mapping(validated_mapping.get("mpi_code"), validated_mapping.get("description")):
                                self.extraction_stats["temporary_mappings"] += 1
                            else:
                                is_valid, validation_errors = validate_mapping_for_permanent_storage(validated_mapping)
                                if is_valid:
                                    self.extraction_stats["permanent_mappings"] += 1
                                else:
                                    self.extraction_stats["invalid_mappings"] += 1
                        
                        logger.debug(
                            f"Extracted mapping: MPI={mpi_code}, Supplier={supplier}, "
                            f"Original={supplier_value}, Cleaned={cleaned_value}, "
                            f"Type={'temporary' if is_temporary_mapping(validated_mapping.get('mpi_code'), validated_mapping.get('description')) else ('permanent' if validate_mapping_for_permanent_storage(validated_mapping)[0] else 'invalid') if validated_mapping else 'invalid'}"
                        )
            
            except Exception as e:
                logger.error(f"Error processing row {row_idx} in sheet {sheet_title}: {str(e)}")
                continue
        
        return extracted_items

    def _extract_mpi_code(self, row) -> str:
        """
        Extract MPI code from a row based on exact mapping sheet structure.
        
        Based on analysis:
        - MPI codes are in column 1 (index 1)
        - Column 1 has headers "MPI" (row 0) and "Item Code" (row 1)
        - Data starts from row 3
        """
        # Primary location: column 1 (where MPI codes are located)
        if len(row) > 1:
            mpi_code_val = row.iloc[1]
            if not pd.isna(mpi_code_val):
                mpi_code = str(mpi_code_val).strip()
                # Ensure it's not a header and has reasonable length
                if (mpi_code and len(mpi_code) >= 2 and 
                    mpi_code.lower() not in ['mpi', 'item code', 'item', 'code', 'description']):
                    return mpi_code
        
        # Fallback: check column 0 if column 1 is empty
        if len(row) > 0:
            mpi_code_val = row.iloc[0]
            if not pd.isna(mpi_code_val):
                mpi_code_str = str(mpi_code_val).strip()
                # Check if this looks like an MPI code (not a header)
                if (mpi_code_str and len(mpi_code_str) >= 2 and 
                    mpi_code_str.lower() not in ['tab name', 'sheet name', 'nan', 'none']):
                    return mpi_code_str
        
        # No fallback to supplier columns - return empty if MPI columns are empty
        return ""

    def _extract_description(self, row) -> str:
        """
        Extract description from a row based on exact mapping sheet structure.
        
        Based on analysis:
        - Descriptions are in column 2 (index 2)
        - Column 2 has header "DESCRIPTION" (row 1)
        - Data starts from row 3
        """
        # Primary location: column 2 (where descriptions are located)
        if len(row) > 2:
            desc_val = row.iloc[2]
            if not pd.isna(desc_val):
                description = str(desc_val).strip()
                if (description and len(description) > 1 and 
                    description.lower() not in ['description', 'desc', 'item', 'code']):
                    return description
        
        # Fallback: check column 3 if column 2 is empty
        if len(row) > 3:
            desc_val = row.iloc[3]
            if not pd.isna(desc_val):
                description = str(desc_val).strip()
                if (description and len(description) > 1 and 
                    description.lower() not in ['description', 'desc', 'item', 'code', 'size']):
                    return description
        
        # No fallback to supplier columns - return empty if description columns are empty
        return ""

    def _extract_size(self, row) -> str:
        """Extract size from a row."""
        # Try column 3 first
        if len(row) > 3:
            size_val = row.iloc[3]
            if not pd.isna(size_val):
                size_str = str(size_val).strip()
                if size_str and size_str.lower() not in ['size', 'dimension', 'measurement']:
                    return size_str
        
        # Try column 2 if no size in column 3
        if len(row) > 2:
            size_val = row.iloc[2]
            if not pd.isna(size_val):
                size_str = str(size_val).strip()
                if size_str and size_str.lower() not in ['size', 'dimension', 'measurement', 'description']:
                    return size_str
        
        # No fallback to supplier columns - return empty if size columns are empty
        return ""

    def _is_header_row(self, mpi_code: str, description: str) -> bool:
        """Check if a row is a header row."""
        header_terms = ["item code", "mpi", "code", "item", "description", "size", "supplier"]
        mpi_lower = mpi_code.lower()
        
        if any(term in mpi_lower for term in header_terms):
            return True
        
        if description and any(term in description.lower() for term in header_terms):
            return True
        
        return False

    def _clean_supplier_item_id(self, supplier_value: str, supplier: str) -> str:
        """
        Clean supplier item ID by removing suffix patterns.
        
        Args:
            supplier_value: Raw supplier item value
            supplier: Supplier name
            
        Returns:
            Cleaned supplier item ID
        """
        cleaned_value = supplier_value
        
        # Remove common BMW suffix patterns (but preserve the base item code)
        if supplier == "BMW Plumbing Supplies":
            # Remove dash followed by single letter at end
            cleaned_value = re.sub(r'-[BWYSGFPA]$', '', cleaned_value)
        else:
            # For other suppliers, remove space-dash-letter patterns
            cleaned_value = re.sub(r'\s*-\s*[BWYSGFPA](\s|$)', '', cleaned_value)
        
        # Remove any extra spaces
        cleaned_value = cleaned_value.strip()
        
        return cleaned_value

    def _validate_and_categorize_mapping(self, mapping_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Validate and categorize a mapping as permanent, temporary, or invalid.
        
        Args:
            mapping_data: Raw mapping data
            
        Returns:
            Validated mapping with original structure, or None if invalid
        """
        try:
            # Clean the mapping data
            cleaned_data = clean_mapping_data(mapping_data)
            
            # Check if this is a temporary mapping
            if is_temporary_mapping(cleaned_data.get("mpi_code"), cleaned_data.get("description")):
                # This is a temporary mapping - return original structure
                return cleaned_data
            
            # Validate for permanent storage
            is_valid, validation_errors = validate_mapping_for_permanent_storage(cleaned_data)
            
            if is_valid:
                # This is a valid permanent mapping - return original structure
                return cleaned_data
            else:
                # This is an invalid mapping - return original structure for consistency
                logger.warning(
                    f"Invalid mapping detected: {cleaned_data.get('mpi_code')} - {validation_errors}"
                )
                return cleaned_data
                
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
                logger.error(f"Error processing sheet {sheet['title']}: {str(e)}")
        
        # Categorize items by type
        permanent_items = []
        temporary_items = []
        invalid_items = []
        
        for item in self.all_items:
            # Determine mapping type using validation functions
            if is_temporary_mapping(item.get("mpi_code"), item.get("description")):
                temporary_items.append(item)
            else:
                is_valid, validation_errors = validate_mapping_for_permanent_storage(item)
                if is_valid:
                    permanent_items.append(item)
                else:
                    invalid_items.append(item)
        
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