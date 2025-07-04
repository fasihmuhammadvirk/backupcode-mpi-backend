#!/usr/bin/env python3
"""
Enhanced Google Sheet Data Extractor with intelligent mapping sheet processing.

This module provides enhanced functionality to extract and process data from
Google Sheets, with intelligent detection of Main Mapping and Temporary
Mapping sheets, automatic supplier detection, suffix cleaning, and robust
error handling.
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
from io import StringIO

# Import spreadsheet configuration
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID,
    GOOGLE_API_KEY
)

# Set up logging
logger = logging.getLogger(__name__)


class EnhancedGoogleSheetDataExtractor:
    """Enhanced extractor for Google Sheets with intelligent mapping detection."""
    
    def __init__(
        self,
        sheet_id: str = None,
        api_key: str = None,
        output_file: str = None,
        skip_sheets: list = None,
        batch_size: int = 100,
        fuzzy_threshold: int = 75
    ):
        """Initialize the enhanced extractor with optional configuration."""
        self.api_key = api_key or GOOGLE_API_KEY
        self.sheet_id = sheet_id or DEFAULT_SHEET_ID
        self.output_file = output_file
        self.skip_sheets = skip_sheets or []
        self.batch_size = batch_size
        self.fuzzy_threshold = fuzzy_threshold
        self.service = None
        
        # Compile regex patterns for efficiency
        self.suffix_pattern = re.compile(
            r'-[BWYS]$', re.IGNORECASE
        )
        self.supplier_pattern = re.compile(
            r'\(([^)]+)\)', re.IGNORECASE
        )
        
        # Invalid sheet patterns
        self.invalid_sheet_patterns = {
            'additional_fees': re.compile(r'additional\s*fees', re.IGNORECASE),
            'control_sheets': re.compile(r'^(AB|AC),', re.IGNORECASE),
            'summary_sheets': re.compile(r'summary|total|report', re.IGNORECASE)
        }
        
        # Column name variations for normalization
        self.column_variations = {
            'original_item': [
                'original item', 'orig item', 'original_item',
                'item code', 'supplier item'
            ],
            'mapped_item': [
                'mapped item', 'mpi code', 'mapped_item',
                'mpi item', 'target item'
            ],
            'description': [
                'description', 'desc', 'item description',
                'product description'
            ],
            'notes': [
                'notes', 'comments', 'note', 'comment',
                'remarks'
            ]
        }
        
    def _initialize_service(self):
        """Initialize Google Sheets service."""
        if not self.service:
            try:
                self.service = build('sheets', 'v4', developerKey=self.api_key)
                logger.info("Google Sheets service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Google Sheets service: {e}")
                raise
    
    def _clean_item_code(self, item_code: str) -> str:
        """
        Clean item code by removing suffixes like -B, -W, -Y, -S.
        
        Args:
            item_code: Raw item code
            
        Returns:
            Cleaned item code
        """
        if not item_code or not isinstance(item_code, str):
            return ""
        
        # Remove leading/trailing whitespace
        cleaned = item_code.strip()
        
        # Remove common suffixes
        cleaned = self.suffix_pattern.sub('', cleaned)
        
        # Remove extra whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        return cleaned
    
    def _extract_supplier_from_sheet_name(self, sheet_name: str) -> Optional[str]:
        """
        Extract supplier name from sheet name.
        
        Args:
            sheet_name: Name of the sheet
            
        Returns:
            Extracted supplier name or None
        """
        if not sheet_name:
            return None
        
        # Special handling for AC unmapped items sheet
        if "AC," in sheet_name and "ITEMS WITHOUT" in sheet_name:
            return "UNMAPPED_ITEMS"  # Special supplier for unmapped items
        
        # Remove parentheses and extract content
        match = self.supplier_pattern.search(sheet_name)
        if match:
            supplier = match.group(1).strip()
            
            # Map category sheets to main supplier
            if any(cat in supplier.upper() for cat in [
                'BLACK MALLEABLE', 'AIR FITTINGS', 'BITS', 'BLADES',
                'BOXES', 'BRASS', 'CAST IRON', 'CONTROLS', 'COPPER',
                'CPVC', 'PVC', 'VALVES', 'TOOLS', 'WELD FITTING',
                'DRAINAGE', 'DRINKING', 'DUCKTILE', 'FINISHINGS',
                'FIXTURES', 'FLANGES', 'GALV', 'GARDEN', 'GAS',
                'GASKETS', 'GAUGES', 'GROOVED', 'HANGERS',
                'HEAVY EQUIPMENT', 'HOT WATER', 'INJECTOR',
                'INSULATION', 'LIGHT EQUIPMENT', 'MISCELLANEOUS',
                'NDS', 'NIPPLES', 'NO-HUB', 'PEX', 'PIPE',
                'POLYPROPYLENE', 'RADIANT', 'SHOWER', 'SIGNS',
                'SLEEVES', 'SPACE', 'SPECIAL', 'SPRINKLER',
                'SSDS', 'STAINLESS', 'STEEL', 'SV', 'TAPE',
                'TAX', 'TESTING', 'TUB', 'VENT', 'WASTE',
                'WATER'
            ]):
                return "BMW_PLUMBING_SUPPLIES"
            
            # Clean up common prefixes/suffixes
            supplier = re.sub(r'^(Sheet|Tab|Page)\s*', '', supplier, flags=re.IGNORECASE)
            supplier = re.sub(r'\s*(Sheet|Tab|Page)$', '', supplier, flags=re.IGNORECASE)
            return supplier
        
        # If no parentheses, try to extract meaningful supplier name
        # Remove common sheet identifiers
        cleaned_name = re.sub(r'^(Sheet|Tab|Page)\s*', '', sheet_name, flags=re.IGNORECASE)
        cleaned_name = re.sub(r'\s*(Sheet|Tab|Page)$', '', cleaned_name, flags=re.IGNORECASE)
        
        # If it's a meaningful name (not just numbers or single letters)
        if len(cleaned_name) > 2 and not cleaned_name.isdigit():
            return cleaned_name.strip()
        
        return "UNKNOWN_SUPPLIER"
    
    def _is_valid_mapping_sheet(
        self, sheet_name: str, sheet_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """
        Check if a sheet is a valid mapping sheet.
        
        Args:
            sheet_name: Name of the sheet
            sheet_data: DataFrame containing sheet data
            
        Returns:
            Tuple of (is_valid, reason)
        """
        # Check for invalid sheet patterns
        for pattern_name, pattern in self.invalid_sheet_patterns.items():
            if pattern.search(sheet_name):
                return False, f"Matches invalid pattern: {pattern_name}"
        
        # Check if sheet is empty
        if sheet_data.empty or len(sheet_data) < 2:
            return False, "Sheet is empty or has insufficient data"
        
        # Check for headers that indicate it's not a mapping sheet
        if not sheet_data.columns.empty:
            headers = [str(col).lower() for col in sheet_data.columns]
            
            # Check for item1, item2 pattern (invalid for mapping)
            item_pattern = re.compile(r'^item\s*\d+$')
            if any(item_pattern.match(header) for header in headers):
                return (
                    False,
                    "Contains Item1, Item2 style headers (not mapping sheet)"
                )
        
        # Special handling for the AC sheet (unmapped items)
        if "AC," in sheet_name and "ITEMS WITHOUT" in sheet_name:
            has_original = self._find_column_by_variations(
                sheet_data, 'original_item'
            ) is not None
            if has_original:
                return True, "Valid unmapped items sheet"
        
        # For regular mapping sheets, look for both original and mapped columns
        has_original = self._find_column_by_variations(
            sheet_data, 'original_item'
        ) is not None
        has_mapped = self._find_column_by_variations(
            sheet_data, 'mapped_item'
        ) is not None
        
        # Check if this is a sheet with only MPI codes (category sheet)
        if has_mapped and not has_original:
            # These are category sheets with only MPI codes, not mapping sheets
            return False, "Category sheet with only MPI codes (no original items)"
        
        # For true mapping sheets, we need both original and mapped columns
        if not (has_original and has_mapped):
            return False, "No complete mapping columns found"
        
        return True, "Valid mapping sheet"
    
    def _normalize_column_name(self, column_name: str) -> str:
        """
        Normalize column name for consistent matching.
        
        Args:
            column_name: Raw column name
            
        Returns:
            Normalized column name
        """
        if not column_name or not isinstance(column_name, str):
            return ""
        
        normalized = str(column_name).lower().strip()
        normalized = re.sub(r'[^a-z0-9\s]', ' ', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def _find_column_by_variations(self, df: pd.DataFrame, column_type: str) -> Optional[str]:
        """
        Find column by checking variations of column names.
        
        Args:
            df: DataFrame to search
            column_type: Type of column to find
            
        Returns:
            Column name if found, None otherwise
        """
        if column_type not in self.column_variations:
            return None
        
        variations = self.column_variations[column_type]
        df_columns = [self._normalize_column_name(col) for col in df.columns]
        
        for variation in variations:
            normalized_variation = self._normalize_column_name(variation)
            
            # Exact match
            if normalized_variation in df_columns:
                original_index = df_columns.index(normalized_variation)
                return df.columns[original_index]
            
            # Partial match
            for i, col in enumerate(df_columns):
                if normalized_variation in col or col in normalized_variation:
                    return df.columns[i]
        
        return None
                
    def _extract_mapping_from_sheet(self, sheet_name: str, gid: str) -> List[Dict[str, Any]]:
        """
        Extract mapping data from a specific sheet.
        
        Args:
            sheet_name: Name of the sheet
            gid: Sheet GID
            
        Returns:
            List of extracted mapping items
        """
        extracted_items = []
        
        try:
            # Get sheet data
            csv_url = f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export?format=csv&gid={gid}"
            response = requests.get(csv_url, timeout=30)
            response.raise_for_status()
            
            # Parse CSV data
            df = pd.read_csv(StringIO(response.text))
            
            # Validate sheet
            is_valid, reason = self._is_valid_mapping_sheet(sheet_name, df)
            if not is_valid:
                logger.info(f"Skipping sheet '{sheet_name}': {reason}")
                return extracted_items
            
            # Extract supplier name
            supplier_name = self._extract_supplier_from_sheet_name(sheet_name)
            if not supplier_name:
                logger.warning(f"Could not extract supplier name from sheet: {sheet_name}")
                return extracted_items
            
            # Find column mappings
            original_col = self._find_column_by_variations(df, 'original_item')
            mapped_col = self._find_column_by_variations(df, 'mapped_item')
            description_col = self._find_column_by_variations(df, 'description')
            notes_col = self._find_column_by_variations(df, 'notes')
            
            logger.info(
                f"Processing sheet '{sheet_name}' - Found columns: "
                f"original={original_col}, mapped={mapped_col}, "
                f"description={description_col}, notes={notes_col}"
            )
            
            # Process each row
            valid_items = 0
            for idx, row in df.iterrows():
                try:
                    # Extract data
                    original_item = ""
                    mapped_item = ""
                    description = ""
                    notes = ""
                    
                    if original_col and not pd.isna(row[original_col]):
                        original_item = str(row[original_col]).strip()
                    
                    if mapped_col and not pd.isna(row[mapped_col]):
                        mapped_item = str(row[mapped_col]).strip()
                    
                    if description_col and not pd.isna(row[description_col]):
                        description = str(row[description_col]).strip()
                    
                    if notes_col and not pd.isna(row[notes_col]):
                        notes = str(row[notes_col]).strip()
                    
                    # Skip if both original and mapped are empty
                    if not original_item and not mapped_item:
                        continue
                            
                    # Clean original item code
                    original_item_cleaned = self._clean_item_code(original_item)
                        
                    # Skip if cleaned original item is empty
                    if not original_item_cleaned:
                        continue
                        
                    # Determine if this is a temporary mapping
                    is_temporary = "temporary" in sheet_name.lower() or "temp" in sheet_name.lower()
                    
                    # Create mapping item
                    mapping_item = {
                        'original_item_code': original_item,
                        'original_item_code_cleaned': original_item_cleaned,
                        'mapped_item_code': mapped_item,
                        'description': description,
                        'supplier_name': supplier_name,
                        'source_sheet_name': sheet_name,
                        'notes': notes,
                        'mapping_type': 'temporary' if is_temporary else 'permanent',
                        'row_index': idx + 1,
                        'extracted_at': time.time()
                    }
                    
                    # Validate mapping (original != mapped if both exist)
                    if original_item_cleaned and mapped_item and original_item_cleaned.lower() == mapped_item.lower():
                        logger.warning(
                            f"Skipping self-mapping in {sheet_name} row {idx + 1}: "
                            f"{original_item_cleaned}"
                        )
                        continue
                        
                    extracted_items.append(mapping_item)
                    valid_items += 1
                    
                except Exception as e:
                    logger.warning(f"Error processing row {idx + 1} in sheet {sheet_name}: {e}")
                    continue
            
            logger.info(
                f"Extracted {valid_items} valid mappings from sheet: {sheet_name}"
            )
        except Exception as e:
            logger.error(
                f"Error extracting data from sheet {sheet_name}: {e}"
            )
        
        return extracted_items

    def get_sheet_list(self) -> List[Dict[str, str]]:
        """Get list of all sheets in the spreadsheet."""
        self._initialize_service()
        
        try:
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=self.sheet_id
            ).execute()
            
            sheets = []
            for sheet in spreadsheet.get('sheets', []):
                properties = sheet.get('properties', {})
                sheets.append({
                    'title': properties.get('title', ''),
                    'gid': str(properties.get('sheetId', ''))
                })
            
            logger.info(
                f"Found {len(sheets)} sheets in spreadsheet"
            )
            return sheets
                
        except Exception as e:
            logger.error(f"Error getting sheet list: {e}")
            return []

    def process_all_mapping_sheets(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Process all mapping sheets from the spreadsheet.
        
        Args:
            dry_run: If True, shows what would be extracted without committing
        
        Returns:
            Dictionary with extraction results
        """
        logger.info("Starting enhanced mapping sheet extraction...")
        
        if dry_run:
            logger.info("DRY RUN MODE: No data will be committed")
        
        # Get all sheets
        sheets = self.get_sheet_list()
        if not sheets:
            return {'success': False, 'error': 'No sheets found'}
        
        # Statistics
        stats = {
            'total_sheets': len(sheets),
            'valid_sheets': 0,
            'invalid_sheets': 0,
            'total_mappings': 0,
            'permanent_mappings': 0,
            'temporary_mappings': 0,
            'skipped_sheets': [],
            'processed_sheets': [],
            'errors': []
        }
        
        all_mappings = []
        
        # Process each sheet
        for sheet in sheets:
            sheet_title = sheet.get('title', '')
            gid = sheet.get('gid', '')
            
            if not sheet_title or not gid:
                stats['invalid_sheets'] += 1
                stats['skipped_sheets'].append({
                    'name': sheet_title,
                    'reason': 'Missing title or GID'
                })
                continue
            
            logger.info(f"Processing sheet: {sheet_title}")
            
            try:
                # Extract mappings from sheet
                mappings = self._extract_mapping_from_sheet(sheet_title, gid)
                
                if mappings:
                    stats['valid_sheets'] += 1
                    stats['total_mappings'] += len(mappings)
                    
                    # Count mapping types
                    for mapping in mappings:
                        if mapping.get('mapping_type') == 'temporary':
                            stats['temporary_mappings'] += 1
                        else:
                            stats['permanent_mappings'] += 1
                    
                    all_mappings.extend(mappings)
                    stats['processed_sheets'].append({
                        'name': sheet_title,
                        'mappings_count': len(mappings),
                        'supplier': mappings[0].get('supplier_name', 'Unknown') if mappings else 'Unknown'
                    })
                else:
                    stats['invalid_sheets'] += 1
                    stats['skipped_sheets'].append({
                        'name': sheet_title,
                        'reason': 'No valid mappings found'
                    })
                
            except Exception as e:
                logger.error(f"Error processing sheet {sheet_title}: {e}")
                stats['invalid_sheets'] += 1
                stats['errors'].append({
                    'sheet': sheet_title,
                    'error': str(e)
                })
        
        # Save results if not dry run
        if not dry_run:
            output_file = "mpi_backend/storage/fixtures/enhanced-mapping-extraction.json"
            try:
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(all_mappings, f, indent=2, ensure_ascii=False, default=str)
                logger.info(
                    f"Results saved to: {output_file}"
                )
            except Exception as e:
                logger.error(f"Error saving results: {e}")
                stats['errors'].append({'error': f'Failed to save results: {e}'})
        
        # Log final statistics
        logger.info("\n" + "=" * 80)
        logger.info("ENHANCED MAPPING EXTRACTION COMPLETED")
        logger.info("=" * 80)
        logger.info(f"Total Sheets: {stats['total_sheets']}")
        logger.info(f"Valid Sheets: {stats['valid_sheets']}")
        logger.info(f"Invalid/Skipped Sheets: {stats['invalid_sheets']}")
        logger.info(f"Total Mappings Extracted: {stats['total_mappings']}")
        logger.info(f"Permanent Mappings: {stats['permanent_mappings']}")
        logger.info(f"Temporary Mappings: {stats['temporary_mappings']}")
        
        if stats['processed_sheets']:
            logger.info("\nProcessed Sheets:")
            for sheet_info in stats['processed_sheets']:
                logger.info(f"  - {sheet_info['name']}: {sheet_info['mappings_count']} mappings ({sheet_info['supplier']})")
        
        if stats['skipped_sheets']:
            logger.info("\nSkipped Sheets:")
            for skip_info in stats['skipped_sheets']:
                logger.info(f"  - {skip_info['name']}: {skip_info['reason']}")
        
        if stats['errors']:
            logger.warning("\nErrors:")
            for error_info in stats['errors']:
                if 'sheet' in error_info:
                    logger.warning(f"  - {error_info['sheet']}: {error_info['error']}")
                else:
                    logger.warning(f"  - {error_info['error']}")
        
        logger.info("=" * 80)
        
        return {
            'success': True,
            'stats': stats,
            'mappings': all_mappings if dry_run else [],
            'dry_run': dry_run
        }
    
    def process_all_sheets(self) -> Dict[str, Any]:
        """Legacy method for backward compatibility."""
        logger.warning("Using legacy process_all_sheets method. Consider using process_all_mapping_sheets.")
        return self.process_all_mapping_sheets(dry_run=False)


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