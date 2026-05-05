#!/usr/bin/env python3
"""
Backfill script to fix non-ASCII characters in raw.model_extracted_data.

Uses the staging table analytics_staging.stg__extracted_line_items as an
index to find ALL extracted items containing non-ASCII lookalike characters
(e.g., Greek Nu instead of Latin N), then updates the corresponding raw
records via direct PK lookup on extraction_id.

Usage:
    # Dry run - shows what would be changed without applying
    python backfill_ascii_normalization.py --dry-run

    # Actually apply changes
    python backfill_ascii_normalization.py --apply

    # Limit number of records to process
    python backfill_ascii_normalization.py --dry-run --limit 10

    # Normalize specific fields (default is 'item' only)
    python backfill_ascii_normalization.py --apply --fields item description po_no
"""
import argparse
import copy
import logging
import sys
from pathlib import Path

from psycopg2.extras import RealDictCursor, Json

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from ascii_normalization import normalize_to_ascii_with_details
from db_utils import connect_to_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Fields that live inside line_items[] — sourced from stg__extracted_line_items
LINE_ITEM_FIELDS = {'item', 'description'}

# Fields that live at the invoice top-level — sourced from stg__extracted_global_fields.
# Maps staging column name -> raw_data JSONB key (they differ for po_no/po_number).
GLOBAL_FIELDS = {
    'po_number': 'po_no',   # staging col: po_number, JSONB key: po_no
    'vendor':    'vendor',
    'buyer':     'buyer',
    'ref_no':    'ref_no',
    'customer_job': 'customer_job',
    'bill':      'bill',
}
# Reverse map: user-friendly input name -> staging column name
GLOBAL_FIELD_INPUT_TO_STAGING = {
    'po_no':        'po_number',   # user types 'po_no', staging col is 'po_number'
    'vendor':       'vendor',
    'buyer':        'buyer',
    'ref_no':       'ref_no',
    'customer_job': 'customer_job',
    'bill':         'bill',
}


def get_items_with_non_ascii(cursor, limit: int | None = None, fields: list[str] | None = None) -> list[dict]:
    """
    Query all extracted items with non-ASCII characters from the staging table.

    Args:
        cursor: Database cursor
        limit: Optional limit on number of records
        fields: List of line item fields to check for non-ASCII characters.
            Defaults to ['item'] to preserve original behaviour.

    Returns:
        list[dict]: List of items with non-ASCII characters and their extraction_ids
    """
    _fields = fields if fields else ['item']

    # 'item' is always needed as the row locator (used by update_raw_data_item
    # to find the correct line item to patch), even if the user didn't ask to normalize it.
    select_cols = list(dict.fromkeys(['item'] + _fields))  # deduplicated, item first

    # Build WHERE clause: any of the requested fields contains non-ASCII
    non_ascii_conditions = " OR ".join(f"{f} ~ '[^[:ascii:]]'" for f in _fields)

    select_fields = ", ".join(select_cols)

    query = f"""
        SELECT DISTINCT extraction_id::text, s3_file_key AS filename, {select_fields}
        FROM analytics_staging.stg__extracted_line_items
        WHERE {non_ascii_conditions}
        ORDER BY extraction_id
    """

    if limit:
        query += " LIMIT %s"
        cursor.execute(query, (limit,))
    else:
        cursor.execute(query)
    rows = cursor.fetchall()

    results = []
    for row in rows:
        # Normalize only the explicitly requested fields (not the locator-only 'item')
        field_normalizations = {}
        for field in _fields:
            value = row.get(field)
            if not isinstance(value, str):
                continue
            normalized, details = normalize_to_ascii_with_details(value)
            if details['chars_replaced'] > 0:
                field_normalizations[field] = {
                    'original': value,
                    'normalized': normalized,
                    'details': details,
                }

        if field_normalizations:
            results.append({
                'extraction_id': row['extraction_id'],
                'filename': row['filename'],
                # Keep 'item' / 'normalized_item' for backward compat with logging
                'item': row.get('item', ''),
                'normalized_item': field_normalizations.get('item', {}).get('normalized', row.get('item', '')),
                'non_ascii_details': field_normalizations.get('item', {}).get('details', {'replacements': []}),
                'field_normalizations': field_normalizations,
            })

    return results


