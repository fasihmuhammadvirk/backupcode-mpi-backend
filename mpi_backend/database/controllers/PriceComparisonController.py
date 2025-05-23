from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional, Dict, Any, Union
from datetime import date, datetime
import logging

from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.invoice import Invoice
from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.database.schemas.PriceComparison import (
    ItemInfo, 
    ItemPriceResponse,
    SupplierPriceInfo,
    SupplierCheapestItemsResponse,
    PaginatedItemInfoResponse
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

    def get_items_in_date_range(
        self, 
        from_date: date, 
        to_date: date,
        page: int = 1,
        size: int = 10
    ) -> dict[str, any]:
        """
        Get distinct items that were used within the specified date range.
        Excludes items with 'No Match' or 'UIDI' in the description.
        
        Args:
            from_date (date): Start date for the search
            to_date (date): End date for the search
            page (int): Page number (1-based)
            size (int): Number of items per page
            
        Returns:
            Dict containing paginated items and metadata
        """
        try:
            db = self._get_db_session()
            
            # Base query
            query = db.query(
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
            ).distinct()
            
            # Get total count for pagination
            total = query.count()
            
            # Apply pagination
            items = query.offset((page - 1) * size).limit(size).all()
            
            # Calculate total pages
            pages = (total + size - 1) // size if size > 0 else 1
            
            # Format response
            items = [
                ItemInfo(
                    id=item.id,
                    mpi_item=item.mpi_item,
                    original_item=item.original_item,
                    mpi_description=item.mpi_description
                )
                for item in items
            ]
            
            return PaginatedItemInfoResponse(
                items=items,
                total=total,
                page=page,
                size=size,
                pages=pages
            )
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
            
    def search_mpi_items(
        self,
        search_term: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        page: int = 1,
        size: int = 10
    ) -> Dict[str, Any]:
        """
        Search for MPI items by item code with optional date range filtering.
        Returns items starting with the search term first, then items containing the term.
        """
        try:
            db = self._get_db_session()
            search_term = (search_term or '').upper().strip()
            
            if not search_term:
                return {
                    'items': [],
                    'total': 0,
                    'page': page,
                    'size': size,
                    'pages': 0
                }
                
            # Prepare date filters
            date_filters = []
            if from_date:
                date_filters.append(InvoiceItem.date >= from_date)
            if to_date:
                date_filters.append(InvoiceItem.date <= to_date)
            
            # Base query for searching MPI items
            base_filters = [
                InvoiceItem.mpi_item != 'No Match',
                InvoiceItem.mpi_description.notlike('%No Match%'),
                ~InvoiceItem.mpi_item.contains('UIDI'),
                ~InvoiceItem.mpi_description.contains('UIDI'),
                ~InvoiceItem.mpi_item.like('%10 Materials%'),
                InvoiceItem.mpi_item != ''
            ]
            
            # Add date filters if provided
            if date_filters:
                base_filters.extend(date_filters)
            
            base_query = db.query(
                InvoiceItem.id,
                InvoiceItem.mpi_item,
                InvoiceItem.item.label('original_item'),
                InvoiceItem.mpi_description,
                InvoiceItem.date
            ).filter(and_(*base_filters))
            
            # Get items that start with the search term (case sensitive)
            starts_with_query = base_query.filter(
                InvoiceItem.mpi_item.like(f'{search_term}%')
            ).order_by(InvoiceItem.mpi_item.asc())
            
            # Get items that contain the search term but don't start with it
            contains_query = base_query.filter(
                and_(
                    ~InvoiceItem.mpi_item.like(f'{search_term}%'),
                    InvoiceItem.mpi_item.like(f'%{search_term}%')
                )
            ).order_by(InvoiceItem.mpi_item.asc())
            
            # Get results from both queries
            starts_with_results = starts_with_query.distinct().all()
            contains_results = contains_query.distinct().all()
            
            # Combine results with priority to 'starts with' matches
            all_results = list(starts_with_results) + list(contains_results)
            
            # Apply pagination
            total = len(all_results)
            start = (page - 1) * size
            end = start + size
            paginated_results = all_results[start:end]
            
            # Format response
            items = [
                ItemInfo(
                    id=item.id,
                    mpi_item=item.mpi_item or '',
                    original_item=item.original_item or '',
                    mpi_description=item.mpi_description or ''
                )
                for item in paginated_results
            ]
            
            return PaginatedItemInfoResponse(
                items=items,
                total=total,
                page=page,
                size=size,
                pages=(total + size - 1) // size if size > 0 else 1
            )
            
        except Exception as e:
            logger.error(f"Error searching MPI items: {str(e)}")
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
