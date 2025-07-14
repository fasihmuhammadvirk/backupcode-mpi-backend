#!/usr/bin/env python3
"""
Temporary Mapping Extractor - Extracts temporary mappings from Google Sheets.

This module provides functionality to detect and extract temporary mapping sections
from Google Sheets based on specific header criteria.
"""

import logging
import pandas as pd
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
import re

# Split long import lines
import os
import json

from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping

# Set up logging
logger = logging.getLogger(
    __name__
)


class TemporaryMappingExtractor:
    """Extract temporary mappings from Google Sheets."""

    def __init__(self, db: Session):
        """
        Initialize the TemporaryMappingExtractor.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.logger = logging.getLogger(
            f"{__name__}"
        )

    def detect_temporary_mapping_section(self, df: pd.DataFrame) -> Optional[int]:
        """
        Detect the temporary mapping section in a DataFrame based on exact mapping sheet structure.
        
        Criteria for temporary mappings (based on analysis):
        - First two rows (0 and 1) are empty/NaN
        - Row 2 contains headers "Original Item" and "Original Description"
        - Data starts from row 3 onwards
        - Always appear as pairs of adjacent columns
        
        Args:
            df: DataFrame to check for temporary mapping section
        Returns:
            Starting row index (0-based) if temporary mapping section found, None otherwise
        """
        if len(df) < 3:
            return None
        
        # Check for the exact pattern: empty rows 0-1, headers in row 2
        try:
            # Look for columns where first two rows are empty and row 2 has the right headers
            for col_idx in range(len(df.columns) - 1):  # Need at least 2 adjacent columns
                # Check current column
                row_0_empty = pd.isna(df.iloc[0, col_idx])
                row_1_empty = pd.isna(df.iloc[1, col_idx])
                row_2_val = str(df.iloc[2, col_idx]).strip().lower() if pd.notna(df.iloc[2, col_idx]) else ""
                
                # Check next column
                next_row_0_empty = pd.isna(df.iloc[0, col_idx + 1])
                next_row_1_empty = pd.isna(df.iloc[1, col_idx + 1])
                next_row_2_val = str(df.iloc[2, col_idx + 1]).strip().lower() if pd.notna(df.iloc[2, col_idx + 1]) else ""
                
                # Check for exact pattern
                if (row_0_empty and row_1_empty and 
                    ("original" in row_2_val and "item" in row_2_val) and
                    next_row_0_empty and next_row_1_empty and
                    ("original" in next_row_2_val and "description" in next_row_2_val)):
                    
                    self.logger.info(f"Temporary mapping section detected at columns {col_idx}-{col_idx+1}, row 2")
                    return 2  # Headers are in row 2, data starts from row 3
                    
        except Exception as e:
            self.logger.error(f"Error detecting temporary mapping section: {str(e)}")
        
        # Fallback to alternative detection methods
        return self._detect_alternative_temporary_section(df)

    def _detect_alternative_temporary_section(self, df: pd.DataFrame) -> Optional[int]:
        """
        Detect temporary mapping sections using alternative header patterns.
        
        Args:
            df: DataFrame to check for temporary mapping section
        Returns:
            Starting row index (0-based) if temporary mapping section found, None otherwise
        """
        max_scan_rows = min(20, len(df))
        
        # Alternative patterns for temporary mapping headers
        patterns = [
            # Pattern 1: "Item" and "Description"
            (["item", "description"], 2),
            # Pattern 2: "Code" and "Description" 
            (["code", "description"], 2),
            # Pattern 3: "Original" and "Description"
            (["original", "description"], 2),
            # Pattern 4: Single column with "Item" or "Code"
            (["item"], 1),
            (["code"], 1),
        ]
        
        for row_idx in range(max_scan_rows):
            try:
                row_values = [str(val).strip().lower() if not pd.isna(val) else "" for val in df.iloc[row_idx]]
                
                for pattern, min_columns in patterns:
                    matches = sum(1 for val in row_values if any(p in val for p in pattern))
                    if matches >= min_columns:
                        # Additional check: ensure this row has some data in subsequent rows
                        if self._has_data_in_subsequent_rows(df, row_idx):
                            self.logger.info(f"Alternative temporary mapping section detected starting at row {row_idx+1} with pattern: {pattern}")
                            return row_idx
                            
            except Exception as e:
                self.logger.error(f"Error scanning row {row_idx} for alternative headers: {str(e)}")
                continue
        
        return None

    def _has_data_in_subsequent_rows(self, df: pd.DataFrame, header_row: int) -> bool:
        """
        Check if there's actual data in the rows following the header row.
        
        Args:
            df: DataFrame to check
            header_row: Index of the header row
            
        Returns:
            True if there's data in subsequent rows
        """
        # Check next 5 rows for any non-empty data
        for row_idx in range(header_row + 1, min(header_row + 6, len(df))):
            try:
                row = df.iloc[row_idx]
                for cell in row:
                    if pd.notna(cell) and str(cell).strip():
                        return True
            except Exception:
                continue
        return False

    def clean_item_suffix(self, item: str) -> str:
        """
        Remove common supplier suffixes like -B, -Y, -F, etc. from the end of the item code.
        """
        if not item:
            return item
        # Remove dash followed by a single uppercase letter at the end
        return re.sub(r'-[A-Z]$', '', item)

    def extract_temporary_mappings(self, df: pd.DataFrame, sheet_name: str) -> List[Dict[str, Any]]:
        """
        Extract temporary mappings from a DataFrame.
        
        Args:
            df: DataFrame containing the temporary mapping data
            sheet_name: Name of the sheet for association
            
        Returns:
            List of extracted temporary mappings
        """
        # Detect temporary mapping section
        header_row_idx = self.detect_temporary_mapping_section(df)
        
        if header_row_idx is None:
            self.logger.debug(f"No temporary mapping section found in sheet: {sheet_name}")
            return []
        
        try:
            # Extract headers from the detected row
            headers = [str(val).strip() if not pd.isna(val) else "" for val in df.iloc[header_row_idx]]
            
            # Find column indices for required headers
            original_item_col = None
            original_description_col = None
            
            # FIXED: More flexible header detection
            for i, header in enumerate(headers):
                header_lower = header.lower()
                if "original item" in header_lower or "item" in header_lower:
                    original_item_col = i
                elif "original description" in header_lower or "description" in header_lower:
                    original_description_col = i
            
            # FIXED: If we only found one column, try to infer the other
            if original_item_col is not None and original_description_col is None:
                # Look for description in adjacent columns
                for i in range(max(0, original_item_col - 2), min(len(headers), original_item_col + 3)):
                    if i != original_item_col:
                        header_lower = headers[i].lower()
                        if "description" in header_lower or "desc" in header_lower:
                            original_description_col = i
                            break
            
            if original_item_col is None:
                self.logger.warning(f"Required item header not found in sheet: {sheet_name}")
                return []
            
            # Extract data rows (start from the row after headers)
            data_start_row = header_row_idx + 1
            extracted_mappings = []
            
            # FIXED: Process more rows to catch all data
            for row_idx in range(data_start_row, len(df)):
                try:
                    row_data = df.iloc[row_idx]
                    
                    # Extract original item and description
                    original_item = ""
                    original_description = ""
                    
                    if original_item_col < len(row_data):
                        original_item = str(row_data.iloc[original_item_col]).strip() if not pd.isna(row_data.iloc[original_item_col]) else ""
                        # Clean suffix from original_item
                        original_item = self.clean_item_suffix(original_item)
                    
                    if original_description_col is not None and original_description_col < len(row_data):
                        original_description = str(row_data.iloc[original_description_col]).strip() if not pd.isna(row_data.iloc[original_description_col]) else ""
                    
                    # FIXED: More lenient validation - accept items with just item code
                    if not original_item:
                        continue
                    
                    # Skip if it's clearly a header row
                    if any(term in original_item.lower() for term in ["item", "code", "description", "header", "total"]):
                        continue
                    
                    mapping_data = {
                        "original_item": original_item,
                        "original_description": original_description,
                        "sheet_name": sheet_name
                    }
                    
                    extracted_mappings.append(mapping_data)
                    
                    self.logger.debug(
                        f"Extracted temporary mapping: {original_item} -> {original_description} ({sheet_name})"
                    )
                    
                except Exception as e:
                    self.logger.error(f"Error extracting row {row_idx} in sheet {sheet_name}: {str(e)}")
                    continue
            
            self.logger.info(f"Extracted {len(extracted_mappings)} temporary mappings from sheet: {sheet_name}")
            return extracted_mappings
            
        except Exception as e:
            self.logger.error(f"Error extracting temporary mappings from sheet {sheet_name}: {str(e)}")
            return []

    def save_temporary_mappings(self, mappings: List[Dict[str, Any]]) -> int:
        """
        Save temporary mappings to the database.
        Args:
            mappings: List of temporary mapping dictionaries
        Returns:
            Number of mappings saved
        """
        if not mappings:
            return 0
        try:
            # Filter out mappings with empty or null original_item or sheet_name
            valid_mappings = [
                m for m in mappings
                if m.get("original_item") and m.get("sheet_name")
            ]
            if not valid_mappings:
                return 0
            # Clear existing temporary mappings for affected sheet names
            sheet_names = {mapping["sheet_name"] for mapping in valid_mappings}
            for sheet_name in sheet_names:
                self.db.query(TempItemMapping).filter(
                    TempItemMapping.sheet_name == sheet_name
                ).delete()
            # Insert new temporary mappings
            saved_count = 0
            for mapping_data in valid_mappings:
                temp_mapping = TempItemMapping(
                    original_item=mapping_data["original_item"],
                    original_description=mapping_data["original_description"],
                    sheet_name=mapping_data["sheet_name"]
                )
                self.db.add(temp_mapping)
                saved_count += 1
            self.db.commit()
            self.logger.info(f"Saved {saved_count} temporary mappings to database")
            return saved_count
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error saving temporary mappings: {str(e)}")
            raise

    def extract_and_save_from_dataframe(self, df: pd.DataFrame, sheet_name: str) -> int:
        """
        Extract and save temporary mappings from a DataFrame in one operation.
        Also writes all extracted mappings to a JSON file for backup/reference.
        Args:
            df: DataFrame to extract from
            sheet_name: Name of the sheet
        Returns:
            Number of mappings extracted and saved
        """
        # Extract temporary mappings
        mappings = self.extract_temporary_mappings(df, sheet_name)
        if not mappings:
            return 0
        # Save to database
        saved_count = self.save_temporary_mappings(mappings)
        # --- Save all temporary mappings to JSON file ---
        try:
            # Query all temporary mappings from the DB
            all_temp_mappings = self.db.query(TempItemMapping).all()
            all_temp_mappings_dicts = [
                {
                    "original_item": m.original_item,
                    "original_description": m.original_description,
                    "sheet_name": m.sheet_name,
                    "created_at": (
                        m.created_at.isoformat() if m.created_at else None
                    ),
                    "updated_at": (
                        m.updated_at.isoformat() if m.updated_at else None
                    )
                }
                for m in all_temp_mappings
            ]
            # Ensure the directory exists
            output_path = os.path.join(
                os.path.dirname(__file__),
                '../../storage/fixtures/temp-item-mapping.json'
            )
            output_path = os.path.normpath(output_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            # Write to JSON file
            with open(output_path, 'w') as f:
                json.dump(
                    all_temp_mappings_dicts, f, indent=2
                )
            self.logger.info(
                f"Exported all temporary mappings to {output_path}"
            )
        except Exception as e:
            self.logger.error(
                f"Failed to export temporary mappings to JSON: {e}"
            )
        return saved_count 