def get_raw_extraction_by_id(cursor, extraction_id: str) -> dict | None:
    """
    Get the raw extraction record by its primary key.

    Args:
        cursor: Database cursor
        extraction_id: UUID of the extraction record

    Returns:
        dict | None: Raw extraction record or None if not found
    """
    query = """
        SELECT id, s3_file_key, raw_data
        FROM raw.model_extracted_data
        WHERE id = %s
          AND deleted_at IS NULL
    """

    cursor.execute(query, (extraction_id,))
    row = cursor.fetchone()

    if row:
        return {
            'id': str(row['id']),
            's3_file_key': row['s3_file_key'],
            'raw_data': row['raw_data']
        }

    return None


def get_global_fields_with_non_ascii(cursor, staging_fields: list[str], limit: int | None = None) -> list[dict]:
    """
    Query stg__extracted_global_fields for rows where any of the given
    header-level fields contain non-ASCII characters.

    Args:
        cursor: Database cursor
        staging_fields: List of staging column names to check (e.g. ['po_number', 'vendor']).
            These must be valid column names in stg__extracted_global_fields.
        limit: Optional limit on number of records

    Returns:
        list[dict]: One entry per extraction with non-ASCII global fields, containing
            extraction_id, filename, and field_normalizations.
    """
    non_ascii_conditions = " OR ".join(f"{f} ~ '[^[:ascii:]]'" for f in staging_fields)
    select_fields = ", ".join(staging_fields)

    query = f"""
        SELECT DISTINCT extraction_id::text, filename, {select_fields}
        FROM analytics_staging.stg__extracted_global_fields
        WHERE {non_ascii_conditions}
        ORDER BY extraction_id
    """

    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    rows = cursor.fetchall()

    results = []
    for row in rows:
        field_normalizations = {}
        for staging_col in staging_fields:
            value = row.get(staging_col)
            if not isinstance(value, str):
                continue
            normalized, details = normalize_to_ascii_with_details(value)
            if details['chars_replaced'] > 0:
                # Map staging column name back to the raw_data JSONB key
                jsonb_key = GLOBAL_FIELDS.get(staging_col, staging_col)
                field_normalizations[jsonb_key] = {
                    'original': value,
                    'normalized': normalized,
                    'details': details,
                }

        if field_normalizations:
            results.append({
                'extraction_id': row['extraction_id'],
                'filename': row['filename'],
                'field_normalizations': field_normalizations,
            })

    return results


def update_raw_data_global_field(raw_data: dict, field_normalizations: dict) -> tuple[dict, str]:
    """
    Update top-level invoice fields (e.g. po_no, vendor) in raw_data in-place.

    Handles both flat structure (raw_data has the field directly) and
    nested invoices[] (multi-invoice Gemini response).

    Args:
        raw_data: The JSONB raw_data dictionary (modified in-place)
        field_normalizations: Dict mapping JSONB key -> {original, normalized}

    Returns:
        tuple[dict, str]: (raw_data, status) — 'updated', 'already_processed', or 'not_found'
    """
    updated_any = False
    already_processed_any = False

    # Collect all invoice-level objects to patch (flat root + invoices[])
    invoice_objects = []
    if 'invoices' in raw_data and isinstance(raw_data['invoices'], list):
        for inv in raw_data['invoices']:
            if isinstance(inv, dict):
                invoice_objects.append(inv)
    else:
        # Flat structure — raw_data itself is the invoice object
        invoice_objects.append(raw_data)

    for inv_obj in invoice_objects:
        for jsonb_key, norm_info in field_normalizations.items():
            original = norm_info['original']
            normalized = norm_info['normalized']
            current = inv_obj.get(jsonb_key)

            if not isinstance(current, str):
                continue

            # Idempotency check
            if current == normalized and inv_obj.get(f'{jsonb_key}_original') == original:
                already_processed_any = True
                continue

            if current.strip() == original:
                inv_obj[f'{jsonb_key}_original'] = original
                inv_obj[jsonb_key] = normalized
                logger.debug(f"Updated global field '{jsonb_key}': '{original}' -> '{normalized}'")
                updated_any = True

    if updated_any:
        return raw_data, 'updated'
    if already_processed_any:
        return raw_data, 'already_processed'
    return raw_data, 'not_found'


