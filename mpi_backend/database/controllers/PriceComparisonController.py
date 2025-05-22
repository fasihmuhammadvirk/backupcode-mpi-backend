from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from datetime import date
import logging

from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.database.schemas.PriceComparison import (
    ItemInfo,
    ItemPriceResponse
)

logger = logging.getLogger(__name__)

class PriceComparisonController:
    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self) -> Session:
        """Get a database session object, whether db_context is a factory or session."""
        if callable(self.db_context):
            return self.db_context()
        return self.db_context

    def get_items_in_date_range(self, from_date: date, to_date: date) -> List[ItemInfo]:
        """
        Get distinct items that were used within the specified date range.
        Excludes items with 'No Match' or 'UIDI' in the description.
        
        Args:
            from_date (date): Start date for the search
            to_date (date): End date for the search
            
        Returns:
            List[ItemInfo]: List of distinct items with their information and IDs
        """
        try:
            db = self._get_db_session()
            items = db.query(
                InvoiceItem.id,
                InvoiceItem.mpi_item,
                InvoiceItem.item.label('original_item'),
                InvoiceItem.mpi_description
            ).filter(
                and_(
                    InvoiceItem.date >= from_date,
                    InvoiceItem.date <= to_date,
                    InvoiceItem.mpi_item != 'No Match',
                    InvoiceItem.mpi_description.notlike('%No Match%'),
                    ~InvoiceItem.mpi_item.contains('UIDI'),
                    ~InvoiceItem.mpi_description.contains('UIDI'),
                    ~InvoiceItem.mpi_item.like('%10 Materials%')
                )
            ).distinct().all()

            return [
                ItemInfo(
                    id=item.id,
                    mpi_item=item.mpi_item,
                    original_item=item.original_item,
                    mpi_description=item.mpi_description
                )
                for item in items
            ]
        except Exception as e:
            logger.error(f"Error fetching items in date range: {str(e)}")
            raise

    def get_items_prices(self, items: List[ItemInfo]) -> List[ItemPriceResponse]:
        """
        Get the lowest prices for the specified items across all suppliers.
        Returns a simplified response with only the required fields.
        
        Args:
            items (List[ItemInfo]): List of items to get prices for
            
        Returns:
            List[ItemPriceResponse]: List of items with their lowest prices
        """
        try:
            db = self._get_db_session()
            result = []

            for item in items:
                # Get the lowest price for the item
                lowest_price = db.query(
                    InvoiceItem.cost
                ).filter(
                    InvoiceItem.mpi_item == item.mpi_item,
                    InvoiceItem.cost.isnot(None)  # Exclude items with no cost
                ).order_by(
                    InvoiceItem.cost.asc()
                ).first()

                if not lowest_price or lowest_price.cost is None:
                    continue  # Skip if no valid price found
                
                # Create response with only the required fields
                result.append(
                    ItemPriceResponse(
                        id=item.id,
                        mpi_item=item.mpi_item or '',
                        original_item=item.original_item or '',
                        mpi_description=item.mpi_description or '',
                        unit_price=float(lowest_price.cost)
                    )
                )

            return result
        except Exception as e:
            logger.error(f"Error fetching items prices: {str(e)}")
            raise
            
    def get_cheapest_prices_per_supplier(self, items: List[ItemInfo]) -> List[dict]:
        """
        Get the lowest unit price per supplier for each item.
        
        Args:
            items (List[ItemInfo]): List of items to get prices for
            
        Returns:
            List[dict]: List of items with their suppliers and lowest prices
        """
        try:
            db = self._get_db_session()
            result = []
            
            for item in items:
                # Get the lowest price per supplier for this item with supplier ID
                supplier_prices = db.query(
                    InvoiceItem.vendor,
                    InvoiceItem.cost,
                    Supplier.id.label('supplier_id')
                ).join(
                    Supplier, 
                    Supplier.supplier_name == InvoiceItem.vendor
                ).filter(
                    InvoiceItem.mpi_item == item.mpi_item,
                    InvoiceItem.cost.isnot(None),
                    InvoiceItem.vendor.isnot(None)
                ).order_by(
                    InvoiceItem.vendor,
                    InvoiceItem.cost.asc()
                ).distinct(
                    InvoiceItem.vendor
                ).all()
                
                if not supplier_prices:
                    continue
                    
                # Format supplier prices with supplier ID
                suppliers = [
                    {
                        "id": supplier_id,
                        "name": vendor or "Unknown", 
                        "unit_price": float(cost)
                    }
                    for vendor, cost, supplier_id in supplier_prices
                    if cost is not None
                ]
                
                # Sort suppliers by price (cheapest first)
                suppliers.sort(key=lambda x: x["unit_price"])
                
                result.append({
                    "id": item.id,
                    "mpi_item": item.mpi_item or "",
                    "original_item": item.original_item or "",
                    "mpi_description": item.mpi_description or "",
                    "suppliers": suppliers
                })
                
            return result
            
        except Exception as e:
            logger.error(f"Error fetching cheapest prices per supplier: {str(e)}")
            raise
