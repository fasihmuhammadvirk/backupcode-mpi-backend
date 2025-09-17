"""
Reusable duplication filtering utility for consistent application across
filter endpoint and Excel export.
"""

import logging
from typing import List, Dict, Any
from collections import defaultdict
from datetime import date

logger = logging.getLogger(__name__)


def filter_exact_duplicates(items: List[Any],
                            tolerance: float = 0.01) -> List[Any]:
    """
    Filter out exact duplicate invoices, keeping only the most recent one.

    Exact Duplicate Criteria:
    - Same ref_no + vendor + date + total_amount (within tolerance)
    - Action: Keep only the most recent (latest date_added)

    Args:
        items: List of invoice items
        tolerance: Amount tolerance for floating-point comparison (0.01)

    Returns:
        Filtered list with exact duplicates removed
    """
    if not items:
        return items

    # Group items by invoice_id to calculate totals
    invoice_groups = defaultdict(list)

    for item in items:
        invoice_id = _get_field_value(item, 'invoice_id')
        if invoice_id:
            invoice_groups[invoice_id].append(item)

    # Calculate invoice totals and metadata
    invoice_metadata = {}
    for invoice_id, invoice_items in invoice_groups.items():
        if not invoice_items:
            continue

        # Use first item for metadata
        first_item = invoice_items[0]

        ref_no = _get_field_value(first_item, 'ref_no')
        vendor = _get_field_value(first_item, 'vendor')
        item_date = _get_field_value(first_item, 'date')
        date_added = _get_field_value(first_item, 'date_added')

        # Calculate total amount for this invoice
        total_amount = 0.0
        for item in invoice_items:
            amount_value = _get_field_value(item, 'amount')
            try:
                # Handle string amounts with potential formatting
                if isinstance(amount_value, str):
                    amount_value = amount_value.replace(',', '').strip()
                item_amount = float(amount_value) if amount_value else 0.0
                total_amount += item_amount
            except (ValueError, TypeError):
                continue

        invoice_metadata[invoice_id] = {
            'ref_no': str(ref_no).strip() if ref_no else "",
            'vendor': str(vendor).strip() if vendor else "",
            'date': item_date,
            'total_amount': total_amount,
            'date_added': date_added,
            'items': invoice_items
        }

    # Find exact duplicate groups
    # Group by (ref_no, vendor, date, rounded_amount)
    duplicate_groups = defaultdict(list)

    for invoice_id, metadata in invoice_metadata.items():
        if not metadata['ref_no'] or not metadata['vendor']:
            continue

        # Round amount to handle floating point precision
        rounded_amount = round(metadata['total_amount'], 2)

        key = (
            metadata['ref_no'],
            metadata['vendor'],
            metadata['date'],
            rounded_amount
        )

        duplicate_groups[key].append((invoice_id, metadata))

    # Identify exact duplicates and keep only most recent
    invoices_to_keep = set()
    duplicates_removed = 0

    for key, group in duplicate_groups.items():
        if len(group) <= 1:
            # No duplicates, keep the invoice
            if group:
                invoices_to_keep.add(group[0][0])
        else:
            # Multiple invoices with same ref_no + vendor + date + amount
            # Check if amounts are within tolerance
            amounts = [metadata['total_amount'] for _, metadata in group]

            # Check if all amounts are within tolerance of each other
            min_amount = min(amounts)
            max_amount = max(amounts)

            if (max_amount - min_amount) <= tolerance:
                # These are exact duplicates - keep only the most recent
                most_recent = max(group, key=lambda x: (
                    x[1]['date_added'] or date.min,
                    x[0]  # Use invoice_id as tiebreaker
                ))

                invoices_to_keep.add(most_recent[0])
                duplicates_removed += len(group) - 1

                logger.info(
                    f"Filtered {len(group)} exact duplicates for "
                    f"RefNo: {key[0]}, Vendor: {key[1]}, Date: {key[2]}, "
                    f"Amount: {key[3]}. Kept most recent: {most_recent[0]}"
                )
            else:
                # Amounts differ beyond tolerance - keep all
                for invoice_id, _ in group:
                    invoices_to_keep.add(invoice_id)

    # Filter the original items list
    filtered_items = []
    for item in items:
        invoice_id = _get_field_value(item, 'invoice_id')
        if invoice_id in invoices_to_keep:
            filtered_items.append(item)

    if duplicates_removed > 0:
        logger.info(f"Filtered out {duplicates_removed} exact duplicate "
                    f"invoice items. Returning {len(filtered_items)} items "
                    f"from {len(items)} original items.")

    return filtered_items


def _get_field_value(obj: Any, field_name: str) -> Any:
    """
    Extract field value from different object types.

    Args:
        obj: Object to extract field from
        field_name: Name of the field to extract

    Returns:
        Field value or None if not found
    """
    try:
        # Try dictionary access first
        if isinstance(obj, dict):
            return obj.get(field_name)

        # Try attribute access (ORM objects, response objects)
        if hasattr(obj, field_name):
            return getattr(obj, field_name)

        # Try __dict__ access for objects with dynamic attributes
        if hasattr(obj, '__dict__') and field_name in obj.__dict__:
            return obj.__dict__[field_name]

    except (AttributeError, KeyError, TypeError):
        pass

    return None


def apply_duplication_rules_info(items: List[Any]) -> Dict[str, Any]:
    """
    Analyze items and return information about duplication rules applied.

    Args:
        items: List of invoice items

    Returns:
        Dictionary with duplication analysis info
    """
    if not items:
        return {
            'total_items': 0,
            'exact_duplicates_found': 0,
            'items_after_filtering': 0
        }

    original_count = len(items)
    filtered_items = filter_exact_duplicates(items)
    filtered_count = len(filtered_items)

    return {
        'total_items': original_count,
        'exact_duplicates_found': original_count - filtered_count,
        'items_after_filtering': filtered_count,
        'duplication_rules': {
            'exact_duplicate': 'Same ref_no + vendor + date + amount '
                               '(within 0.01) -> Keep most recent only',
            'updated_invoice': 'Same ref_no + vendor + date, different '
                               'amount -> Keep all',
            'new_invoice': 'Same ref_no + vendor, different date/amount '
                           '-> Keep all',
            'not_found': 'Unique ref_no + vendor -> Keep all'
        }
    }
