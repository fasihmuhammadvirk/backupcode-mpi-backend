#!/usr/bin/env python3
"""
Complete Temporary Mapping Sync Script

This script performs a complete temporary mapping workflow:
1. Extracts temporary mappings from Google Sheets
2. Saves them to a JSON file for backup/reference
3. Stores them in the database (temporary_item_mappings table)
4. Updates all invoice items with the temporary mappings

Usage:
    python scripts/complete_temporary_mapping_sync.py [options]

Options:
    --dry-run           : Show what would be done without making changes
    --sheet-id SHEET_ID : Custom Google Sheet ID (optional)
    --api-key API_KEY   : Custom Google API key (optional)
    --skip-sheets NAMES : Comma-separated list of sheet names to skip
    --output-file PATH  : Custom output JSON file path
    --batch-size SIZE   : Batch size for processing (default: 100)
    --stats-only        : Only show statistics without making changes
    --analyze-conflicts : Analyze mapping conflicts across suppliers

Examples:
    # Full sync with default settings
    python scripts/complete_temporary_mapping_sync.py
    
    # Dry run to see what would happen
    python scripts/complete_temporary_mapping_sync.py --dry-run
    
    # Use custom sheet ID
    python scripts/complete_temporary_mapping_sync.py \
        --sheet-id "your_sheet_id"
    
    # Just show statistics
    python scripts/complete_temporary_mapping_sync.py --stats-only
    
    # Analyze potential conflicts
    python scripts/complete_temporary_mapping_sync.py --analyze-conflicts
"""

import sys
import os
import argparse
import logging
import time
import json
from datetime import datetime
from typing import Dict, List, Any
from collections import defaultdict

# Add the project root to the Python path FIRST
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..')
))

# Now import mpi_backend modules
from mpi_backend.database import get_db
from mpi_backend.utils.sync_mapping.temporary_mapping_sync import (
    TemporaryMappingSync
)
from mpi_backend.utils.google_sheets.temporary_mapping_extractor import (
    TemporaryMappingExtractor
)
from mpi_backend.utils.sync_mapping.temporary_mapping_updater import (
    TemporaryMappingUpdater
)
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.config.spreadsheet_config import (
    DEFAULT_SHEET_ID,
    GOOGLE_API_KEY,
    SKIP_SHEETS
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('temp_mapping_sync.log')
    ]
)
logger = logging.getLogger(__name__)


