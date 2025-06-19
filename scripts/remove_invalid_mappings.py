#!/usr/bin/env python3
"""
Remove Invalid Mappings Script

This script removes invalid mappings that were incorrectly extracted from:
- Columns with non-supplier headers (ADDITIONAL FEES, TOTAL, etc.)
- Columns with empty first two rows
- Invalid item patterns

Usage:
    python scripts/remove_invalid_mappings.py [--dry-run]
"""

import sys
import os
import json
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Set

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models import ItemsMapping, Supplier
from mpi_backend.utils.mapping_validators import is_temporary_mapping
from mpi_backend.config.logging_config import setup_logging

# Setup logging using existing app configuration
setup_logging()
logger = logging.getLogger('mpi_backend.scripts.cleanup_mappings')


# Patterns for invalid mappings
INVALID_PATTERNS = {
    'non_supplier_headers': [
        'additional fees', 'total', 'notes', 'comments', 'description',
        'size', 'item code', 'code', 'mpi', 'price', 'cost', 'amount',
        'quantity', 'qty', 'date', 'status', 'misc', 'miscellaneous',
        'fees', 'charges', 'shipping', 'delivery', 'freight', 'z,'
    ],
    'empty_column_indicators': [
        'unnamed:', 'column', 'untitled'
    ],
    'invalid_items': [
        'ship with uber asap', 'no match', 'n/a', 'na', 'none',
        'null', 'empty', 'total', 'subtotal', 'shipping', 'delivery',
        'freight', 'charge', 'fee', 'tax'
    ]
}


def check_mapping_validity(mapping: ItemsMapping) -> List[str]:
    """Check if a mapping is invalid and return reasons"""
    reasons = []

    # Check for temporary mappings
    if is_temporary_mapping(mapping.mpi_code, mapping.description):
        reasons.append('temporary_mapping')

    # Check sheet name for non-supplier headers
    if mapping.google_sheet_name:
        sheet_name_lower = mapping.google_sheet_name.lower()
        for pattern in INVALID_PATTERNS['non_supplier_headers']:
            if pattern in sheet_name_lower:
                reasons.append('non_supplier_column')
                break

    # Check for empty column indicators
    if mapping.google_sheet_name:
        sheet_name_lower = mapping.google_sheet_name.lower()
        for pattern in INVALID_PATTERNS['empty_column_indicators']:
            if pattern in sheet_name_lower:
                reasons.append('empty_column')
                break

    # Check supplier item IDs for invalid patterns
    if mapping.supplier_item_ids:
        item_lower = mapping.supplier_item_ids.lower().strip()
        for pattern in INVALID_PATTERNS['invalid_items']:
            if pattern in item_lower:
                reasons.append('invalid_pattern')
                break

    # Check for empty or very short supplier item IDs
    if (not mapping.supplier_item_ids or
            len(mapping.supplier_item_ids.strip()) < 2):
        reasons.append('empty_item_id')

    # Check for empty MPI codes
    if not mapping.mpi_code or len(mapping.mpi_code.strip()) < 2:
        reasons.append('empty_mpi_code')

    return reasons


def get_supplier_name(db, supplier_id: int) -> str:
    """Get supplier name by ID"""
    try:
        supplier = db.query(Supplier).filter_by(id=supplier_id).first()
        return (supplier.supplier_name if supplier
                else f"Unknown (ID: {supplier_id})")
    except Exception:
        return f"Unknown (ID: {supplier_id})"


def identify_invalid_mappings(db) -> List[Dict]:
    """Identify all invalid mappings in the database"""
    logger.info("🔍 Identifying invalid mappings...")

    invalid_mappings = []
    all_mappings = db.query(ItemsMapping).all()
    logger.info(f"Found {len(all_mappings)} total mappings in database")

    for mapping in all_mappings:
        reasons = check_mapping_validity(mapping)
        if reasons:
            invalid_mappings.append({
                'mapping': mapping,
                'reasons': reasons
            })

    logger.info(f"Found {len(invalid_mappings)} invalid mappings")
    return invalid_mappings


def remove_invalid_mappings_from_db(db, invalid_mappings: List[Dict],
                                    dry_run: bool = False) -> int:
    """Remove invalid mappings from database"""
    logger.info("🗑️ Removing invalid mappings from database...")

    removed_count = 0

    for item in invalid_mappings:
        mapping = item['mapping']
        reasons = item['reasons']

        supplier_name = get_supplier_name(db, mapping.supplier_id)

        logger.info(
            f"{'[DRY RUN] ' if dry_run else ''}Removing mapping: "
            f"'{mapping.supplier_item_ids}' -> '{mapping.mpi_code}' "
            f"(Supplier: {supplier_name}, "
            f"Sheet: {mapping.google_sheet_name}) "
            f"Reasons: {', '.join(reasons)}"
        )

        if not dry_run:
            try:
                db.delete(mapping)
                removed_count += 1
            except Exception as e:
                logger.error(f"Error removing mapping ID {mapping.id}: {e}")

    if not dry_run:
        try:
            db.commit()
            logger.info(f"Successfully removed {removed_count} mappings")
        except Exception as e:
            db.rollback()
            logger.error(f"Error committing database changes: {e}")
            removed_count = 0
    else:
        logger.info(f"[DRY RUN] Would remove {len(invalid_mappings)} mappings")

    return removed_count


