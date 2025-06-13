#!/usr/bin/env python3
"""
Google Sheet Data Extractor - Extracts data from Google Sheets.

This module provides functionality to extract and process data from Google Sheets,
focusing on mapping supplier item information.
"""

import os
import json
import logging
import re
import time
from typing import Dict, List, Any, Tuple

import pandas as pd
import requests
from googleapiclient.discovery import build
from rapidfuzz import fuzz

# Set up logging
logger = logging.getLogger(__name__)

# Import spreadsheet configuration
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID,
    GOOGLE_API_KEY,
    DEFAULT_OUTPUT_FILE
)


class GoogleSheetDataExtractor:
    """Extract and process data from Google Sheets."""

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
        Initialize the GoogleSheetDataExtractor.
        
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
        """
        Set up configuration parameters.
        
        Args:
            sheet_id: Google Sheet ID
            api_key: Google API key
            output_file: Output file path
            batch_size: Number of rows to process at once
            skip_sheets: List of sheet names to skip
            fuzzy_threshold: Threshold for fuzzy matching
        """
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
        """
        Extract key terms from supplier names for flexible matching.
        
        This includes acronyms (like BMW), individual words, and special cases.
        """
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
        """
        Create an acronym from a text string.
        
        Args:
            text: Text to create acronym from
            
        Returns:
            Acronym created from the text
        """
        return ''.join(
            word[0] for word in text.split() 
            if word.lower() not in ['and', '&']
        )

    def _extract_meaningful_words(self, text: str) -> List[str]:
        """
        Extract meaningful words from text.
        
        Args:
            text: Text to extract words from
            
        Returns:
            List of meaningful words
        """
        return [
            word for word in re.findall(r'\b\w+\b', text) 
            if len(word) > 1 and word.lower() not in 
            ['and', 'supply', 'supplies']
        ]

    def _add_supplier_specific_terms(self, supplier: str, info: Dict[str, Any]):
        """
        Add supplier-specific term variations.
        
        Args:
            supplier: Supplier name
            info: Supplier info dictionary to update
        """
        if supplier == "Y & S Plumbing Supply":
            info["key_terms"].extend(["Y&S", "YS"])
        elif supplier == "Flow Mark Plumbing Supply":
            info["key_terms"].extend(["FM", "FLM"])
        elif supplier == "Bruce Ferguson":
            info["key_terms"].extend(["BF"])

    def get_sheet_list(self) -> List[Dict[str, Any]]:
        """
        Get a list of all sheet names in the Google Sheet.
        
        Returns:
            List of dictionaries with sheet info
        """
        try:
            # Try to get sheet list via Google API
            return self._get_sheet_list_via_api()
        except Exception as e:
            logger.warning(f"Failed to get sheets via API: {e}")
            
        # Fallback to comprehensive list of known sheets
        return self._get_fallback_sheet_list()

    def _get_sheet_list_via_api(self) -> List[Dict[str, Any]]:
        """
        Get sheet list using Google Sheets API.
        
        Returns:
            List of sheet dictionaries
        """
        logger.info("Getting sheet list via Google API")
        service = build('sheets', 'v4', developerKey=self.api_key)
        result = service.spreadsheets().get(
            spreadsheetId=self.sheet_id,
            fields='sheets(properties(title,sheetId))'
        ).execute()
        
        # Process the result
        sheets = []
        for sheet in result.get('sheets', []):
            props = sheet.get('properties', {})
            sheets.append({
                'title': props.get('title', ''),
                'gid': str(props.get('sheetId', ''))
            })
            
        if sheets:
            logger.info(f"Found {len(sheets)} sheets via API")
            return sheets
        
        return []

    def _get_fallback_sheet_list(self) -> List[Dict[str, Any]]:
        """
        Get fallback sheet list when API fails.
        
        Returns:
            List of sheet dictionaries
        """
        logger.warning("Using fallback sheet list")
        # Implementation would be specific to your use case
        # This is a placeholder for the actual fallback logic
        return []

    def match_supplier(self, col_name: str) -> Tuple[str, int, float]:
        """
        Match a column name to a supplier using fuzzy matching.
        
        Args:
            col_name: Column name to match
            
        Returns:
            Tuple of (supplier_name, supplier_id, match_confidence)
        """
        best_match = ("Unknown", 0, 0)
        
        # Skip empty or numeric-only column names
        if not col_name or col_name.strip() == "" or col_name.strip().isnumeric():
            return best_match
            
        # Convert to lowercase for matching
        col_lower = col_name.lower()
        
        # Try direct matching with supplier names first
        for supplier, info in self.supplier_mapping.items():
            # Direct match with supplier name
            if supplier.lower() in col_lower:
                return (supplier, info["id"], 100.0)
                
            # Check if any of the key terms are in the column name
            for term in info["key_terms"]:
                if term in col_lower:
                    # If term is found, return with high confidence
                    return (supplier, info["id"], 95.0)
        
        # If no direct match, try fuzzy matching
        for supplier, info in self.supplier_mapping.items():
            # Check fuzzy match with supplier name
            ratio = fuzz.partial_ratio(supplier.lower(), col_lower)
            
            if ratio > self.fuzzy_threshold and ratio > best_match[2]:
                best_match = (supplier, info["id"], ratio)
                
            # Check fuzzy match with key terms
            for term in info["key_terms"]:
                if len(term) < 2:  # Skip very short terms
                    continue
                    
                term_ratio = fuzz.partial_ratio(term, col_lower)
                if term_ratio > self.fuzzy_threshold and term_ratio > best_match[2]:
                    best_match = (supplier, info["id"], term_ratio)
        
        return best_match

    def detect_supplier_columns(
        self, 
        df_head: pd.DataFrame,
        df_full: pd.DataFrame
    ) -> Dict[str, List[int]]:
        """
        Detect columns that contain supplier information.
        
        Args:
            df_head: DataFrame head for initial detection
            df_full: Full DataFrame to check if columns are empty
            
        Returns:
            Dictionary mapping supplier names to column indices
        """
        supplier_columns = {}
        unnamed_columns = []
        
        # First pass: Check for columns with explicit supplier names or numbered variations
        for col_idx, col_name in enumerate(df_head.columns):
            # Skip if column is empty
            if pd.isna(col_name):
                continue
                
            # Check if this is an unnamed column - collect these for later inspection
            if str(col_name).startswith('Unnamed:'):
                # Check if column contains any data
                col_data = df_full.iloc[:, col_idx]
                if not col_data.dropna().empty:
                    unnamed_columns.append(col_idx)
                continue
                
            # Skip columns that likely contain description/code data
            col_name_str = str(col_name).lower()
            if any(x in col_name_str for x in 
                  ["size", "description", "item code", "code", "mpi"]):
                continue
                
            # Check for supplier name with number pattern (e.g., "BMW 1", "BMW 2", "BMW3", "WWPS 1")
            # This regex handles both space-separated numbers (BMW 1) and attached numbers (BMW3)
            supplier_number_match = re.match(r'^([A-Za-z&\s]+)[\s]*(\d+)?$', str(col_name))
            
            if supplier_number_match:
                # Extract the base supplier name without the number
                base_supplier_name = supplier_number_match.group(1).strip()
                # Match the base supplier name
                supplier, supplier_id, confidence = self.match_supplier(base_supplier_name)
                
                # If good match, add to supplier columns
                if supplier_id > 0 and confidence >= self.fuzzy_threshold:
                    # Check if column contains any data
                    col_data = df_full.iloc[:, col_idx]
                    if not col_data.dropna().empty:
                        # Add to supplier columns
                        if supplier not in supplier_columns:
                            supplier_columns[supplier] = []
                        supplier_columns[supplier].append(col_idx)
                        
                        logger.info(
                            f"Detected supplier column: {col_name} -> "
                            f"{supplier} (ID: {supplier_id}, "
                            f"Confidence: {confidence:.1f}%)"
                        )
                    continue
            
            # Standard supplier name matching for columns without numbers
            supplier, supplier_id, confidence = self.match_supplier(str(col_name))
            
            # Only keep columns that have a supplier match and contain data
            if supplier_id > 0 and confidence >= self.fuzzy_threshold:
                # Check if column contains any data
                col_data = df_full.iloc[:, col_idx]
                if not col_data.dropna().empty:
                    # Add to supplier columns
                    if supplier not in supplier_columns:
                        supplier_columns[supplier] = []
                    supplier_columns[supplier].append(col_idx)
                    
                    logger.info(
                        f"Detected supplier column: {col_name} -> "
                        f"{supplier} (ID: {supplier_id}, "
                        f"Confidence: {confidence:.1f}%)"
                    )
        
        # Now check unnamed columns for supplier item patterns
        # Common patterns: item codes with supplier suffixes like -B, -W, -Y, -S
        suffix_pattern = r'-[BWYSGFPA]$'
        
        for col_idx in unnamed_columns:
            # Sample some non-empty values from this column
            col_data = df_full.iloc[:, col_idx].dropna()
            if len(col_data) == 0:
                continue
                
            # Check if values match supplier item patterns
            supplier_matches = {
                "BMW Plumbing Supplies": 0,
                "World Wide Plumbing": 0,
                "Y & S Plumbing Supply": 0,
                "Supreme Plumbing Supply": 0,
                "Pyramid Plumbing": 0,
                "Gotham Plumbing Supply": 0,
                "FW Webb Plumbing Supply": 0,
                "ABC Opus Services": 0,
                "Flow Mark Plumbing Supply": 0,
                "AF Supply": 0
            }
            
            # Count suffix matches
            for value in col_data[:30]:  # Check first 30 non-empty values (increased from 20)
                if not isinstance(value, str):
                    continue
                    
                value = str(value).strip()
                if value.endswith("-B"):
                    supplier_matches["BMW Plumbing Supplies"] += 1
                elif value.endswith("-W"):
                    supplier_matches["World Wide Plumbing"] += 1
                elif value.endswith("-Y"):
                    supplier_matches["Y & S Plumbing Supply"] += 1
                elif value.endswith("-S"):
                    supplier_matches["Supreme Plumbing Supply"] += 1
                elif value.endswith("-P"):
                    supplier_matches["Pyramid Plumbing"] += 1
                elif value.endswith("-G"):
                    supplier_matches["Gotham Plumbing Supply"] += 1
                elif value.endswith("-F"):
                    supplier_matches["FW Webb Plumbing Supply"] += 1
                elif value.endswith("-A"):
                    supplier_matches["ABC Opus Services"] += 1
                # Check for numeric patterns that might indicate supplier items
                elif re.match(r'^\d{8,}(-[A-Z])?$', value):  # Long numeric codes often used by BMW
                    supplier_matches["BMW Plumbing Supplies"] += 1
                elif re.match(r'^IN[A-Z0-9]{2,}(-[A-Z])?$', value):  # Patterns like INHL20-A for AF Supply
                    supplier_matches["AF Supply"] += 1
            
            # If we have a significant number of matches for a supplier, add this column
            for supplier, count in supplier_matches.items():
                if count >= 2:  # At least 2 matches to consider it a supplier column (reduced from 3)
                    if supplier not in supplier_columns:
                        supplier_columns[supplier] = []
                    supplier_columns[supplier].append(col_idx)
                    
                    logger.info(
                        f"Detected unnamed supplier column: {df_head.columns[col_idx]} -> "
                        f"{supplier} (ID: {self.supplier_ids[supplier]}, "
                        f"Based on {count} suffix/pattern matches)"
                    )
                    break  # Assign to the supplier with most matches
        
        # Check for columns we might have missed (especially those with supplier names in header row)
        if len(df_full) > 0:
            # Check the first few rows for supplier names
            for row_idx in range(min(8, len(df_full))):  # Increased from 5 to 8 rows
                for col_idx, col_name in enumerate(df_head.columns):
                    # Skip columns we've already identified
                    if any(col_idx in indices for indices in supplier_columns.values()):
                        continue
                        
                    # Skip empty columns
                    if col_idx >= len(df_full.iloc[row_idx]):
                        continue
                        
                    cell_value = df_full.iloc[row_idx, col_idx]
                    if pd.isna(cell_value) or not isinstance(cell_value, str):
                        continue
                        
                    # Check if this cell contains a supplier name or abbreviation
                    cell_str = str(cell_value).strip()
                    
                    # Check for common supplier column headers with more variations
                    for supplier_pattern, supplier_name in [
                        ("BMW", "BMW Plumbing Supplies"),
                        ("WWPS", "World Wide Plumbing"),
                        ("Y&S", "Y & S Plumbing Supply"),
                        ("Y & S", "Y & S Plumbing Supply"),
                        ("SUPREME", "Supreme Plumbing Supply"),
                        ("PYRAMID", "Pyramid Plumbing"),
                        ("GOTHAM", "Gotham Plumbing Supply"),
                        ("FW WEBB", "FW Webb Plumbing Supply"),
                        ("FLOW", "Flow Mark Plumbing Supply"),
                        ("OPUS", "ABC Opus Services"),
                        ("AF SUPPLY", "AF Supply"),
                        ("AF", "AF Supply"),
                        ("LION", "Lion Hvac Supplies"),
                        ("BRUCE", "Bruce Ferguson")
                    ]:
                        # Match supplier name with optional number (e.g., "BMW 1", "BMW 2")
                        if re.match(f"^{supplier_pattern}\\s*\\d*$", cell_str, re.IGNORECASE):
                            supplier_id = self.supplier_ids.get(supplier_name, 0)
                            if supplier_id > 0:
                                # Check if column contains any data
                                col_data = df_full.iloc[:, col_idx]
                                if not col_data.dropna().empty:
                                    # Add to supplier columns
                                    if supplier_name not in supplier_columns:
                                        supplier_columns[supplier_name] = []
                                    if col_idx not in supplier_columns[supplier_name]:
                                        supplier_columns[supplier_name].append(col_idx)
                                        
                                        logger.info(
                                            f"Detected supplier from header row: {cell_str} -> "
                                            f"{supplier_name} (ID: {supplier_id}, "
                                            f"Column: {col_name})"
                                        )
            
            # Additional check for columns that might contain supplier data but weren't detected
            # Look for columns that have item codes but weren't identified as supplier columns
            for col_idx, col_name in enumerate(df_head.columns):
                # Skip columns we've already identified
                if any(col_idx in indices for indices in supplier_columns.values()):
                    continue
                
                # Skip columns that likely contain description/code data
                col_name_str = str(col_name).lower()
                if any(x in col_name_str for x in 
                      ["size", "description", "item code", "code", "mpi"]):
                    continue
                
                # Check if column contains data that looks like item codes
                col_data = df_full.iloc[:, col_idx].dropna()
                if len(col_data) >= 5:  # At least 5 non-empty values
                    # Sample values to check for patterns
                    sample_values = col_data[:20].tolist()
                    string_values = [str(v).strip() for v in sample_values if isinstance(v, (str, int, float))]
                    
                    # Count values that look like item codes
                    code_patterns = [
                        r'^\d{5,}(-[A-Z])?$',  # Long numeric codes
                        r'^[A-Z]{2,}\d+(-[A-Z])?$',  # Alphanumeric codes
                        r'^[A-Z]{2,}[0-9]+[A-Z0-9]*(-[A-Z])?$'  # Complex alphanumeric codes
                    ]
                    
                    pattern_matches = 0
                    for value in string_values:
                        if any(re.match(pattern, value) for pattern in code_patterns):
                            pattern_matches += 1
                    
                    # If more than 30% of values look like item codes, consider it a supplier column
                    if pattern_matches > 0 and pattern_matches / len(string_values) >= 0.3:
                        # Try to determine which supplier based on patterns
                        # Default to BMW if we can't determine
                        supplier_name = "BMW Plumbing Supplies"
                        
                        # Check for specific patterns
                        for value in string_values:
                            if value.endswith("-W"):
                                supplier_name = "World Wide Plumbing"
                                break
                            elif value.endswith("-Y"):
                                supplier_name = "Y & S Plumbing Supply"
                                break
                            elif value.endswith("-S"):
                                supplier_name = "Supreme Plumbing Supply"
                                break
                            elif value.endswith("-B"):
                                supplier_name = "BMW Plumbing Supplies"
                                break
                            elif value.endswith("-A"):
                                supplier_name = "ABC Opus Services"
                                break
                            elif "IN" in value and len(value) > 5:
                                supplier_name = "AF Supply"
                                break
                        
                        # Add to supplier columns
                        if supplier_name not in supplier_columns:
                            supplier_columns[supplier_name] = []
                        if col_idx not in supplier_columns[supplier_name]:
                            supplier_columns[supplier_name].append(col_idx)
                            
                            logger.info(
                                f"Detected supplier column by pattern analysis: {col_name} -> "
                                f"{supplier_name} (ID: {self.supplier_ids[supplier_name]}, "
                                f"Based on {pattern_matches}/{len(string_values)} pattern matches)"
                            )
        
        return supplier_columns

    def process_sheet(self, sheet_title: str, gid: str) -> List[Dict[str, Any]]:
        """
        Process a single sheet from the Google Sheet.
        
        Args:
            sheet_title: Title of the sheet
            gid: Sheet ID
            
        Returns:
            List of extracted items
        """
        logger.info(f"Processing sheet: {sheet_title}")
        
        # Check if sheet should be skipped
        if any(skip_name in sheet_title for skip_name in self.skip_sheets):
            logger.info(f"Skipping sheet {sheet_title} (in skip list)")
            self.skipped_sheets.append(sheet_title)
            return []
        
        try:
            # Create export URL for the sheet
            export_url = (
                f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export"
                f"?format=csv&gid={gid}"
            )
            
            # Try to load the sheet with different URL patterns if needed
            try:
                # First attempt with standard URL
                df = pd.read_csv(export_url)
            except Exception as e:
                logger.info(f"Trying alternative URL for sheet {sheet_title}")
                # Try a different URL pattern
                alternate_url = (
                    f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/"
                    f"gviz/tq?tqx=out:csv&gid={gid}"
                )
                df = pd.read_csv(alternate_url)
            
            # Check if DataFrame is empty
            if df.empty:
                logger.warning(f"Sheet {sheet_title} is empty")
                self.empty_sheets.append(sheet_title)
                return []
            
            # Get a sample of rows for supplier column detection
            df_head = df.head(10)
            
            # Detect supplier columns
            supplier_columns = self.detect_supplier_columns(df_head, df)
            
            # If no supplier columns found, skip sheet
            if not supplier_columns:
                logger.warning(f"No supplier columns found in sheet {sheet_title}")
                self.empty_sheets.append(sheet_title)
                return []
            
            # Process the DataFrame in chunks
            extracted_items = []
            
            # Process in batches to handle large sheets efficiently
            for start_row in range(0, len(df), self.batch_size):
                end_row = min(start_row + self.batch_size, len(df))
                df_chunk = df.iloc[start_row:end_row]
                
                # Process chunk and add items to extracted items
                chunk_items = self._process_dataframe_chunk(
                    df_chunk, supplier_columns, sheet_title, start_row
                )
                extracted_items.extend(chunk_items)
            
            logger.info(
                f"Extracted {len(extracted_items)} items from sheet {sheet_title}"
            )
            return extracted_items
            
        except Exception as e:
            logger.error(f"Error processing sheet {sheet_title}: {str(e)}")
            return []

    def _process_dataframe_chunk(
        self, 
        df: pd.DataFrame,
        supplier_columns: Dict[str, List[int]],
        sheet_title: str,
        start_row: int
    ) -> List[Dict[str, Any]]:
        """
        Process a chunk of rows from a DataFrame.
        
        Args:
            df: DataFrame chunk to process
            supplier_columns: Dictionary mapping suppliers to column indices
            sheet_title: Title of the sheet
            start_row: Starting row index
            
        Returns:
            List of extracted items
        """
        extracted_items = []
        
        # Process each row in the chunk
        for row_idx, row in df.iterrows():
            # Calculate actual row index
            actual_row = start_row + row_idx - df.index[0] + 1
            
            # Get MPI code explicitly from column 1 (index 1)
            mpi_code = None
            description = None
            size = None
            
            # Use consistent logic for finding MPI code and description
            if len(row) > 1:
                mpi_code_val = row.iloc[1]  # MPI code in column 1 (index 1)
                if not pd.isna(mpi_code_val):
                    mpi_code = str(mpi_code_val).strip()
                    
                    # Get description from column 2 (index 2)
                    if len(row) > 2:
                        desc_val = row.iloc[2]
                        if not pd.isna(desc_val):
                            description = str(desc_val).strip()
                        
                        # Get size from column 3 (index 3) if available
                        if len(row) > 3:
                            size_val = row.iloc[3]
                            if not pd.isna(size_val):
                                size = str(size_val).strip()
            
            # Skip row if no MPI code found
            if not mpi_code:
                continue
                
            # Skip header rows - check for common header text patterns
            header_terms = ["item code", "mpi", "code", "item", "description", "size"]
            mpi_lower = mpi_code.lower()
            
            # Skip if the MPI code or description field contains header-like text
            if any(term in mpi_lower for term in header_terms) or (
                description and any(
                    term in description.lower() for term in header_terms
                )
            ):
                logger.debug(f"Skipping header row {actual_row}: {mpi_code}")
                continue
            
            # Create a combined description with size and sheet name
            combined_description = description or ""
            if size:
                combined_description = f"{size} {combined_description}"
            
            # Remove sheet name from the description, only use size + description
            combined_description = combined_description.strip()
            
            logger.debug(
                f"Row {actual_row}: Code={mpi_code}, "
                f"Desc={combined_description}"
            )
            
            # Process supplier columns for this row
            for supplier, col_indices in supplier_columns.items():
                for col_idx in col_indices:
                    if col_idx >= len(row):
                        continue
                        
                    cell_value = row.iloc[col_idx]
                    
                    # Skip empty or non-string cells
                    if pd.isna(cell_value) or not isinstance(cell_value, str) or not cell_value.strip():
                        continue
                    
                    # Clean the supplier_item_ids by removing prefixes
                    supplier_value = str(cell_value).strip()
                    # Remove common prefix patterns like -B, -W, -Y, -S
                    cleaned_value = re.sub(
                        r'\s*-\s*[BWYSGFPA](\s|$)', 
                        '', 
                        supplier_value
                    )
                    # Remove any extra spaces
                    cleaned_value = cleaned_value.strip()
                    
                    # Skip if the supplier ID field contains header-like text
                    if any(term in cleaned_value.lower() for term in ["supplier", "item", "id", "code"]):
                        continue
                    
                    # Get the original column name
                    supplier_column_name = str(df.columns[col_idx])
                    
                    # Create item mapping with enhanced data
                    item_mapping = {
                        "mpi_code": mpi_code,
                        "description": combined_description,
                        "size": size if size else "",  # Add size as a separate field
                        "supplier_name": supplier,
                        "supplier_id": self.supplier_ids[supplier],
                        "supplier_item_ids": cleaned_value,
                        "google_sheet_name": sheet_title,
                        "row_index": actual_row,
                        "supplier_column_name": supplier_column_name
                    }
                    
                    extracted_items.append(item_mapping)
        
        return extracted_items

    def process_all_sheets(self) -> List[Dict[str, Any]]:
        """
        Process all sheets in the Google Sheet.
        
        Returns:
            List of all extracted items
        """
        logger.info(f"Processing Google Sheet: {self.sheet_id}")
        
        # Get list of sheets
        sheets = self.get_sheet_list()
        
        if not sheets:
            logger.warning("No sheets found")
            return []
        
        logger.info(f"Found {len(sheets)} sheets")
        
        # Reset tracking variables
        self.all_items = []
        self.skipped_sheets = []
        self.empty_sheets = []
        
        # Process each sheet
        for sheet in sheets:
            try:
                sheet_items = self.process_sheet(
                    sheet_title=sheet['title'],
                    gid=sheet['gid']
                )
                self.all_items.extend(sheet_items)
                
                # Short pause to avoid overwhelming the API
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"Error processing sheet {sheet['title']}: {str(e)}")
        
        # Save extracted data to output file
        with open(self.output_file, 'w') as f:
            json.dump(self.all_items, f, indent=2)
        
        logger.info(
            f"Extraction complete. Processed {len(sheets)} sheets, "
            f"extracted {len(self.all_items)} items. "
            f"Output saved to {self.output_file}"
        )
        
        # Log skipped and empty sheets
        if self.skipped_sheets:
            logger.info(
                f"Skipped {len(self.skipped_sheets)} sheets: "
                f"{self.skipped_sheets}"
            )
        if self.empty_sheets:
            logger.info(
                f"Empty sheets: {len(self.empty_sheets)} sheets: "
                f"{self.empty_sheets}"
            )
        
        return self.all_items


def extract_all_data():
    """Extract all data from the Google Sheet (utility function)."""
    extractor = GoogleSheetDataExtractor()
    return extractor.process_all_sheets() 