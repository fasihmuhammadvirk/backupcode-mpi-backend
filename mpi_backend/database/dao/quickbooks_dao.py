"""
Data Access Object for QuickBooks export operations.

Provides stateless functions for querying invoice items, invoices,
and classifications needed for QuickBooks export.
"""

import logging
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import exists, func

from mpi_backend.database.models import InvoiceItem, Invoice, InvoiceItemMart
from mpi_backend.database.models.ItemClassification import ItemClassification
from mpi_backend.database.models.QuickBooksItems import QuickBooksItems
from mpi_backend.database.models.QuickBooksPreviewMart import QuickBooksPreviewMart

logger = logging.getLogger(__name__)

def get_preview_from_mart(
    db: Session,
    start_date: date,
    end_date: date,
    only_unprocessed: bool = False
) -> List[Dict[str, Any]]:
    """
    Query pre-computed QuickBooks preview items from mart__quickbooks_preview.

    The mart is now structured as one row per invoice, containing pre-computed
    JSON arrays of QuickBooksPreviewItem objects for both 'all' and 'unprocessed' 
    filters. This allows for instant retrieval and handles partial invoice 
    exports (where only remaining items show up in 'unprocessed').

    Args:
        db: SQLAlchemy database session
        start_date: Start date for filtering (inclusive)
        end_date: End date for filtering (inclusive)
        only_unprocessed: When True, use the unprocessed_data_json column.

    Returns:
        List of dicts representing QuickBooksPreviewItem objects.
    """
    logger.info(
        f"DAO: Querying mart__quickbooks_preview from {start_date} to {end_date}, "
        f"unprocessed_only={only_unprocessed}"
    )

    query = db.query(QuickBooksPreviewMart).filter(
        QuickBooksPreviewMart.date >= start_date,
        QuickBooksPreviewMart.date <= end_date
    )

    # If only_unprocessed, we might want to skip invoices that are 100% processed
    if only_unprocessed:
        # Filter out rows where unprocessed_data_json is empty or NULL
        query = query.filter(
            QuickBooksPreviewMart.unprocessed_data_json.is_not(None),
            func.jsonb_array_length(QuickBooksPreviewMart.unprocessed_data_json) > 0
        )

    rows = query.order_by(
        QuickBooksPreviewMart.date.asc(),
        QuickBooksPreviewMart.ref_no.asc(),
        QuickBooksPreviewMart.vendor.asc()
    ).all()

    # Flatten the pre-computed JSON columns into a single list of items
    result_items = []
    for row in rows:
        data = row.unprocessed_data_json if only_unprocessed else row.all_data_json
        if data:
            result_items.extend(data)

    logger.info(f"DAO: Retrieved {len(rows)} matching invoices, flattened to {len(result_items)} preview items")
    return result_items


def count_no_match_items(
    db: Session,
    start_date: date,
    end_date: date,
) -> int:
    """
    Count invoice items with mpi_item = 'No Match' in a date range.

    The mart__quickbooks_preview table silently excludes No Match items so
    they never appear in the preview.  This function lets the controller
    detect them up-front and return a clear HTTP 400 error instead.

    Args:
        db: SQLAlchemy database session
        start_date: Start date (inclusive)
        end_date: End date (inclusive)

    Returns:
        Number of 'No Match' items in the date range (0 = all clear)
    """
    count = (
        db.query(InvoiceItemMart)
        .filter(
            InvoiceItemMart.date >= start_date,
            InvoiceItemMart.date <= end_date,
            InvoiceItemMart.mpi_item == 'No Match',
            # Only non-TAX rows (tax rows don't carry an mpi_item that matters)
            InvoiceItemMart.sheet_name != '(TAX)',
        )
        .count()
    )
    logger.info(
        f"DAO: Found {count} 'No Match' items between {start_date} and {end_date}"
    )
    return count


def get_classifications_by_items(
    db: Session,
    sheet_names: List[str]
) -> Dict[str, str]:
    """
    Query item classifications and return as dictionary mapping item to category.
    
    Args:
        db: SQLAlchemy database session
        sheet_names: List of sheet names (items) to get classifications for
        
    Returns:
        Dictionary mapping sheet_name to category code (M/E/A)
    """
    if not sheet_names:
        return {}
    
    logger.info(f"DAO: Querying classifications for {len(sheet_names)} items")
    
    classifications = db.query(ItemClassification).filter(
        ItemClassification.item.in_(sheet_names)
    ).all()
    
    # Build classification cache
    classification_cache = {}
    for classification in classifications:
        try:
            category = (classification.category or '').strip().upper()
            if category in ['M', 'E', 'A']:
                classification_cache[classification.item] = category
            else:
                classification_cache[classification.item] = ''
        except Exception as e:
            logger.warning(f"Error processing classification for {classification.item}: {e}")
            classification_cache[classification.item] = ''
    
    logger.info(f"DAO: Retrieved {len(classification_cache)} classifications")
    return classification_cache


