"""
Sheet Name Manager Utility

This module provides utilities for syncing Google Sheet metadata and managing
canonical sheet names across the application.
"""

import logging
from typing import Optional, Dict, List, Any
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from mpi_backend.database.controllers.google_sheet_metadata_controller import (
    GoogleSheetMetadataController
)
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
from mpi_backend.config.spreadsheet_config import DEFAULT_SHEET_ID, GOOGLE_API_KEY

logger = logging.getLogger(__name__)


class SheetNameManager:
    """Manager for Google Sheet name synchronization and canonical name lookups."""

    def __init__(self, db_session: Session, spreadsheet_id: str = None, api_key: str = None):
        """
        Initialize the SheetNameManager.

        Args:
            db_session: SQLAlchemy database session
            spreadsheet_id: Google Spreadsheet ID (defaults to config)
            api_key: Google API key (defaults to config)
        """
        self.db = db_session
        self.spreadsheet_id = spreadsheet_id or DEFAULT_SHEET_ID
        self.api_key = api_key or GOOGLE_API_KEY
        self.controller = GoogleSheetMetadataController(db_session)

    def sync_sheet_metadata_from_google(self) -> Dict[str, Any]:
        """
        Fetch all sheets from Google Sheets API and sync to metadata table.

        Returns:
            Dictionary with sync results and statistics
        """
        try:
            logger.info(f"Syncing sheet metadata from Google Sheets: {self.spreadsheet_id}")

            # Fetch sheets from Google Sheets API
            sheets = self._fetch_sheets_from_google()

            if not sheets:
                logger.warning("No sheets found in Google Spreadsheet")
                return {
                    "success": False,
                    "message": "No sheets found",
                    "synced_count": 0
                }

            # Bulk upsert to database
            synced_count = self.controller.bulk_upsert_sheets(
                sheets_list=sheets,
                spreadsheet_id=self.spreadsheet_id
            )

            logger.info(f"Successfully synced {synced_count} sheets to metadata table")

            return {
                "success": True,
                "message": f"Synced {synced_count} sheets",
                "synced_count": synced_count,
                "sheets": sheets
            }

        except Exception as e:
            logger.error(f"Error syncing sheet metadata: {str(e)}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "synced_count": 0
            }

    def _fetch_sheets_from_google(self) -> List[Dict[str, str]]:
        """
        Fetch sheet list from Google Sheets API.

        Returns:
            List of dictionaries with 'title' and 'gid' keys
        """
        try:
            service = build('sheets', 'v4', developerKey=self.api_key)
            spreadsheet = service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()

            sheets = []
            for sheet in spreadsheet.get('sheets', []):
                sheet_props = sheet.get('properties', {})
                sheets.append({
                    'title': sheet_props.get('title', ''),
                    'gid': str(sheet_props.get('sheetId', ''))
                })

            logger.info(f"Fetched {len(sheets)} sheets from Google API")
            return sheets

        except Exception as e:
            logger.error(f"Error fetching sheets from Google API: {str(e)}")
            raise

    def get_canonical_sheet_name(self, sheet_id: str) -> Optional[str]:
        """
        Look up the current canonical name for a sheet ID.

        Args:
            sheet_id: Google Sheets gid

        Returns:
            The canonical sheet name, or None if not found
        """
        return self.controller.get_canonical_name(sheet_id)

    def populate_missing_sheet_ids(
        self,
        extracted_mappings: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Populate sheet_id for existing database records by matching with fresh extraction.

        This method matches existing records by (mpi_code, supplier_id, supplier_item_ids)
        and updates them with the correct sheet_id from the extraction.
        
        For unmatched records, it uses fuzzy sheet name matching as a fallback.

        Args:
            extracted_mappings: List of mappings from fresh extraction (with sheet_id)

        Returns:
            Dictionary with update statistics
        """
        try:
            logger.info("Starting to populate missing sheet_ids in database records")

            updated_supplier_mappings = 0
            updated_temp_mappings = 0
            fuzzy_matched_count = 0
            unmatched_records = []

            # Create lookup dictionary from extraction: (mpi_code, supplier_id, supplier_item_ids) -> sheet_id
            extraction_lookup = {}
            for mapping in extracted_mappings:
                key = (
                    mapping.get('mpi_code'),
                    mapping.get('supplier_id'),
                    mapping.get('supplier_item_ids')
                )
                sheet_id = mapping.get('sheet_id')
                if all(key) and sheet_id:
                    extraction_lookup[key] = sheet_id

            logger.info(f"Built extraction lookup with {len(extraction_lookup)} entries")
            
            # Build sheet name to sheet_id mapping from metadata for fuzzy matching
            sheet_name_to_id = self.controller.get_all_sheet_mappings(self.spreadsheet_id)
            # Reverse it: name -> id
            name_to_id_map = {name: sid for sid, name in sheet_name_to_id.items()}
            
            logger.info(f"Built sheet name lookup with {len(name_to_id_map)} entries for fuzzy matching")

            # Update supplier_item_mappings
            supplier_records = self.db.query(ItemsMapping).filter(
                ItemsMapping.sheet_id.is_(None)
            ).all()

            for record in supplier_records:
                key = (record.mpi_code, record.supplier_id, record.supplier_item_ids)
                sheet_id = extraction_lookup.get(key)

                if sheet_id:
                    # Exact match found
                    record.sheet_id = sheet_id
                    updated_supplier_mappings += 1
                else:
                    # Try fuzzy matching by sheet name
                    matched_id = self._fuzzy_match_sheet_name(
                        record.google_sheet_name, 
                        name_to_id_map
                    )
                    if matched_id:
                        record.sheet_id = matched_id
                        updated_supplier_mappings += 1
                        fuzzy_matched_count += 1
                        logger.debug(
                            f"Fuzzy matched '{record.google_sheet_name}' to sheet_id {matched_id}"
                        )
                    else:
                        unmatched_records.append({
                            'table': 'supplier_item_mappings',
                            'id': record.id,
                            'mpi_code': record.mpi_code,
                            'sheet_name': record.google_sheet_name
                        })

            # Update temporary_item_mappings
            temp_records = self.db.query(TempItemMapping).filter(
                TempItemMapping.sheet_id.is_(None)
            ).all()

            # For temporary mappings, we match by (original_item, sheet_name)
            temp_extraction_lookup = {}
            for mapping in extracted_mappings:
                if mapping.get('mapping_type') == 'temporary':
                    temp_key = (
                        mapping.get('mpi_code'),  # This is original_item for temporary
                        mapping.get('google_sheet_name')
                    )
                    temp_sheet_id = mapping.get('sheet_id')
                    if all(temp_key) and temp_sheet_id:
                        temp_extraction_lookup[temp_key] = temp_sheet_id

            for record in temp_records:
                temp_key = (record.original_item, record.sheet_name)
                sheet_id = temp_extraction_lookup.get(temp_key)

                if sheet_id:
                    # Exact match found
                    record.sheet_id = sheet_id
                    updated_temp_mappings += 1
                else:
                    # Try fuzzy matching by sheet name
                    matched_id = self._fuzzy_match_sheet_name(
                        record.sheet_name,
                        name_to_id_map
                    )
                    if matched_id:
                        record.sheet_id = matched_id
                        updated_temp_mappings += 1
                        fuzzy_matched_count += 1
                        logger.debug(
                            f"Fuzzy matched '{record.sheet_name}' to sheet_id {matched_id}"
                        )
                    else:
                        unmatched_records.append({
                            'table': 'temporary_item_mappings',
                            'id': record.id,
                            'original_item': record.original_item,
                            'sheet_name': record.sheet_name
                        })

            # Commit all updates
            self.db.commit()

            logger.info(
                f"Populated sheet_ids: {updated_supplier_mappings} supplier mappings, "
                f"{updated_temp_mappings} temporary mappings "
                f"({fuzzy_matched_count} via fuzzy matching)"
            )

            if unmatched_records:
                logger.warning(f"{len(unmatched_records)} records could not be matched")

            return {
                "success": True,
                "updated_supplier_mappings": updated_supplier_mappings,
                "updated_temp_mappings": updated_temp_mappings,
                "fuzzy_matched_count": fuzzy_matched_count,
                "unmatched_count": len(unmatched_records),
                "unmatched_records": unmatched_records[:100]  # Limit to first 100
            }

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error populating sheet IDs: {str(e)}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "updated_supplier_mappings": 0,
                "updated_temp_mappings": 0
            }

    def update_all_sheet_names_to_canonical(self) -> Dict[str, Any]:
        """
        Update ALL records in mapping tables to use current canonical sheet names.
        
        This ensures that:
        1. ALL records with the same sheet_id have the SAME canonical name
        2. If a sheet is renamed in Google (e.g., "NO-HUB" → "NO-HUB FASIH"),
           ALL existing records are updated to the new name
        3. The system maintains consistency across all records

        For records with sheet_id, look up the canonical name from google_sheet_metadata.
        For records without sheet_id, keep current name and log for review.

        Returns:
            Dictionary with update statistics
        """
        try:
            logger.info("=" * 80)
            logger.info("UPDATING ALL RECORDS TO CANONICAL SHEET NAMES")
            logger.info("=" * 80)

            updated_supplier_mappings = 0
            updated_temp_mappings = 0
            skipped_no_sheet_id = 0
            updates_by_sheet = {}  # Track updates per sheet

            # Get all sheet mappings from metadata (current names from Google)
            sheet_mappings = self.controller.get_all_sheet_mappings(self.spreadsheet_id)

            if not sheet_mappings:
                logger.warning("No sheet mappings found in metadata table")
                return {
                    "success": False,
                    "message": "No sheet mappings available",
                    "updated_supplier_mappings": 0,
                    "updated_temp_mappings": 0
                }

            logger.info(f"Found {len(sheet_mappings)} canonical sheet names from Google")

            # Update supplier_item_mappings - ALL records with sheet_id
            logger.info("\nUpdating supplier_item_mappings...")
            supplier_records = self.db.query(ItemsMapping).filter(
                ItemsMapping.sheet_id.isnot(None)
            ).all()
            
            logger.info(f"Processing {len(supplier_records)} supplier records with sheet_id...")

            for record in supplier_records:
                canonical_name = sheet_mappings.get(record.sheet_id)
                
                if not canonical_name:
                    logger.warning(
                        f"No canonical name found for sheet_id {record.sheet_id} "
                        f"(record {record.id})"
                    )
                    continue
                
                # Update even if it's already correct to ensure consistency
                old_name = record.google_sheet_name
                if canonical_name != old_name:
                    logger.info(
                        f"  ✓ Record {record.id}: '{old_name}' → '{canonical_name}'"
                    )
                    record.google_sheet_name = canonical_name
                    updated_supplier_mappings += 1
                    
                    # Track updates by sheet
                    if canonical_name not in updates_by_sheet:
                        updates_by_sheet[canonical_name] = {'count': 0, 'old_names': set()}
                    updates_by_sheet[canonical_name]['count'] += 1
                    updates_by_sheet[canonical_name]['old_names'].add(old_name)

            # Update temporary_item_mappings - ALL records with sheet_id
            logger.info("\nUpdating temporary_item_mappings...")
            temp_records = self.db.query(TempItemMapping).filter(
                TempItemMapping.sheet_id.isnot(None)
            ).all()
            
            logger.info(f"Processing {len(temp_records)} temporary records with sheet_id...")

            for record in temp_records:
                canonical_name = sheet_mappings.get(record.sheet_id)
                
                if not canonical_name:
                    logger.warning(
                        f"No canonical name found for sheet_id {record.sheet_id} "
                        f"(record {record.id})"
                    )
                    continue
                
                old_name = record.sheet_name
                if canonical_name != old_name:
                    logger.info(
                        f"  ✓ Record {record.id}: '{old_name}' → '{canonical_name}'"
                    )
                    record.sheet_name = canonical_name
                    updated_temp_mappings += 1

            # Count records without sheet_id
            skipped_no_sheet_id = (
                self.db.query(ItemsMapping).filter(
                    ItemsMapping.sheet_id.is_(None)
                ).count() +
                self.db.query(TempItemMapping).filter(
                    TempItemMapping.sheet_id.is_(None)
                ).count()
            )

            # Commit all updates
            self.db.commit()

            # Print summary by sheet
            logger.info("\n" + "=" * 80)
            logger.info("UPDATES BY SHEET:")
            logger.info("=" * 80)
            for canonical_name, data in sorted(updates_by_sheet.items()):
                old_names_str = ', '.join(f"'{n}'" for n in sorted(data['old_names']))
                logger.info(
                    f"  {canonical_name}: {data['count']} records updated "
                    f"(from {old_names_str})"
                )

            logger.info("\n" + "=" * 80)
            logger.info("FINAL SUMMARY:")
            logger.info(f"  Supplier mappings updated: {updated_supplier_mappings}")
            logger.info(f"  Temporary mappings updated: {updated_temp_mappings}")
            logger.info(f"  Records without sheet_id (skipped): {skipped_no_sheet_id}")
            logger.info("=" * 80)

            if skipped_no_sheet_id > 0:
                logger.warning(
                    f"\n⚠️  {skipped_no_sheet_id} records still don't have sheet_id!"
                )
                logger.warning("   Run Phase 1 again with improved fuzzy matching.")

            return {
                "success": True,
                "updated_supplier_mappings": updated_supplier_mappings,
                "updated_temp_mappings": updated_temp_mappings,
                "skipped_no_sheet_id": skipped_no_sheet_id,
                "updates_by_sheet": updates_by_sheet
            }

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating to canonical names: {str(e)}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "updated_supplier_mappings": 0,
                "updated_temp_mappings": 0
            }

    def _fuzzy_match_sheet_name(
        self,
        sheet_name: str,
        name_to_id_map: Dict[str, str]
    ) -> Optional[str]:
        """
        FULLY DYNAMIC fuzzy matching - no hardcoded overrides.
        
        Strategy:
        1. Normalize and try exact match
        2. Use intelligent fuzzy similarity matching
        3. Compound category detection (NO-HUB, BLACK MALLEABLE, etc.)
        
        This handles ALL variations dynamically:
        - "(COPPER)" vs "COPPER" 
        - "(NO-HUB PIPE & FITTINGS)" vs "NO-HUB COUPLINGS"
        - "(BLACK MALLEABLE) (GAS)" vs "BLACK MALLEABLE GAS"
        
        Args:
            sheet_name: The sheet name to match
            name_to_id_map: Dictionary mapping canonical names to sheet IDs
            
        Returns:
            Matched sheet_id or None if no good match found
        """
        if not sheet_name:
            return None
            
        # Normalize the input sheet name
        normalized_input = self._normalize_sheet_name(sheet_name)
        
        best_match_id = None
        best_score = 0
        
        for canonical_name, sheet_id in name_to_id_map.items():
            normalized_canonical = self._normalize_sheet_name(canonical_name)
            
            # Exact match after normalization
            if normalized_input == normalized_canonical:
                return sheet_id
            
            # Calculate similarity score
            score = self._calculate_name_similarity(
                normalized_input,
                normalized_canonical
            )
            
            if score > best_score and score >= 60:  # 60% threshold for flexibility
                best_score = score
                best_match_id = sheet_id
        
        if best_match_id:
            # Find the matched canonical name for logging
            matched_name = next(
                (name for name, sid in name_to_id_map.items() if sid == best_match_id),
                "Unknown"
            )
            logger.info(
                f"✓ Fuzzy matched '{sheet_name}' → '{matched_name}' "
                f"(sheet_id: {best_match_id}, score: {best_score:.1f})"
            )
        else:
            logger.warning(
                f"✗ No fuzzy match found for '{sheet_name}' (best score: {best_score:.1f})"
            )
            
        return best_match_id

    def _normalize_sheet_name(self, name: str) -> str:
        """
        100% DYNAMIC normalization - NO hardcoded abbreviations.
        
        Normalizes sheet name by:
        - Removing parentheses: (COPPER) -> COPPER
        - Removing punctuation: GALV. -> GALV
        - Converting & to AND
        - Converting hyphens/underscores to spaces
        - Uppercasing
        - Collapsing multiple spaces
        """
        if not name:
            return ""
            
        # Remove parentheses
        normalized = name.replace('(', '').replace(')', '')
        
        # Remove punctuation (except spaces, hyphens, underscores)
        import string
        normalized = ''.join(
            c if c not in string.punctuation or c in [' ', '-', '_'] 
            else ' ' 
            for c in normalized
        )
        
        # Normalize special characters
        normalized = normalized.replace('&', 'AND')
        normalized = normalized.replace('-', ' ')
        normalized = normalized.replace('_', ' ')
        
        # Uppercase and collapse spaces
        normalized = ' '.join(normalized.split()).upper()
        
        return normalized

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """
        100% DYNAMIC similarity calculation - NO hardcoded categories.
        
        Pure algorithmic approach:
        1. Exact match = 100
        2. Substring match = high score
        3. Multi-word overlap = very high score (for compound names)
        4. Word overlap (Jaccard) = medium-high score
        5. Partial word overlap = lower score
        
        Returns:
            Similarity score from 0-100
        """
        if not name1 or not name2:
            return 0.0
            
        # Strategy 1: Exact match after normalization
        if name1 == name2:
            return 100.0
            
        # Strategy 2: Substring containment
        if name1 in name2 or name2 in name1:
            # Calculate containment ratio
            shorter = min(len(name1), len(name2))
            longer = max(len(name1), len(name2))
            containment_ratio = shorter / longer
            return 85.0 + (containment_ratio * 15)  # 85-100 score
        
        # Split into words for analysis
        words1 = set(name1.split())
        words2 = set(name2.split())
        
        if not words1 or not words2:
            return 0.0
        
        # Strategy 3: Multi-word overlap (for compound categories)
        # If they share 2+ consecutive important words, very high match
        # This handles "NO-HUB X" vs "NO-HUB Y" → both have NO-HUB
        intersection = words1.intersection(words2)
        
        if len(intersection) >= 2:
            # Share 2 or more words - very likely same category
            # Examples:
            # - "NO HUB COUPLINGS" & "NO HUB PIPE FITTINGS" → share {NO, HUB}
            # - "BLACK MALLEABLE GAS" & "BLACK MALLEABLE" → share {BLACK, MALLEABLE}
            # - "COPPER PRESS" & "COPPER" → share {COPPER} (only 1, handled below)
            
            # Calculate what % of the SHORTER name's words are shared
            shorter_word_count = min(len(words1), len(words2))
            overlap_ratio = len(intersection) / shorter_word_count
            
            if overlap_ratio >= 0.5:  # 50% or more words match
                # Strong match
                base_score = 80.0
                # Bonus: more shared words = higher score
                word_bonus = (len(intersection) / max(len(words1), len(words2))) * 20
                return min(base_score + word_bonus, 98.0)
        
        # Strategy 4: Single meaningful word overlap
        # If they share 1 important word AND have similar word counts
        if len(intersection) >= 1:
            # Check if word counts are similar (within 3 words)
            word_count_diff = abs(len(words1) - len(words2))
            
            if word_count_diff <= 3:
                # Similar complexity, share at least 1 word
                overlap_ratio = len(intersection) / min(len(words1), len(words2))
                
                if overlap_ratio >= 0.4:  # 40% overlap
                    return 75.0 + (overlap_ratio * 15)  # 75-90 score
        
        # Strategy 5: Jaccard similarity (word set overlap)
        union = words1.union(words2)
        jaccard_score = (len(intersection) / len(union)) * 100
        
        # Strategy 6: Dice coefficient (alternative similarity measure)
        dice_score = (2 * len(intersection) / (len(words1) + len(words2))) * 100
        
        # Combine scores - weighted toward higher values
        final_score = max(jaccard_score, dice_score)
        
        return min(final_score, 100.0)

