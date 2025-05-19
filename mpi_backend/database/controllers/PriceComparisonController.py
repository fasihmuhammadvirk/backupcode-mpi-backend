from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from datetime import date
import logging

from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.schemas.PriceComparison import (
    ItemInfo,
    ItemPriceInfo
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
        
        Args:
            from_date (date): Start date for the search
            to_date (date): End date for the search
            
        Returns:
            List[ItemInfo]: List of distinct items with their information
        """
        try:
            db = self._get_db_session()
            items = db.query(
                InvoiceItem.mpi_item,
                InvoiceItem.item.label('original_item'),
                InvoiceItem.mpi_description
            ).filter(
                and_(
                    InvoiceItem.date >= from_date,
                    InvoiceItem.date <= to_date,
                    InvoiceItem.mpi_item != 'No Match'
                )
            ).distinct().all()

            return [
                ItemInfo(
                    mpi_item=item.mpi_item,
                    original_item=item.original_item,
                    mpi_description=item.mpi_description
                )
                for item in items
            ]
        except Exception as e:
            logger.error(f"Error fetching items in date range: {str(e)}")
            raise

    def get_items_prices(self, items: List[ItemInfo]) -> List[ItemPriceInfo]:
        """
        Get the most recent prices for the specified items.
        
        Args:
            items (List[ItemInfo]): List of items to get prices for
            
        Returns:
            List[ItemPriceInfo]: List of items with their most recent prices
        """
        try:
            db = self._get_db_session()
            result = []

            for item in items:
                # Get the most recent price for the item
                latest_price = db.query(
                    InvoiceItem.cost
                ).filter(
                    InvoiceItem.mpi_item == item.mpi_item
                ).order_by(
                    InvoiceItem.date.desc()
                ).first()

                result.append(
                    ItemPriceInfo(
                        mpi_item=item.mpi_item,
                        original_item=item.original_item,
                        mpi_description=item.mpi_description,
                        unit_price=latest_price.cost if latest_price else None
                    )
                )

            return result
        except Exception as e:
            logger.error(f"Error fetching items prices: {str(e)}")
            raise 