class CompleteTempMappingSync:
    """Complete temporary mapping synchronization workflow."""
    
    def __init__(self, db_session):
        """Initialize the sync manager."""
        self.db = db_session
        self.temp_sync = TemporaryMappingSync(db_session)
        self.temp_extractor = TemporaryMappingExtractor(db_session)
        self.temp_updater = TemporaryMappingUpdater(db_session)
        
    def run_complete_sync(
        self,
        sheet_id: str = None,
        api_key: str = None,
        skip_sheets: List[str] = None,
        output_file: str = None,
        dry_run: bool = False,
        batch_size: int = 100,
        stats_only: bool = False,
        analyze_conflicts: bool = False
    ) -> Dict[str, Any]:
        """Run the complete temporary mapping sync workflow."""
        start_time = time.time()
        
        logger.info("="*80)
        logger.info("COMPLETE TEMPORARY MAPPING SYNC")
        logger.info("="*80)
        mode_desc = (
            'DRY RUN' if dry_run else (
                'STATS ONLY' if stats_only else (
                    'CONFLICT ANALYSIS' if analyze_conflicts else 'LIVE SYNC'
                )
            )
        )
        logger.info("Mode: %s", mode_desc)
        sheet_id_str = sheet_id or DEFAULT_SHEET_ID
        logger.info("Sheet ID: %s", sheet_id_str)
        timestamp_str = datetime.now().isoformat()
        logger.info("Timestamp: %s", timestamp_str)
        logger.info("-" * 80)
        
        try:
            # Step 0: Get initial statistics
            initial_stats = self._get_comprehensive_stats()
            logger.info("INITIAL STATE:")
            self._log_stats(initial_stats)
            
            if stats_only:
                logger.info("Stats-only mode - exiting without changes")
                return {
                    "success": True,
                    "mode": "stats_only",
                    "initial_stats": initial_stats,
                    "total_time": round(time.time() - start_time, 2)
                }
            
            if analyze_conflicts:
                logger.info(
                    "Analyzing potential mapping conflicts"
                )
                conflict_analysis = self._analyze_mapping_conflicts()
                return {
                    "success": True,
                    "mode": "conflict_analysis",
                    "initial_stats": initial_stats,
                    "conflict_analysis": conflict_analysis,
                    "total_time": round(time.time() - start_time, 2)
                }
            
            # Step 1: Extract temporary mappings from Google Sheets
            logger.info(
                "STEP 1: EXTRACTING TEMPORARY MAPPINGS FROM "
                "GOOGLE SHEETS"
            )
            logger.info("-" * 60)
            
            extraction_result = self._extract_mappings_from_sheets(
                sheet_id=sheet_id or DEFAULT_SHEET_ID,
                api_key=api_key or GOOGLE_API_KEY,
                skip_sheets=skip_sheets or SKIP_SHEETS,
                dry_run=dry_run
            )
            
            if not extraction_result["success"]:
                logger.error(
                    "Extraction failed: %s",
                    extraction_result['message']
                )
                return extraction_result
            
            # Step 2: Save to JSON file
            logger.info("\nSTEP 2: SAVING TO JSON FILE")
            logger.info("-"*60)
            
            json_result = self._save_to_json_file(
                output_file=output_file,
                dry_run=dry_run
            )
            
            # Step 3: Update invoice items with enhanced conflict detection
            logger.info(
                "STEP 3: UPDATING INVOICE ITEMS (WITH CONFLICT "
                "DETECTION)"
            )
            logger.info("-" * 60)
            
            update_result = self._update_invoice_items(dry_run=dry_run)
            
            # Step 4: Get final statistics
            final_stats = self._get_comprehensive_stats()
            
            # Calculate changes
            changes = self._calculate_changes(initial_stats, final_stats)
            
            total_time = time.time() - start_time
            
            # Final summary
            logger.info("\n" + "="*80)
            logger.info("SYNC COMPLETE - SUMMARY")
            logger.info("="*80)
            logger.info(
                "Total execution time: %.2fs",
                total_time
            )
            temp_map_count = extraction_result.get(
                'total_mappings_extracted', 0
            )
            logger.info(
                "Temporary mappings extracted: %s", str(temp_map_count)
            )
            logger.info(
                "Mappings saved to database: %s", str(temp_map_count)
            )
            json_status = 'Updated' if json_result['success'] else 'Failed'
            logger.info("JSON file: %s", json_status)
            invoice_updated = update_result.get('items_updated', 0)
            logger.info("Invoice items updated: %s", str(invoice_updated))
            warnings_count = update_result.get('warnings_count', 0)
            if warnings_count > 0:
                logger.warning(
                    "Mapping conflicts detected: %s", str(warnings_count)
                )
            skipped_count = update_result.get('skipped_count', 0)
            if skipped_count > 0:
                logger.info(
                    "Items skipped for safety: %s", str(skipped_count)
                )
            mapped_items_change = changes.get('mapped_items_change', 0)
            logger.info(
                "Net change in mapped items: +%s", str(mapped_items_change)
            )
            
            return {
                "success": True,
                "mode": "dry_run" if dry_run else "live_sync",
                "total_time": round(total_time, 2),
                "extraction_result": extraction_result,
                "json_result": json_result,
                "update_result": update_result,
                "initial_stats": initial_stats,
                "final_stats": final_stats,
                "changes": changes
            }
            
        except Exception as e:
            logger.error("Critical error in complete sync: %s", str(e))
            return {
                "success": False,
                "error": str(e),
                "total_time": round(time.time() - start_time, 2)
            }
    
    def _analyze_mapping_conflicts(self) -> Dict[str, Any]:
        """Analyze potential mapping conflicts across suppliers."""
        try:
            logger.info("Analyzing potential mapping conflicts")
            logger.info("-"*60)
            
            # Get all temporary mappings grouped by item
            temp_mappings = self.temp_updater.get_temporary_mappings_with_supplier_context()
            
            # Find items with multiple sheet assignments
            conflicts = {}
            multi_sheet_items = 0
            total_conflicts = 0
            
            for item_code, sheet_options in temp_mappings.items():
                if len(sheet_options) > 1:
                    multi_sheet_items += 1
                    unique_sheets = set(opt['sheet_name'] for opt in sheet_options)
                    
                    if len(unique_sheets) > 1:
                        total_conflicts += 1
                        conflicts[item_code] = {
                            'sheets': list(unique_sheets),
                            'count': len(sheet_options),
                            'details': sheet_options
                        }
            
            # Get invoice items that might be affected
            affected_invoice_items = []
            if conflicts:
                conflict_items = list(conflicts.keys())
                affected_invoice_items = self.db.query(InvoiceItem).filter(
                    InvoiceItem.item.in_(conflict_items)
                ).all()
            
            # Organize affected items by supplier
            supplier_impact = defaultdict(list)
            for item in affected_invoice_items:
                supplier_id, supplier_name = self.temp_updater._extract_supplier_id(item.vendor)
                if item.item in conflicts:
                    supplier_impact[supplier_name].append({
                        'item_code': item.item,
                        'current_sheet': item.sheet_name or 'None',
                        'potential_sheets': conflicts[item.item]['sheets'],
                        'mpi_status': item.mpi_item or 'None'
                    })
            
            # Log analysis results
            logger.info(
                "Analysis Results:"
            )
            logger.info(
                "   Total unique items: %s",
                str(len(temp_mappings))
            )
            logger.info(
                "   Items with multiple entries: %s",
                str(multi_sheet_items)
            )
            logger.info(
                "   Items with conflicting sheets: %s",
                str(total_conflicts)
            )
            logger.info(
                "   Affected invoice items: %s",
                str(len(affected_invoice_items))
            )
            logger.info(
                "   Affected suppliers: %s",
                str(len(supplier_impact))
            )
            
            if total_conflicts > 0:
                logger.warning("\nTOP MAPPING CONFLICTS:")
                sorted_conflicts = sorted(conflicts.items(), key=lambda x: len(x[1]['sheets']), reverse=True)
                for i, (item_code, conflict_info) in enumerate(sorted_conflicts[:10]):
                    sheets_str = str(conflict_info['sheets'])
                    if len(sheets_str) > 60:
                        logger.warning(
                            "   %d. '%s' ->", i + 1, item_code
                        )
                        logger.warning("      %s", sheets_str)
                    else:
                        logger.warning(
                            "   %d. '%s' -> %s",
                            i + 1, item_code, sheets_str
                        )
            
            if supplier_impact:
                logger.info("\nSUPPLIER IMPACT SUMMARY:")
                for supplier, items in supplier_impact.items():
                    logger.info(f"   {supplier}: {len(items)} affected items")
            
            return {
                "total_items": len(temp_mappings),
                "multi_sheet_items": multi_sheet_items,
                "conflict_items": total_conflicts,
                "affected_invoice_items": len(affected_invoice_items),
                "affected_suppliers": len(supplier_impact),
                "conflicts": conflicts,
                "supplier_impact": dict(supplier_impact)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing conflicts: {str(e)}")
            return {
                "error": str(e),
                "total_items": 0,
                "conflict_items": 0
            }
    
    def _extract_mappings_from_sheets(
        self,
        sheet_id: str,
        api_key: str,
        skip_sheets: List[str],
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Extract temporary mappings from Google Sheets."""
        try:
            if dry_run:
                logger.info("DRY RUN: Would extract temporary mappings from Google Sheets")
            
            logger.info(f"Connecting to Google Sheet: {sheet_id}")
            logger.info(f"Skipping sheets: {skip_sheets}")
            
            # Use the existing extraction functionality
            result = self.temp_sync.extract_temporary_mappings_from_sheets(
                sheet_id=sheet_id,
                api_key=api_key,
                skip_sheets=skip_sheets
            )
            
            if result["success"]:
                logger.info(f"Successfully extracted {result['total_mappings_extracted']} temporary mappings")
                logger.info(f"Processed {result['sheets_processed']} sheets")
            else:
                logger.error(f"Extraction failed: {result['message']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting from sheets: {str(e)}")
            return {
                "success": False,
                "message": f"Extraction error: {str(e)}",
                "total_mappings_extracted": 0,
                "sheets_processed": 0
            }
    
    def _save_to_json_file(
        self,
        output_file: str = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Save all temporary mappings to JSON file."""
        try:
            # Default output file path
            if not output_file:
                output_file = os.path.join(
                    os.path.dirname(__file__),
                    '../mpi_backend/storage/fixtures/temp-item-mapping.json'
                )
            
            output_file = os.path.normpath(output_file)
            
            if dry_run:
                logger.info(f"DRY RUN: Would save temporary mappings to {output_file}")
                return {"success": True, "message": "Dry run - no file saved", "file_path": output_file}
            
            # Get all temporary mappings from database
            all_temp_mappings = self.db.query(TempItemMapping).all()
            
            # Convert to JSON-serializable format
            mappings_data = []
            for mapping in all_temp_mappings:
                mappings_data.append({
                    "id": mapping.id,
                    "original_item": mapping.original_item,
                    "original_description": mapping.original_description,
                    "sheet_name": mapping.sheet_name,
                    "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
                    "updated_at": mapping.updated_at.isoformat() if mapping.updated_at else None
                })
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # Write to JSON file with pretty formatting
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(mappings_data, f, indent=2, ensure_ascii=False)
            
            file_size = os.path.getsize(output_file)
            logger.info(f"Saved {len(mappings_data)} temporary mappings to {output_file}")
            logger.info(f"File size: {file_size:,} bytes")
            
            return {
                "success": True,
                "message": f"Saved {len(mappings_data)} mappings to JSON",
                "file_path": output_file,
                "mappings_count": len(mappings_data),
                "file_size": file_size
            }
            
        except Exception as e:
            logger.error(f"Error saving to JSON file: {str(e)}")
            return {
                "success": False,
                "message": f"JSON save error: {str(e)}",
                "file_path": output_file if 'output_file' in locals() else None
            }
    
    def _update_invoice_items(self, dry_run: bool = False) -> Dict[str, Any]:
        """Update invoice items with temporary mappings using enhanced conflict detection."""
        try:
            if dry_run:
                # In dry run, get stats but don't actually update
                stats = self.temp_updater.get_update_stats()
                logger.info("DRY RUN: Would update invoice items with temporary mappings")
                logger.info(f"Would check {stats['total_unmapped_items']} unmapped items")
                logger.info(f"Would update {stats['potential_matches']} items")
                if stats.get('potential_conflicts', 0) > 0:
                    logger.warning(f"Potential conflicts: {stats['potential_conflicts']}")
                return {
                    "success": True,
                    "message": "Dry run - no items updated",
                    "total_items_checked": stats['total_unmapped_items'],
                    "items_updated": 0,
                    "potential_updates": stats['potential_matches'],
                    "potential_conflicts": stats.get('potential_conflicts', 0)
                }
            
            # Perform actual updates with enhanced conflict detection
            result = self.temp_updater.update_invoice_items_with_temporary_mappings()
            
            if result["success"]:
                logger.info(f"Successfully updated {result['items_updated']} invoice items")
                logger.info(f"Checked {result['total_items_checked']} total items")
                
                if result.get('warnings_count', 0) > 0:
                    logger.warning(f"Mapping conflicts encountered: {result['warnings_count']}")
                
                if result.get('skipped_count', 0) > 0:
                    logger.info(f"Items skipped for safety: {result['skipped_count']}")
            else:
                logger.error(f"Update failed: {result['message']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error updating invoice items: {str(e)}")
            return {
                "success": False,
                "message": f"Invoice update error: {str(e)}",
                "total_items_checked": 0,
                "items_updated": 0,
                "warnings_count": 0,
                "skipped_count": 0
            }
    
    def _get_comprehensive_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the current state."""
        try:
            # Temporary mappings count
            temp_mappings_count = self.db.query(TempItemMapping).count()
            
            # Invoice items stats
            total_invoice_items = self.db.query(InvoiceItem).count()
            mapped_items = self.db.query(InvoiceItem).filter(
                InvoiceItem.sheet_name.isnot(None),
                InvoiceItem.sheet_name != ''
            ).count()
            unmapped_items = total_invoice_items - mapped_items
            
            # Temporary items (have sheet_name but are No Match or UIDI)
            from sqlalchemy import or_
            temporary_items = self.db.query(InvoiceItem).filter(
                InvoiceItem.sheet_name.isnot(None),
                InvoiceItem.sheet_name != '',
                or_(
                    InvoiceItem.mpi_item == 'No Match',
                    InvoiceItem.mpi_item.like('UIDI%'),
                    InvoiceItem.mpi_description == 'No Match',
                    InvoiceItem.mpi_description.like('UIDI%')
                )
            ).count()
            
            return {
                "temporary_mappings_in_db": temp_mappings_count,
                "total_invoice_items": total_invoice_items,
                "mapped_items": mapped_items,
                "unmapped_items": unmapped_items,
                "temporary_items": temporary_items,
                "mapping_percentage": round((mapped_items / total_invoice_items * 100), 2) if total_invoice_items > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Error getting stats: {str(e)}")
            return {
                "temporary_mappings_in_db": 0,
                "total_invoice_items": 0,
                "mapped_items": 0,
                "unmapped_items": 0,
                "temporary_items": 0,
                "mapping_percentage": 0
            }
    
    def _log_stats(self, stats: Dict[str, Any]):
        """Log statistics in a formatted way."""
        logger.info(f"Temporary mappings in database: {stats['temporary_mappings_in_db']:,}")
        logger.info(f"Total invoice items: {stats['total_invoice_items']:,}")
        logger.info(f"Mapped items: {stats['mapped_items']:,}")
        logger.info(f"Unmapped items: {stats['unmapped_items']:,}")
        logger.info(f"Temporary items: {stats['temporary_items']:,}")
        logger.info(f"Mapping percentage: {stats['mapping_percentage']:.2f}%")
    
    def _calculate_changes(self, initial: Dict[str, Any], final: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate changes between initial and final stats."""
        return {
            "temp_mappings_change": final["temporary_mappings_in_db"] - initial["temporary_mappings_in_db"],
            "mapped_items_change": final["mapped_items"] - initial["mapped_items"],
            "unmapped_items_change": final["unmapped_items"] - initial["unmapped_items"],
            "temporary_items_change": final["temporary_items"] - initial["temporary_items"],
            "mapping_percentage_change": final["mapping_percentage"] - initial["mapping_percentage"]
        }


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Complete Temporary Mapping Sync Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Full sync with defaults
  %(prog)s --dry-run                          # Show what would happen
  %(prog)s --sheet-id "your_sheet_id"         # Use custom sheet
  %(prog)s --stats-only                       # Just show statistics
  %(prog)s --analyze-conflicts                # Analyze mapping conflicts
  %(prog)s --skip-sheets "Sheet1,Sheet2"      # Skip specific sheets
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    parser.add_argument(
        '--sheet-id',
        type=str,
        help='Custom Google Sheet ID (default: from config)'
    )
    
    parser.add_argument(
        '--api-key',
        type=str,
        help='Custom Google API key (default: from config)'
    )
    
    parser.add_argument(
        '--skip-sheets',
        type=str,
        help='Comma-separated list of sheet names to skip'
    )
    
    parser.add_argument(
        '--output-file',
        type=str,
        help='Custom output JSON file path'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Batch size for processing (default: 100)'
    )
    
    parser.add_argument(
        '--stats-only',
        action='store_true',
        help='Only show statistics without making changes'
    )
    
    parser.add_argument(
        '--analyze-conflicts',
        action='store_true',
        help='Analyze potential mapping conflicts across suppliers'
    )
    
    return parser.parse_args()


def main():
    """Main execution function."""
    args = parse_arguments()
    
    # Process skip_sheets argument
    skip_sheets = None
    if args.skip_sheets:
        skip_sheets = [sheet.strip() for sheet in args.skip_sheets.split(',')]
    
    try:
        # Get database session
        with next(get_db()) as db:
            # Create sync manager
            sync_manager = CompleteTempMappingSync(db)
            
            # Run the complete sync
            result = sync_manager.run_complete_sync(
                sheet_id=args.sheet_id,
                api_key=args.api_key,
                skip_sheets=skip_sheets,
                output_file=args.output_file,
                dry_run=args.dry_run,
                batch_size=args.batch_size,
                stats_only=args.stats_only,
                analyze_conflicts=args.analyze_conflicts
            )
            
            # Exit with appropriate code
            if result["success"]:
                logger.info("Complete temporary mapping sync finished successfully!")
                sys.exit(0)
            else:
                logger.error(f"Sync failed: {result.get('error', 'Unknown error')}")
                sys.exit(1)
                
    except KeyboardInterrupt:
        logger.info("Sync interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