def cleanup_json_file(json_file: str, invalid_items: Set[str],
                      dry_run: bool = False) -> int:
    """Clean up a specific JSON file"""
    logger.info(f"Processing {json_file}...")

    try:
        # Backup original file
        if not dry_run:
            backup_name = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = f"{json_file}.backup_{backup_name}"
            os.system(f"cp '{json_file}' '{backup_file}'")
            logger.info(f"Created backup: {backup_file}")

        # Read JSON file
        with open(json_file, 'r') as f:
            data = json.load(f)

        original_count = len(data)
        cleaned_data = []
        removed_count = 0

        for item in data:
            item_id = item.get('supplier_item_ids', '').strip()
            sheet_name = item.get('google_sheet_name', '').lower()
            mpi_code = item.get('mpi_code', '')
            description = item.get('description', '')

            should_remove = False
            removal_reason = ""

            # Check various invalid patterns
            if item_id in invalid_items:
                should_remove = True
                removal_reason = "matches database invalid mapping"
            elif is_temporary_mapping(mpi_code, description):
                should_remove = True
                removal_reason = "temporary mapping"
            elif any(pattern in sheet_name for pattern in
                     INVALID_PATTERNS['non_supplier_headers']):
                should_remove = True
                removal_reason = "non-supplier sheet name"
            elif (item_id and any(pattern in item_id.lower() for pattern in
                                  INVALID_PATTERNS['invalid_items'])):
                should_remove = True
                removal_reason = "invalid item pattern"

            if should_remove:
                logger.info(
                    f"{'[DRY RUN] ' if dry_run else ''}Removing from JSON: "
                    f"'{item_id}' -> '{mpi_code}' ({removal_reason})"
                )
                removed_count += 1
            else:
                cleaned_data.append(item)

        # Save cleaned data
        if not dry_run and removed_count > 0:
            with open(json_file, 'w') as f:
                json.dump(cleaned_data, f, indent=2)
            logger.info(f"Updated {json_file}: "
                       f"removed {removed_count}/{original_count} items")
        elif dry_run:
            logger.info(f"[DRY RUN] Would remove "
                       f"{removed_count}/{original_count} items from {json_file}")

        return removed_count

    except Exception as e:
        logger.error(f"Error processing {json_file}: {e}")
        return 0


def cleanup_json_files(invalid_mappings: List[Dict],
                       dry_run: bool = False) -> int:
    """Remove invalid mappings from JSON files"""
    logger.info("📁 Cleaning up JSON mapping files...")

    # Get set of invalid supplier item IDs
    invalid_items = set()
    for item in invalid_mappings:
        mapping = item['mapping']
        if mapping.supplier_item_ids:
            invalid_items.add(mapping.supplier_item_ids.strip())

    json_files = [
        'mpi_backend/storage/fixtures/item-mapping.json',
        'mpi_backend/storage/fixtures/temp-item-mapping.json'
    ]

    total_removed = 0
    for json_file in json_files:
        if os.path.exists(json_file):
            removed_count = cleanup_json_file(json_file, invalid_items, dry_run)
            total_removed += removed_count

    return total_removed


def generate_report(invalid_mappings: List[Dict], db_removed: int,
                    json_removed: int):
    """Generate cleanup report"""
    logger.info("\n" + "="*80)
    logger.info("CLEANUP REPORT")
    logger.info("="*80)

    # Count by reason
    reason_counts = {}
    supplier_breakdown = {}

    for item in invalid_mappings:
        mapping = item['mapping']
        reasons = item['reasons']

        # Count reasons
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

        # Count by supplier
        supplier_name = get_supplier_name(None, mapping.supplier_id)
        supplier_breakdown[supplier_name] = (
            supplier_breakdown.get(supplier_name, 0) + 1)

    logger.info(f"Total invalid mappings found: {len(invalid_mappings)}")
    logger.info(f"Removed from database: {db_removed}")
    logger.info(f"Removed from JSON files: {json_removed}")

    logger.info("\nBreakdown by reason:")
    for reason, count in sorted(reason_counts.items()):
        logger.info(f"  {reason}: {count}")

    if supplier_breakdown:
        logger.info("\nBreakdown by supplier:")
        for supplier, count in sorted(supplier_breakdown.items()):
            logger.info(f"  {supplier}: {count}")

    logger.info("="*80)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Remove invalid mappings from database and JSON files'
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Run in dry-run mode (no actual changes)')

    args = parser.parse_args()

    dry_run_text = '(DRY RUN)' if args.dry_run else ''
    logger.info(f"Starting invalid mapping cleanup {dry_run_text}")

    db = SessionLocal()
    try:
        # Step 1: Identify invalid mappings
        invalid_mappings = identify_invalid_mappings(db)

        if not invalid_mappings:
            logger.info("No invalid mappings found!")
            return

        # Step 2: Remove from database
        db_removed = remove_invalid_mappings_from_db(
            db, invalid_mappings, args.dry_run)

        # Step 3: Clean JSON files
        json_removed = cleanup_json_files(invalid_mappings, args.dry_run)

        # Step 4: Generate report
        generate_report(invalid_mappings, db_removed, json_removed)

        completion_text = '(DRY RUN)' if args.dry_run else 'successfully'
        logger.info(f"Cleanup completed {completion_text}!")

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main() 