def update_raw_data_item(raw_data: dict, original_item: str, normalized_item: str, field_normalizations: dict | None = None) -> tuple[dict, str]:
    """
    Update line_items in raw_data in-place, replacing non-ASCII values with ASCII equivalents.

    The caller is responsible for making a deepcopy before calling this function
    if the original dict must be preserved. This allows chaining multiple updates
    on the same dict when an extraction has multiple non-ASCII items.

    Handles both flat 'line_items' at root and nested 'invoices[].line_items'.

    Args:
        raw_data: The JSONB raw_data dictionary (modified in-place)
        original_item: The original item code (with non-ASCII chars) — used to
            locate the correct line item row (matched via the 'item' field).
        normalized_item: The ASCII-normalized item code
        field_normalizations: Dict mapping field name -> {original, normalized}
            for all fields to update on the matched line item.
            Defaults to updating only the 'item' field (original behaviour).

    Returns:
        tuple[dict, str]: (raw_data, status) where status is one of:
            - 'updated': successfully updated an item
            - 'already_processed': item has item_original (idempotent skip)
            - 'not_found': item doesn't exist in line_items
    """
    # Collect all lists of line items to process
    target_lists = []
    if 'line_items' in raw_data and isinstance(raw_data['line_items'], list):
        target_lists.append(raw_data['line_items'])
    
    if 'invoices' in raw_data and isinstance(raw_data['invoices'], list):
        for invoice in raw_data['invoices']:
            if isinstance(invoice, dict) and 'line_items' in invoice and isinstance(invoice['line_items'], list):
                target_lists.append(invoice['line_items'])

    if not target_lists:
        return raw_data, 'not_found'

    # Build the effective per-field updates: always includes 'item', plus any extras
    _field_normalizations = field_normalizations or {}
    if 'item' not in _field_normalizations:
        _field_normalizations['item'] = {'original': original_item, 'normalized': normalized_item}

    updated_any = False
    already_processed_any = False

    for line_items_list in target_lists:
        for line_item in line_items_list:
            if not isinstance(line_item, dict):
                continue

            item_value = line_item.get('item')
            if item_value is None:
                continue

            # Idempotency check: track if already processed
            # We check if item matches original and has item_original
            if item_value == normalized_item and line_item.get('item_original') == original_item:
                already_processed_any = True
                continue

            # Compare using strip() because the staging table (dbt) trims the value
            if isinstance(item_value, str) and item_value.strip() == original_item:
                # Update all requested fields on this line item
                for field, norm_info in _field_normalizations.items():
                    field_original = norm_info['original']
                    field_normalized = norm_info['normalized']
                    current_value = line_item.get(field)
                    if isinstance(current_value, str):
                        line_item[f'{field}_original'] = field_original
                        line_item[field] = field_normalized
                        logger.debug(f"Updated line_item '{field}': '{field_original}' -> '{field_normalized}'")
                updated_any = True

    if updated_any:
        return raw_data, 'updated'
    if already_processed_any:
        return raw_data, 'already_processed'
    return raw_data, 'not_found'


def apply_update(cursor, extraction_id: str, updated_raw_data: dict) -> bool:
    """
    Apply the updated raw_data to the database.

    Args:
        cursor: Database cursor
        extraction_id: UUID of the extraction record
        updated_raw_data: The updated JSONB data

    Returns:
        bool: True if update succeeded
    """
    query = """
        UPDATE raw.model_extracted_data
        SET raw_data = %s
        WHERE id = %s
    """

    cursor.execute(query, (Json(updated_raw_data), extraction_id))
    return cursor.rowcount > 0


