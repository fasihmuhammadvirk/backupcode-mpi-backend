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
from mpi_backend.database import get_db
from mpi_backend.utils.mapping_stats_manager import MappingStatsManager

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
        - Check column headers for 'Original Item' (required)
        - 'Original Description' is optional

        Args:
            df: DataFrame to check for temporary mapping section
        Returns:
            Starting row index (0-based) if temporary mapping section found, None otherwise
        """
        try:
            # Check column headers first
            column_headers = [str(col).strip().lower() if not pd.isna(
                col) else "" for col in df.columns]

            self.logger.debug(f"Column headers: {column_headers}")

            has_original_item = any(
                "original item" in header for header in column_headers)
            has_original_description = any(
                "original description" in header for header in column_headers)

            self.logger.debug(f"  - Has 'original item': {has_original_item}")
            self.logger.debug(
                f"  - Has 'original description': {has_original_description}")

            # If headers are found in column names, return row 0 (headers are in column names)
            if has_original_item:
                self.logger.info(
                    "Temporary mapping section detected in column headers")
                if not has_original_description:
                    self.logger.info(
                        "  - 'Original Description' header not found, will use default descriptions")
                return 0

            # If not found in column headers, check first few rows for headers
            max_scan_rows = min(10, len(df))
            for row_idx in range(max_scan_rows):
                try:
                    row_values = [str(val).strip().lower() if not pd.isna(
                        val) else "" for val in df.iloc[row_idx]]
                    has_original_item = any(
                        "original item" in val for val in row_values)
                    has_original_description = any(
                        "original description" in val for val in row_values)

                    # Debug logging
                    self.logger.debug(f"Row {row_idx}: {row_values}")
                    self.logger.debug(
                        f"  - Has 'original item': {has_original_item}")
                    self.logger.debug(
                        f"  - Has 'original description': {has_original_description}")

                    # Only "Original Item" is required - "Original Description" is optional
                    if has_original_item:
                        self.logger.info(
                            f"Temporary mapping section detected starting at row {row_idx+1}")
                        if not has_original_description:
                            self.logger.info(
                                f"  - 'Original Description' header not found, will use default descriptions")
                        return row_idx
                except Exception as e:
                    self.logger.error(
                        f"Error scanning row {row_idx} for header: {str(e)}")
                    continue
            return None
        except Exception as e:
            self.logger.error(f"Error in header detection: {str(e)}")
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
            self.logger.debug(
                f"No temporary mapping section found in sheet: {sheet_name}")
            return []

        try:
            # Determine if headers are in column names or data rows
            if header_row_idx == 0:
                # Headers are in column names
                headers = [str(col).strip() if not pd.isna(col)
                           else "" for col in df.columns]
                data_start_row = 0  # Start from first row since headers are column names
            else:
                # Headers are in data rows
                headers = [str(val).strip() if not pd.isna(
                    val) else "" for val in df.iloc[header_row_idx]]
                data_start_row = header_row_idx + 1

            # Find column indices for required headers
            original_item_col = None
            original_description_col = None

            for i, header in enumerate(headers):
                header_lower = header.lower()
                if "original item" in header_lower:
                    original_item_col = i
                elif "original description" in header_lower:
                    original_description_col = i

            if original_item_col is None:
                self.logger.warning(
                    f"Required 'Original Item' header not found in sheet: {sheet_name}")
                return []

            # Original Description is optional - if not found, we'll use a default description
            if original_description_col is None:
                self.logger.info(
                    f"'Original Description' header not found in sheet: {sheet_name} - will use default descriptions")

            # Extract data rows
            extracted_mappings = []

            # Enhanced approach: Process ALL rows to the end of the sheet
            # This handles data clusters with large gaps and data appearing after many empty rows
            total_rows_in_sheet = len(df)

            # Statistics for processing
            total_rows_processed = 0
            valid_items_found = 0
            empty_rows_skipped = 0
            data_clusters_found = 0
            current_cluster_size = 0
            in_data_cluster = False

            self.logger.info(f"Processing ALL rows from {data_start_row + 1} to {total_rows_in_sheet} "
                             f"for temporary items in sheet {sheet_name}")

            # Add timeout protection to prevent infinite loops
            # Limit to 10k rows max
            max_rows_to_process = min(
                total_rows_in_sheet - data_start_row, 10000)

            for row_idx in range(data_start_row, min(data_start_row + max_rows_to_process, total_rows_in_sheet)):
                try:
                    row_data = df.iloc[row_idx]
                    total_rows_processed += 1

                    # Extract original item and description
                    original_item = ""
                    original_description = ""

                    if original_item_col < len(row_data):
                        original_item = str(row_data.iloc[original_item_col]).strip(
                        ) if not pd.isna(row_data.iloc[original_item_col]) else ""
                        # With suffix standardization, preserve the original item form
                        # No suffix cleaning needed - items are stored with full suffixes

                    if original_description_col is not None and original_description_col < len(row_data):
                        original_description = str(row_data.iloc[original_description_col]).strip(
                        ) if not pd.isna(row_data.iloc[original_description_col]) else ""
                    else:
                        # If no description column, use a default description
                        original_description = f"Temporary item: {original_item}"

                    # Skip if original_item is empty (required field)
                    if not original_item:
                        empty_rows_skipped += 1
                        if in_data_cluster:
                            # End of current data cluster
                            if current_cluster_size > 0:
                                self.logger.debug(
                                    f"Ended data cluster with {current_cluster_size} items at row {row_idx + 1}")
                                data_clusters_found += 1
                            in_data_cluster = False
                            current_cluster_size = 0
                        continue

                    # We found a valid item - start or continue data cluster
                    if not in_data_cluster:
                        in_data_cluster = True
                        self.logger.debug(
                            f"Started new data cluster at row {row_idx + 1}")

                    current_cluster_size += 1
                    valid_items_found += 1

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
                    self.logger.error(
                        f"Error extracting row {row_idx} in sheet {sheet_name}: {str(e)}")
                    continue

            # Handle final data cluster if still in one
            if in_data_cluster and current_cluster_size > 0:
                data_clusters_found += 1
                self.logger.debug(
                    f"Final data cluster with {current_cluster_size} items")

            # Log processing statistics
            self.logger.info(
                f"Temporary items processing complete for sheet {sheet_name}:")
            self.logger.info(
                f"  - Total rows processed: {total_rows_processed}")
            self.logger.info(f"  - Valid items found: {valid_items_found}")
            self.logger.info(f"  - Empty rows skipped: {empty_rows_skipped}")
            self.logger.info(
                f"  - Data clusters detected: {data_clusters_found}")
            self.logger.info(
                f"  - Average cluster size: {valid_items_found / max(data_clusters_found, 1):.1f} items")

            self.logger.info(
                f"Extracted {len(extracted_mappings)} temporary mappings from sheet: {sheet_name}")
            return extracted_mappings

        except Exception as e:
            self.logger.error(
                f"Error extracting temporary mappings from sheet {sheet_name}: {str(e)}")
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
                try:
                    self.db.query(TempItemMapping).filter(
                        TempItemMapping.sheet_name == sheet_name
                    ).delete()
                    self.db.commit()
                except Exception as e:
                    self.logger.warning(
                        f"Error clearing existing mappings for {sheet_name}: {str(e)}")
                    self.db.rollback()

            # Process mappings in batches to avoid memory issues
            batch_size = 50
            saved_count = 0

            for i in range(0, len(valid_mappings), batch_size):
                batch = valid_mappings[i:i + batch_size]

                try:
                    for mapping_data in batch:
                        try:
                            # Use UPSERT approach to avoid duplicate key violations
                            existing_mapping = self.db.query(TempItemMapping).filter_by(
                                original_item=mapping_data["original_item"],
                                sheet_name=mapping_data["sheet_name"]
                            ).first()

                            if existing_mapping:
                                # Update existing mapping
                                existing_mapping.original_description = mapping_data[
                                    "original_description"]
                                self.logger.debug(
                                    f"Updated existing temporary mapping: {mapping_data['original_item']}")
                            else:
                                # Create new mapping with explicit ID handling
                                temp_mapping = TempItemMapping(
                                    original_item=mapping_data["original_item"],
                                    original_description=mapping_data["original_description"],
                                    sheet_name=mapping_data["sheet_name"]
                                )
                                self.db.add(temp_mapping)
                                self.logger.debug(
                                    f"Created new temporary mapping: {mapping_data['original_item']}")

                            saved_count += 1

                        except Exception as e:
                            self.logger.error(
                                f"Error processing temporary mapping {mapping_data.get('original_item', 'unknown')}: {str(e)}")
                            continue

                    # Commit batch
                    self.db.commit()
                    self.logger.debug(
                        f"Committed batch of {len(batch)} temporary mappings")

                except Exception as e:
                    self.logger.error(f"Error committing batch: {str(e)}")
                    self.db.rollback()
                    # Continue with next batch instead of failing completely
                    continue

            self.logger.info(
                f"Saved {saved_count} temporary mappings to database")
            return saved_count

        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error saving temporary mappings: {str(e)}")
            return 0  # Return 0 instead of raising to prevent process from hanging

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
        try:
            # Extract temporary mappings
            mappings = self.extract_temporary_mappings(df, sheet_name)
            if not mappings:
                return 0

            # Save to database with timeout protection
            saved_count = self.save_temporary_mappings(mappings)

            return saved_count

        except Exception as e:
            self.logger.error(
                f"Error in extract_and_save_from_dataframe for {sheet_name}: {str(e)}")
            return 0  # Return 0 instead of failing completely
        # --- Save all temporary mappings to JSON file ---
        try:
            # Query only VALID temporary mappings from the DB (exclude null values)
            valid_temp_mappings = self.db.query(TempItemMapping).filter(
                TempItemMapping.original_item.isnot(None),
                TempItemMapping.sheet_name.isnot(None)
            ).all()

            valid_temp_mappings_dicts = [
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
                for m in valid_temp_mappings
            ]
            # Ensure the directory exists
            output_path = os.path.join(
                os.path.dirname(__file__),
                '../../storage/fixtures/temp-item-mapping.json'
            )
            output_path = os.path.normpath(output_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            # Write to JSON file (only mappings, no statistics) with UTF-8 encoding for Windows compatibility
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(
                    valid_temp_mappings_dicts, f, indent=2, ensure_ascii=False
                )
            self.logger.info(
                f"Exported {len(valid_temp_mappings_dicts)} valid temporary mappings to {output_path}"
            )

            # Update statistics in the separate stats file
            try:
                stats_manager = MappingStatsManager()
                stats_manager.update_temp_mapping_stats({
                    "total_mappings": len(valid_temp_mappings_dicts),
                    "unique_sheets": len(set(m.sheet_name for m in valid_temp_mappings if m.sheet_name)),
                    "sheet_names": list(set(m.sheet_name for m in valid_temp_mappings if m.sheet_name)),
                    "mappings_per_sheet": {}
                })
                stats_manager.update_sync_times("temp_sync")
                self.logger.info(
                    "Updated temp mapping statistics in stats file")
            except Exception as stats_error:
                self.logger.error(
                    f"Error updating stats file: {str(stats_error)}")
                # Don't raise here as the main operation succeeded

        except Exception as e:
            self.logger.error(
                f"Failed to export temporary mappings to JSON: {e}"
            )
        return saved_count
