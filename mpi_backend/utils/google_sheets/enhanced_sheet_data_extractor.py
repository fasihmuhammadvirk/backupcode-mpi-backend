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
        
        # Set default skip_sheets - REMOVED "(AC, ITEMS WITHOUT TEMPORARY GROUP NAME)" 
        # as it contains important unmapped items
        self.skip_sheets = skip_sheets or [
            "(AB, ALL SYSTEMS)"  # Only skip the summary sheet
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
        Extract clean sheet name for classification.
        
        Args:
            sheet_title: Original sheet title
            
        Returns:
            Clean sheet name
        """
        # Remove common prefixes and suffixes
        clean_name = sheet_title.strip()
        
        # Remove parentheses and their contents
        clean_name = re.sub(r'\([^)]*\)', '', clean_name)
        
        # Remove extra spaces and clean up
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()
        
        return clean_name

    def get_sheet_list(self) -> List[Dict[str, Any]]:
        """Get list of all sheets in the Google Spreadsheet."""
        try:
            return self._get_sheet_list_via_api()
        except Exception as e:
            logger.warning(f"API method failed, using fallback: {e}")
            return self._get_fallback_sheet_list()

    def _get_sheet_list_via_api(self) -> List[Dict[str, Any]]:
        """Get sheet list using Google Sheets API."""
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
                    'gid': sheet_props.get('sheetId', '')
                })
            
            return sheets
        except Exception as e:
            logger.error(f"Error getting sheet list via API: {e}")
            raise

    def _get_fallback_sheet_list(self) -> List[Dict[str, Any]]:
        """Fallback method to get sheet list."""
        # This is a simplified fallback - in practice, you might want to
        # implement a more robust fallback mechanism
        return []

    def detect_sheet_structure(self, df: pd.DataFrame, sheet_title: str) -> Dict[str, Any]:
        """
        Detect the structure of a sheet to understand how to extract data.
        
        Args:
            df: DataFrame containing sheet data
            sheet_title: Title of the sheet
            
        Returns:
            Dictionary with detected structure information
        """
        structure = {
            "item_code_column": None,
            "description_column": None,
            "category_column": None,
            "supplier_columns": [],
            "sheet_type": "unknown",
            "has_headers": False
        }
        
        if df.empty or len(df.columns) == 0:
            return structure
        
        # Analyze first few rows to understand structure
        sample_rows = df.head(10)
        
        # Check if this is the "ITEMS WITHOUT TEMPORARY GROUP NAME" sheet
        if "ITEMS WITHOUT TEMPORARY GROUP NAME" in sheet_title:
            structure["sheet_type"] = "unmapped_items"
            structure["item_code_column"] = 1  # Column 1 contains item codes
            structure["description_column"] = 2  # Column 2 contains descriptions
            structure["category_column"] = 0  # Column 0 contains categories
            return structure
        
        # For other sheets, analyze the structure
        # Look for item codes in columns (typically columns 1, 2, or 3)
        for col_idx in range(min(5, len(df.columns))):
            col_data = sample_rows.iloc[:, col_idx].dropna()
            if len(col_data) > 0:
                # Check if this column contains item codes
                item_code_indicators = 0
                for val in col_data.head(5):
                    val_str = str(val).strip()
                    if (val_str and 
                        len(val_str) >= 3 and 
                        not val_str.lower() in ['nan', 'item', 'code', 'description', 'supplier', 'category'] and
                        any(c.isdigit() for c in val_str)):
                        item_code_indicators += 1
                
                if item_code_indicators >= 3:  # At least 3 values look like item codes
                    if structure["item_code_column"] is None:
                        structure["item_code_column"] = col_idx
                    elif structure["description_column"] is None:
                        structure["description_column"] = col_idx
                
                # Check if this column contains categories (first column often does)
                if col_idx == 0:
                    category_indicators = 0
                    for val in col_data.head(5):
                        val_str = str(val).strip().lower()
                        if val_str in ['tools', 'finishings', 'valves', 'pipe joining material', 'brass', 'copper']:
                            category_indicators += 1
                    
                    if category_indicators >= 2:
                        structure["category_column"] = col_idx
        
        # If we couldn't detect item code column, assume it's column 1
        if structure["item_code_column"] is None:
            structure["item_code_column"] = 1
        
        # If we couldn't detect description column, assume it's column 2
        if structure["description_column"] is None:
            structure["description_column"] = 2
        
        # Detect supplier columns (columns that contain supplier item codes)
        for col_idx in range(len(df.columns)):
            if col_idx not in [structure["item_code_column"], structure["description_column"], structure["category_column"]]:
                col_data = sample_rows.iloc[:, col_idx].dropna()
                if len(col_data) > 0:
                    # Check if this column contains supplier item codes
                    supplier_indicators = 0
                    for val in col_data.head(5):
                        val_str = str(val).strip()
                        if (val_str and 
                            len(val_str) >= 3 and 
                            not val_str.lower() in ['nan', 'item', 'code', 'description', 'supplier'] and
                            any(c.isdigit() for c in val_str)):
                            supplier_indicators += 1
                    
                    if supplier_indicators >= 2:
                        structure["supplier_columns"].append(col_idx)
        
        return structure

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
            
            # Detect sheet structure
            structure = self.detect_sheet_structure(df, sheet_title)
            
            if structure["item_code_column"] is None:
                logger.debug(f"Could not detect item code column in sheet: {sheet_title}")
                return []
            
            # Process the sheet data
            extracted_items = self._process_dataframe_with_structure(
                df, structure, sheet_title
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

    def _process_dataframe_with_structure(
        self, 
        df: pd.DataFrame,
        structure: Dict[str, Any],
        sheet_title: str
    ) -> List[Dict[str, Any]]:
        """
        Process DataFrame using detected structure.
        
        Args:
            df: DataFrame to process
            structure: Detected sheet structure
            sheet_title: Name of the sheet
            
        Returns:
            List of extracted mappings
        """
        extracted_items = []
        
        # Process each row
        for row_idx in range(len(df)):
            try:
                row = df.iloc[row_idx]
                actual_row = row_idx + 1  # 1-based row number
                
                # Extract data based on detected structure
                item_code = ""
                description = ""
                category = ""
                
                # Extract item code
                if structure["item_code_column"] is not None:
                    item_code_val = row.iloc[structure["item_code_column"]]
                    if not pd.isna(item_code_val):
                        item_code = str(item_code_val).strip()
                
                # Extract description
                if structure["description_column"] is not None:
                    desc_val = row.iloc[structure["description_column"]]
                    if not pd.isna(desc_val):
                        description = str(desc_val).strip()
                
                # Extract category
                if structure["category_column"] is not None:
                    cat_val = row.iloc[structure["category_column"]]
                    if not pd.isna(cat_val):
                        category = str(cat_val).strip()
                
                # Skip row if no item code found
                if not item_code:
                    continue
                    
                # Skip header rows
                header_terms = ["item code", "mpi", "code", "item", "description", "size", "supplier", "category"]
                item_lower = item_code.lower()
                
                if any(term in item_lower for term in header_terms) or (
                    description and any(
                        term in description.lower() for term in header_terms
                    )
                ):
                    logger.debug(f"Skipping header row {actual_row}: {item_code}")
                    continue
                
                # Determine supplier based on sheet name and category
                supplier = self._determine_supplier_from_sheet(sheet_title, category)
                
                if not supplier:
                    continue
                
                # Process supplier columns for this row
                for col_idx in structure["supplier_columns"]:
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
                        "mpi_code": item_code,
                        "description": description,
                        "category": category,
                        "supplier_name": supplier,
                        "supplier_id": self.supplier_ids.get(supplier, 0),
                        "supplier_item_ids": cleaned_value,
                        "google_sheet_name": clean_sheet_name,
                        "row_index": actual_row,
                        "supplier_column_name": supplier_column_name,
                        "original_supplier_value": supplier_value,
                        "sheet_type": structure["sheet_type"]
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
                        f"Extracted mapping: MPI={item_code}, Supplier={supplier}, "
                        f"Original={supplier_value}, Cleaned={cleaned_value}, "
                        f"Type={validated_mapping.get('mapping_type', 'unknown') if validated_mapping else 'invalid'}"
                    )
            
            except Exception as e:
                logger.error(f"Error processing row {row_idx} in sheet {sheet_title}: {str(e)}")
                continue
        
        return extracted_items

    def _determine_supplier_from_sheet(self, sheet_title: str, category: str) -> str:
        """
        Determine supplier based on sheet title and category.
        
        Args:
            sheet_title: Title of the sheet
            category: Category from the sheet
            
        Returns:
            Supplier name
        """
        # For the unmapped items sheet, items are typically from BMW
        if "ITEMS WITHOUT TEMPORARY GROUP NAME" in sheet_title:
            return "BMW Plumbing Supplies"
        
        # For other sheets, try to determine supplier based on sheet name
        sheet_lower = sheet_title.lower()
        
        if "bmw" in sheet_lower:
            return "BMW Plumbing Supplies"
        elif "world wide" in sheet_lower or "wwp" in sheet_lower:
            return "World Wide Plumbing"
        elif "y&s" in sheet_lower or "y & s" in sheet_lower:
            return "Y & S Plumbing Supply"
        elif "flow mark" in sheet_lower:
            return "Flow Mark Plumbing Supply"
        elif "gotham" in sheet_lower:
            return "Gotham Plumbing Supply"
        elif "supreme" in sheet_lower:
            return "Supreme Plumbing Supply"
        elif "pyramid" in sheet_lower:
            return "Pyramid Plumbing"
        elif "park" in sheet_lower:
            return "Park Plumbing Supply"
        elif "lion" in sheet_lower:
            return "Lion Hvac Supplies"
        elif "af supply" in sheet_lower:
            return "AF Supply"
        elif "plumbing exchange" in sheet_lower:
            return "Plumbing Exchange"
        elif "abc opus" in sheet_lower:
            return "ABC Opus Services"
        elif "fw webb" in sheet_lower:
            return "FW Webb Plumbing Supply"
        elif "bruce ferguson" in sheet_lower:
            return "Bruce Ferguson"
        
        # Default to BMW for most sheets
        return "BMW Plumbing Supplies"

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
        
        # Remove common suffix patterns for all suppliers
        # Remove dash followed by single letter at end (e.g., -B, -Y, -W, etc.)
        cleaned_value = re.sub(r'-[BWYSGFPA]$', '', cleaned_value)
        
        # Remove space-dash-letter patterns
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
            Validated and categorized mapping or None if invalid
        """
        try:
            # Clean the mapping data
            cleaned_data = clean_mapping_data(mapping_data)
            
            if not cleaned_data:
                return None
            
            # Extract key fields for validation
            mpi_code = cleaned_data.get('mpi_code', '')
            description = cleaned_data.get('description', '')
            
            # Determine if this should be a temporary mapping
            if should_use_temporary_storage(mpi_code, description):
                cleaned_data["mapping_type"] = "temporary"
                return cleaned_data
            
            # Check if this is a valid permanent mapping
            is_valid, errors = validate_mapping_for_permanent_storage(cleaned_data)
            if is_valid:
                cleaned_data["mapping_type"] = "permanent"
                return cleaned_data
            
            # If not valid for permanent storage, make it temporary
            cleaned_data["mapping_type"] = "temporary"
            return cleaned_data
            
        except Exception as e:
            logger.error(f"Error validating mapping: {e}")
            return None

    def process_all_sheets(self) -> Dict[str, Any]:
        """
        Process all sheets in the Google Spreadsheet.
        
        Returns:
            Dictionary with extraction results and statistics
        """
        logger.info("Starting enhanced Google Sheets data extraction...")
        
        try:
            # Get list of all sheets
            sheets = self.get_sheet_list()
            
            if not sheets:
                logger.error("No sheets found in the spreadsheet")
                return {
                    "success": False,
                    "error": "No sheets found",
                    "stats": self.extraction_stats
                }
            
            logger.info(f"Found {len(sheets)} sheets to process")
            
            # Process each sheet
            for sheet in sheets:
                sheet_title = sheet.get('title', '')
                gid = sheet.get('gid', '')
                
                if not sheet_title or not gid:
                    continue
                
                logger.info(f"Processing sheet: {sheet_title}")
                
                # Process the sheet
                extracted_items = self.process_sheet(sheet_title, gid)
                
                # Add extracted items to the main list
                self.all_items.extend(extracted_items)
                
                # Update statistics
                self.extraction_stats["sheets_processed"] += 1
                
                logger.info(f"Extracted {len(extracted_items)} items from {sheet_title}")
            
            # Save results to file
            self._save_results()
            
            # Log final statistics
            logger.info("Extraction completed successfully!")
            logger.info(f"Total items extracted: {self.extraction_stats['total_extracted']}")
            logger.info(f"Permanent mappings: {self.extraction_stats['permanent_mappings']}")
            logger.info(f"Temporary mappings: {self.extraction_stats['temporary_mappings']}")
            logger.info(f"Sheets processed: {self.extraction_stats['sheets_processed']}")
            logger.info(f"Sheets skipped: {len(self.skipped_sheets)}")
            logger.info(f"Empty sheets: {len(self.empty_sheets)}")
            
            return {
                "success": True,
                "total_items": len(self.all_items),
                "stats": self.extraction_stats,
                "skipped_sheets": self.skipped_sheets,
                "empty_sheets": self.empty_sheets
            }
            
        except Exception as e:
            logger.error(f"Error during extraction: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "stats": self.extraction_stats
            }

    def _save_results(self):
        """Save extracted results to the output file."""
        try:
            # Create output directory if it doesn't exist
            output_dir = os.path.dirname(self.output_file)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
            
            # Save all items to JSON file
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(self.all_items, f, indent=2, ensure_ascii=False, default=str)
            
            logger.info(f"Results saved to: {self.output_file}")
            
        except Exception as e:
            logger.error(f"Error saving results: {e}")


def extract_all_data_enhanced():
    """
    Main function to extract all data from Google Sheets using the enhanced extractor.
    
    Returns:
        Dictionary with extraction results
    """
    extractor = EnhancedGoogleSheetDataExtractor()
    return extractor.process_all_sheets()


if __name__ == "__main__":
    # Run the extraction
    results = extract_all_data_enhanced()
    print(json.dumps(results, indent=2)) 