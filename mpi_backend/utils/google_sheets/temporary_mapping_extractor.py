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
        Detect the temporary mapping section in a DataFrame.
        
        Criteria:
        - Any of the first 10 rows must contain headers: 'Original Item' and 'Original Description'
        
        Args:
            df: DataFrame to check for temporary mapping section
        Returns:
            Starting row index (0-based) if temporary mapping section found, None otherwise
        """
        max_scan_rows = min(10, len(df))
        for row_idx in range(max_scan_rows):
            try:
                row_values = [str(val).strip().lower() if not pd.isna(val) else "" for val in df.iloc[row_idx]]
                has_original_item = any("original item" in val for val in row_values)
                has_original_description = any("original description" in val for val in row_values)
                if has_original_item and has_original_description:
                    self.logger.info(f"Temporary mapping section detected starting at row {row_idx+1}")
                    return row_idx
            except Exception as e:
                self.logger.error(f"Error scanning row {row_idx} for header: {str(e)}")
                continue
        return None

    def clean_item_suffix(self, item: str) -> str:
        """
        With suffix standardization, we preserve the full item codes.
        This method is kept for backward compatibility but no longer removes suffixes.
        """
        if not item:
            return item
        # With suffix standardization, return the item as-is
        return item

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
            
            for i, header in enumerate(headers):
                header_lower = header.lower()
                if "original item" in header_lower:
                    original_item_col = i
                elif "original description" in header_lower:
                    original_description_col = i
            
            if original_item_col is None or original_description_col is None:
                self.logger.warning(f"Required headers not found in sheet: {sheet_name}")
                return []
            
            # Extract data rows (start from the row after headers)
            data_start_row = header_row_idx + 1
            extracted_mappings = []
            
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
                    
                    if original_description_col < len(row_data):
                        original_description = str(row_data.iloc[original_description_col]).strip() if not pd.isna(row_data.iloc[original_description_col]) else ""
                    
                    # Skip empty rows
                    if not original_item and not original_description:
                        continue
                    
                    # Skip if original_item is empty (required field)
                    if not original_item:
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