def get_all_classifications(db: Session) -> List[ItemClassification]:
    """
    Query all item classifications.
    
    Args:
        db: SQLAlchemy database session
        
    Returns:
        List of ItemClassification objects
    """
    logger.info("DAO: Querying all classifications")
    
    classifications = db.query(ItemClassification).all()
    
    logger.info(f"DAO: Retrieved {len(classifications)} classifications")
    return classifications

# This DAO function is intentionally designed to be self-contained
def update_invoice_items_export_status(
    db: Session,
    item_ids: List[int],
    status: str = 'Sent'
) -> int:
    """
    Update export status for multiple invoice items.
    
    Args:
        db: SQLAlchemy database session
        item_ids: List of invoice item IDs to update
        status: New export status (default: 'Sent')
        
    Returns:
        Number of items updated
    """
    logger.info(f"DAO: Updating export status to '{status}' for {len(item_ids)} items")
    
    updated_count = db.query(InvoiceItem).filter(
        InvoiceItem.id.in_(item_ids)
    ).update(
        {InvoiceItem.export_status: status},
        synchronize_session=False
    )
    
    db.commit()
    logger.info(f"DAO: Updated {updated_count} items")
    
    return updated_count


def get_invoice_item_by_id(
    db: Session,
    item_id: int
) -> Optional[InvoiceItem]:
    """
    Query a single invoice item by ID.
    
    Args:
        db: SQLAlchemy database session
        item_id: Invoice item ID
        
    Returns:
        InvoiceItem object or None if not found
    """
    return db.query(InvoiceItem).filter(
        InvoiceItem.id == item_id
    ).first()


def get_invoice_by_id(
    db: Session,
    invoice_id: UUID
) -> Optional[Invoice]:
    """
    Query a single invoice by ID.
    
    Args:
        db: SQLAlchemy database session
        invoice_id: Invoice UUID
        
    Returns:
        Invoice object or None if not found
    """
    return db.query(Invoice).filter(
        Invoice.id == invoice_id
    ).first()


def insert_quickbooks_export_records_from_rows(
    db: Session,
    rows: List[Dict]
) -> int:
    """
    Insert export records into QuickBooksItems using already-fetched row data.

    Args:
        db: SQLAlchemy database session
        rows: List of dicts with keys: id, invoice_id, ref_no, vendor, date

    Returns:
        Number of records inserted
    """
    if not rows:
        logger.warning("DAO: No rows provided for QuickBooks export records")
        return 0

    logger.info(f"DAO: Inserting QuickBooks export records for {len(rows)} items")

    qb_records = [
        QuickBooksItems(
            invoice_items_id=int(row['id']),
            invoice_id=row['invoice_id'],
            ref_no=row.get('ref_no') or '',
            vendor=row.get('vendor') or '',
            date=row.get('date'),
        )
        for row in rows
    ]

    db.bulk_save_objects(qb_records)
    db.commit()

    logger.info(f"DAO: Inserted {len(qb_records)} QuickBooks export records")
    return len(qb_records)

def get_unprocessed_invoice_date_range(db: Session) -> Dict[str, Optional[date]]:
    """
    Query the oldest and latest invoice date for unprocessed items from InvoiceItemMart.

    Unprocessed items are defined as those that do not have a corresponding record
    in the QuickBooksItems (export tracking) table.

    Args:
        db: SQLAlchemy database session

    Returns:
        Dictionary with 'oldest_date' and 'latest_date'
    """
    from sqlalchemy import func
    logger.info("DAO: Querying date range for unprocessed invoices")

    result = db.query(
        func.min(InvoiceItemMart.date).label("oldest_date"),
        func.max(InvoiceItemMart.date).label("latest_date")
    ).filter(
        ~exists().where(
            QuickBooksItems.invoice_items_id == InvoiceItemMart.id
        ),
        ~InvoiceItemMart.sheet_name.in_(['(TAX)', 'TAX'])
    ).first()

    return {
        "oldest_date": result.oldest_date if result else None,
        "latest_date": result.latest_date if result else None
    }