def main():
    parser = argparse.ArgumentParser(
        description='Backfill ASCII normalization for all extracted items'
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without applying'
    )
    mode_group.add_argument(
        '--apply',
        action='store_true',
        help='Actually apply changes to the database'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of records to process'
    )
    parser.add_argument(
        '--fields',
        nargs='+',
        default=None,
        metavar='FIELD',
        help=(
            'Line item fields to normalize (default: item).'
            'Example: --fields item description po_no'
        )
    )

    args = parser.parse_args()
    fields = args.fields  # None means default ['item'] behaviour

    if args.dry_run:
        logger.info("DRY RUN MODE - no changes will be applied")
        logger.info("Use --apply to actually update the database")

    _fields = fields or ['item']
    logger.info(f"Normalizing fields: {_fields}")

    # Connect to database
    connection = connect_to_db()
    if connection is None:
        logger.error("Failed to connect to database")
        sys.exit(1)

    cursor = connection.cursor(cursor_factory=RealDictCursor)

    try:
        # Split caller-supplied fields into the two source groups
        line_item_fields_requested = [f for f in _fields if f in LINE_ITEM_FIELDS]
        global_staging_fields_requested = [
            GLOBAL_FIELD_INPUT_TO_STAGING[f]
            for f in _fields
            if f in GLOBAL_FIELD_INPUT_TO_STAGING
        ]

        # Warn about any unrecognised fields early
        unsupported = [f for f in _fields if f not in LINE_ITEM_FIELDS and f not in GLOBAL_FIELD_INPUT_TO_STAGING]
        if unsupported:
            logger.warning(f"Unknown/unsupported fields will be skipped: {unsupported}")

        # Default: if nothing matched either group, fall back to ['item'] (original behaviour)
        if not line_item_fields_requested and not global_staging_fields_requested:
            line_item_fields_requested = ['item']

        # Step 1a: Query line-item fields (stg__extracted_line_items)
        items_to_fix = []
        if line_item_fields_requested:
            logger.info(f"Querying stg__extracted_line_items for fields: {line_item_fields_requested}")
            items_to_fix = get_items_with_non_ascii(cursor, args.limit, fields=line_item_fields_requested)
            logger.info(f"Found {len(items_to_fix)} line-item rows with non-ASCII characters")

        # Step 1b: Query global/header fields (stg__extracted_global_fields)
        global_to_fix = []
        if global_staging_fields_requested:
            logger.info(f"Querying stg__extracted_global_fields for fields: {global_staging_fields_requested}")
            global_to_fix = get_global_fields_with_non_ascii(cursor, global_staging_fields_requested, args.limit)
            logger.info(f"Found {len(global_to_fix)} global field rows with non-ASCII characters")

        if not items_to_fix and not global_to_fix:
            logger.info("No records found with non-ASCII characters")
            return

        logger.info(f"Total: {len(items_to_fix)} line-item rows, {len(global_to_fix)} global rows")

        # Step 2: Group by extraction_id to fetch/update each raw record once
        items_by_extraction: dict[str, list] = {}
        for item_info in items_to_fix:
            items_by_extraction.setdefault(item_info['extraction_id'], []).append(item_info)

        global_by_extraction: dict[str, dict] = {}
        for g_info in global_to_fix:
            # Only one global row per extraction_id (one po_no per invoice)
            global_by_extraction[g_info['extraction_id']] = g_info

        all_extraction_ids = set(items_by_extraction) | set(global_by_extraction)
        logger.info(f"Across {len(all_extraction_ids)} extraction records")

        # Step 3: Process each extraction record
        updated_count = 0
        already_processed_count = 0
        not_found_count = 0
        error_count = 0
        extraction_idx = 0

        for extraction_id in all_extraction_ids:
            extraction_idx += 1
            items_group = items_by_extraction.get(extraction_id, [])
            global_info = global_by_extraction.get(extraction_id)

            filename = (items_group[0]['filename'] if items_group
                        else global_info['filename'] if global_info else '?')
            logger.info(f"\n[{extraction_idx}/{len(all_extraction_ids)}] Extraction {extraction_id}")
            logger.info(f"  Filename: {filename}")

            if items_group:
                logger.info(f"  Line-item rows to normalize: {len(items_group)}")
                for item_info in items_group:
                    for repl in item_info['non_ascii_details'].get('replacements', []):
                        logger.info(
                            f"  '{item_info['item']}' -> '{item_info['normalized_item']}': "
                            f"'{repl['original']}' ({repl['original_name']}) -> '{repl['replacement']}'"
                        )
                    for field, norm_info in item_info['field_normalizations'].items():
                        if field != 'item':
                            logger.info(f"  [line.{field}] '{norm_info['original']}' -> '{norm_info['normalized']}'")

            if global_info:
                for jsonb_key, norm_info in global_info['field_normalizations'].items():
                    logger.info(f"  [global.{jsonb_key}] '{norm_info['original']}' -> '{norm_info['normalized']}'")

            # Fetch raw record once
            extraction = get_raw_extraction_by_id(cursor, extraction_id)
            if not extraction:
                logger.warning(f"  No extraction found for id: {extraction_id}")
                not_found_count += len(items_group) + (1 if global_info else 0)
                continue

            # Apply all normalizations to the same copy
            raw_data = copy.deepcopy(extraction['raw_data'])
            any_updated = False

            # --- Line item field updates ---
            for item_info in items_group:
                raw_data, status = update_raw_data_item(
                    raw_data,
                    item_info['item'],
                    item_info['normalized_item'],
                    field_normalizations=item_info['field_normalizations'],
                )
                if status == 'already_processed':
                    logger.info(f"  [SKIP] '{item_info['item']}' already processed")
                    already_processed_count += 1
                elif status == 'not_found':
                    logger.warning(f"  '{item_info['item']}' not found in raw_data line_items")
                    not_found_count += 1
                elif status == 'updated':
                    any_updated = True
                    updated_count += 1

            # --- Global field updates ---
            if global_info:
                raw_data, status = update_raw_data_global_field(
                    raw_data, global_info['field_normalizations']
                )
                if status == 'already_processed':
                    logger.info(f"  [SKIP] global fields already processed")
                    already_processed_count += 1
                elif status == 'not_found':
                    logger.warning(f"  Global fields not found in raw_data")
                    not_found_count += 1
                elif status == 'updated':
                    any_updated = True
                    updated_count += 1

            # Write back once if anything changed
            if any_updated:
                if args.apply:
                    try:
                        success = apply_update(cursor, extraction_id, raw_data)
                        if success:
                            logger.info(f"  [OK] Updated extraction {extraction_id}")
                        else:
                            logger.error(f"  [FAILED] No rows updated for {extraction_id}")
                            error_count += 1
                    except Exception as e:
                        logger.error(f"  [ERROR] Failed to update: {e}")
                        error_count += 1
                else:
                    logger.info(f"  [DRY RUN] Would update extraction {extraction_id}")

        # Commit if applying changes
        if args.apply:
            connection.commit()
            logger.info("\nChanges committed to database")

        # Summary
        logger.info("\n" + "=" * 50)
        logger.info("SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Line-item rows found: {len(items_to_fix)}")
        logger.info(f"Global rows found:    {len(global_to_fix)}")
        logger.info(f"Extractions:          {len(all_extraction_ids)}")
        logger.info(f"Updated:              {updated_count}")
        logger.info(f"Already processed:    {already_processed_count}")
        logger.info(f"Not found:            {not_found_count}")
        logger.info(f"Errors:               {error_count}")

        if args.dry_run:
            logger.info("\nThis was a DRY RUN. Use --apply to make actual changes.")

    except Exception as e:
        logger.exception(f"Error during backfill: {e}")
        connection.rollback()
        sys.exit(1)

    finally:
        cursor.close()
        connection.close()


if __name__ == '__main__':
    main()
