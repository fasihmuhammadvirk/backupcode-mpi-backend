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
            "(AC, ITEMS WITHOUT TEMPORARY GROUP NAME)"
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
        col_name_lower = col_name.lower()
        best_match = None
        best_score = 0
        
        for supplier, info in self.supplier_mapping.items():
            for term in info["key_terms"]:
                score = fuzz.ratio(col_name_lower, term)
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
        Detect supplier columns in the DataFrame.
        
        Args:
            df_head: First few rows of the DataFrame
            df_full: Full DataFrame
            
        Returns:
            Dictionary mapping supplier names to column indices
        """
        supplier_columns = {}
        
        for col_idx, col_name in enumerate(df_head.columns):
            supplier_name, supplier_id, confidence = self.match_supplier(str(col_name))
            
            if confidence >= self.fuzzy_threshold and supplier_id > 0:
                # Validate that this column actually contains supplier data
                if self._validate_first_two_rows_have_supplier_data(df_full, col_idx):
                    if supplier_name not in supplier_columns:
                        supplier_columns[supplier_name] = []
                    supplier_columns[supplier_name].append(col_idx)
                    
                    logger.debug(
                        f"Detected supplier column: {col_name} -> {supplier_name} "
                        f"(confidence: {confidence})"
                    )
        
        return supplier_columns

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
        
        # Process each row
        for row_idx in range(start_row, len(df)):
            try:
                row = df.iloc[row_idx]
                actual_row = row_idx + 1  # 1-based row number
                
                # Extract MPI code and description from first few columns
                mpi_code = ""
                description = ""
                size = ""
                
                # Try to find MPI code in column 1 (most common location)
                if len(row) > 1:
                    mpi_code_val = row.iloc[1]
                    if not pd.isna(mpi_code_val):
                        mpi_code = str(mpi_code_val).strip()
                        
                        # Get description from column 2
                        if len(row) > 2:
                            desc_val = row.iloc[2]
                            if not pd.isna(desc_val):
                                description = str(desc_val).strip()
                        
                        # Get size from column 3
                        if len(row) > 3:
                            size_val = row.iloc[3]
                            if not pd.isna(size_val):
                                size = str(size_val).strip()
                
                # Fallback: If no MPI code in column 1, check column 0
                if not mpi_code and len(row) > 0:
                    mpi_code_val = row.iloc[0]
                    if not pd.isna(mpi_code_val):
                        mpi_code_str = str(mpi_code_val).strip()
                        # Check if this looks like an MPI code
                        if (mpi_code_str and len(mpi_code_str) > 2 and 
                            not mpi_code_str.lower() in ['item code', 'mpi', 'code', 'item', 'description']):
                            mpi_code = mpi_code_str
                            
                            # Shift description and size columns
                            if len(row) > 1:
                                desc_val = row.iloc[1]
                                if not pd.isna(desc_val):
                                    description = str(desc_val).strip()
                            if len(row) > 2:
                                size_val = row.iloc[2]
                                if not pd.isna(size_val):
                                    size = str(size_val).strip()
                
                # Skip row if no MPI code found
                if not mpi_code:
                    continue
                    
                # Skip header rows
                header_terms = ["item code", "mpi", "code", "item", "description", "size", "supplier"]
                mpi_lower = mpi_code.lower()
                
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