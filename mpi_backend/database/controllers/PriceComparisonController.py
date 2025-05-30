from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, asc, func
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
    PaginatedItemInfoResponse,
    EnrichedItemPriceResponse,
    PaginatedEnrichedItemResponse
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
    ):
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
                    id=item.id,  # Use the database item ID
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
                        id=item.id,  # Use the item ID from the request
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
    ):
        """
        Search for MPI items by item code with optional date range filtering.
        Returns items starting with the search term first, then items containing the term.
        
        Args:
            search_term (str): The term to search for in MPI items
            from_date (Optional[date]): Filter items after this date
            to_date (Optional[date]): Filter items before this date
            page (int): Page number for pagination (1-based)
            size (int): Number of items per page
            
        Returns:
            PaginatedItemInfoResponse: Paginated list of matching items
        """
        try:
            db = self._get_db_session()
            search_term = (search_term or '').upper().strip()
            
            if not search_term or len(search_term) < 1:
                return PaginatedItemInfoResponse(
                    items=[],
                    total=0,
                    page=page,
                    size=size,
                    pages=0
                )
            
            # Build base query with common filters
            query = db.query(
                InvoiceItem.id,
                InvoiceItem.mpi_item,
                InvoiceItem.item.label('original_item'),
                InvoiceItem.mpi_description
            ).filter(
                InvoiceItem.mpi_item != 'No Match',
                InvoiceItem.mpi_item != '',
                ~InvoiceItem.mpi_item.like('%10 Materials%'),
                ~InvoiceItem.mpi_item.contains('UIDI')
            )
            
            # Add search term filter
            search_filter = or_(
                InvoiceItem.mpi_item.like(f'{search_term}%'),  # Starts with
                InvoiceItem.mpi_item.like(f'%{search_term}%')   # Contains
            )
            query = query.filter(search_filter)
            
            # Add date range filters if provided
            if from_date:
                query = query.filter(InvoiceItem.date >= from_date)
            if to_date:
                query = query.filter(InvoiceItem.date <= to_date)
            
            # Get total count for pagination
            total = query.distinct().count()
            
            # For PostgreSQL, when using DISTINCT with ORDER BY, all ORDER BY expressions must be in the SELECT list
            # Use a subquery approach to work around this limitation
            subquery = query.distinct().subquery()
            
            # Create a new query from the subquery
            items_query = db.query(
                subquery.c.id,
                subquery.c.mpi_item,
                subquery.c.original_item,
                subquery.c.mpi_description
            )
            
            # Now we can safely apply the ORDER BY to the outer query
            items = items_query\
                    .order_by(
                        func.upper(subquery.c.mpi_item).like(f'{search_term}%').desc(),  # Starts with first
                        func.upper(subquery.c.mpi_item).like(f'%{search_term}%').desc(),  # Contains the term
                        subquery.c.mpi_item.asc()  # Then sort alphabetically
                    )\
                    .offset((page - 1) * size)\
                    .limit(size)\
                    .all()
            
            # Format response
            formatted_items = [
                ItemInfo(
                    id=item.id,  # Use the database item ID
                    mpi_item=item.mpi_item or '',
                    original_item=item.original_item or '',
                    mpi_description=item.mpi_description or ''
                )
                for item in items
            ]
            
            # Calculate total pages
            pages = (total + size - 1) // size if size > 0 else 1
            
            return PaginatedItemInfoResponse(
                items=formatted_items,
                total=total,
                page=page,
                size=size,
                pages=pages
            )
            
        except Exception as e:
            logger.error(f"Error in search_mpi_items: {str(e)}", exc_info=True)
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
            
    def get_enriched_items_with_suppliers(self, items: List[ItemInfo], page: int = 1, size: int = 10):
        """
        Get enriched item information with both the cheapest price and supplier details.
        This combines the functionality of get_items_prices and get_cheapest_prices_per_supplier.
        
        Args:
            items (List[ItemInfo]): List of items to get prices for
            page (int): Page number for pagination (1-based)
            size (int): Number of items per page
            
        Returns:
            PaginatedEnrichedItemResponse: Paginated list of items with prices and supplier information
        """
        try:
            db = self._get_db_session()
            result = []
            
            # Calculate pagination indices
            start_idx = (page - 1) * size
            end_idx = start_idx + size
            
            # Get total count for pagination
            total_items = len(items)
            
            # Get the items for the current page
            paginated_items = items[start_idx:end_idx] if total_items > 0 else []
            
            for item in paginated_items:
                # If item ID is not provided, try to find it based on mpi_item
                item_id = item.id
                if item_id is None:
                    # Look up the item ID based on mpi_item
                    invoice_item = db.query(InvoiceItem.id).filter(
                        InvoiceItem.mpi_item == item.mpi_item
                    ).first()
                    
                    if invoice_item:
                        item_id = invoice_item.id
                    else:
                        # If we still can't find an ID, use 0 as a placeholder
                        item_id = 0
                
                # Get all prices for this item across all suppliers
                all_prices = db.query(
                    InvoiceItem.vendor,
                    InvoiceItem.cost,
                    Supplier.id.label('supplier_id')
                ).join(
                    Supplier, 
                    Supplier.supplier_name == InvoiceItem.vendor
                ).filter(
                    InvoiceItem.mpi_item == item.mpi_item,
                    InvoiceItem.cost.isnot(None),
                    InvoiceItem.vendor.isnot(None),
                    InvoiceItem.cost > 0  # Exclude zero prices
                ).all()
                
                if not all_prices:
                    continue
                
                # Get the absolute cheapest price across all suppliers and dates
                # Only consider prices greater than zero
                absolute_cheapest_price = min([float(cost) for _, cost, _ in all_prices if cost is not None and float(cost) > 0])
                
                # Get the lowest price per supplier for this item
                supplier_prices_dict = {}
                for vendor, cost, supplier_id in all_prices:
                    if vendor not in supplier_prices_dict or float(cost) < supplier_prices_dict[vendor][1]:
                        supplier_prices_dict[vendor] = (supplier_id, float(cost))
                
                # Format supplier prices with supplier ID
                suppliers = [
                    SupplierPriceInfo(
                        id=supplier_id,
                        name=vendor or "Unknown", 
                        unit_price=price
                    )
                    for vendor, (supplier_id, price) in supplier_prices_dict.items()
                ]
                
                # Sort suppliers by price (cheapest first)
                suppliers.sort(key=lambda x: x.unit_price)
                
                if not suppliers:
                    continue
                
                # Create enriched response
                result.append(
                    EnrichedItemPriceResponse(
                        id=item_id,  # Use the looked-up item ID from database
                        mpi_item=item.mpi_item or "",
                        original_item=item.original_item or "",
                        mpi_description=item.mpi_description or "",
                        cheapest_unit_price=absolute_cheapest_price,
                        suppliers=suppliers
                    )
                )
            
            # Calculate total pages
            pages = (total_items + size - 1) // size if size > 0 else 1
            
            return PaginatedEnrichedItemResponse(
                items=result,
                total=total_items,
                page=page,
                size=size,
                pages=pages
            )
            
        except Exception as e:
            logger.error(f"Error fetching enriched items with suppliers: {str(e)}", exc_info=True)
            raise
            
    def get_items_by_date_range_with_suppliers(
        self,
        from_date: date,
        to_date: date,
        unselected_items: Optional[List[ItemInfo]] = None,
        page: int = 1,
        size: int = 10
    ):
        """
        Get items within a date range with supplier information, optionally excluding specific items.
        
        Args:
            from_date (date): Start date for filtering
            to_date (date): End date for filtering
            unselected_items (Optional[List[ItemInfo]]): Optional list of items to exclude
            page (int): Page number for pagination (1-based)
            size (int): Number of items per page
            
        Returns:
            PaginatedEnrichedItemResponse: Paginated list of items with prices and supplier information
        """
        try:
            db = self._get_db_session()
            
            # Base query to get distinct items in the date range
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
            )
            
            # Add exclusion filter if unselected_items is provided
            if unselected_items and len(unselected_items) > 0:
                # Extract mpi_item values from the ItemInfo objects
                unselected_mpi_items = [item.mpi_item for item in unselected_items if item.mpi_item]
                if unselected_mpi_items:
                    query = query.filter(~InvoiceItem.mpi_item.in_(unselected_mpi_items))
            
            # Get total count for pagination
            total = query.distinct().count()
            
            # Apply pagination
            paginated_query = query.distinct()
            
            # For pagination, we need to use a subquery approach to avoid PostgreSQL limitations
            subquery = paginated_query.subquery()
            
            # Create a new query from the subquery
            items_query = db.query(
                subquery.c.id,
                subquery.c.mpi_item,
                subquery.c.original_item,
                subquery.c.mpi_description
            ).order_by(subquery.c.mpi_item)
            
            # Apply pagination to the outer query
            items = items_query.offset((page - 1) * size).limit(size).all()
            
            # Format items to ItemInfo objects
            item_infos = [
                ItemInfo(
                    id=item.id,  # Use the database item ID
                    mpi_item=item.mpi_item or '',
                    original_item=item.original_item or '',
                    mpi_description=item.mpi_description or ''
                )
                for item in items
            ]
            
            # Calculate total pages
            pages = (total + size - 1) // size if size > 0 else 1
            
            # Get enriched items with supplier information
            result = []
            
            for item in item_infos:
                # If item ID is not provided, try to find it based on mpi_item
                item_id = item.id
                if item_id is None:
                    # Look up the item ID based on mpi_item
                    invoice_item = db.query(InvoiceItem.id).filter(
                        InvoiceItem.mpi_item == item.mpi_item
                    ).first()
                    
                    if invoice_item:
                        item_id = invoice_item.id
                    else:
                        # If we still can't find an ID, use 0 as a placeholder
                        item_id = 0
                
                # Get all prices for this item across all suppliers
                all_prices = db.query(
                    InvoiceItem.vendor,
                    InvoiceItem.cost,
                    Supplier.id.label('supplier_id')
                ).join(
                    Supplier, 
                    Supplier.supplier_name == InvoiceItem.vendor
                ).filter(
                    InvoiceItem.mpi_item == item.mpi_item,
                    InvoiceItem.cost.isnot(None),
                    InvoiceItem.vendor.isnot(None),
                    InvoiceItem.date >= from_date,
                    InvoiceItem.date <= to_date
                ).all()
                
                if not all_prices:
                    continue
                
                # Get the absolute cheapest price across all suppliers and dates
                absolute_cheapest_price = min([float(cost) for _, cost, _ in all_prices if cost is not None])
                
                # Get the lowest price per supplier for this item
                supplier_prices_dict = {}
                for vendor, cost, supplier_id in all_prices:
                    if vendor not in supplier_prices_dict or float(cost) < supplier_prices_dict[vendor][1]:
                        supplier_prices_dict[vendor] = (supplier_id, float(cost))
                
                # Format supplier prices with supplier ID
                suppliers = [
                    SupplierPriceInfo(
                        id=supplier_id,
                        name=vendor or "Unknown", 
                        unit_price=price
                    )
                    for vendor, (supplier_id, price) in supplier_prices_dict.items()
                ]
                
                # Sort suppliers by price (cheapest first)
                suppliers.sort(key=lambda x: x.unit_price)
                
                if not suppliers:
                    continue
                
                # Create enriched response
                result.append(
                    EnrichedItemPriceResponse(
                        id=item.id,  # Use the item ID from the request
                        mpi_item=item.mpi_item or "",
                        original_item=item.original_item or "",
                        mpi_description=item.mpi_description or "",
                        cheapest_unit_price=absolute_cheapest_price,
                        suppliers=suppliers
                    )
                )
            
            return PaginatedEnrichedItemResponse(
                items=result,
                total=total,
                page=page,
                size=size,
                pages=pages
            )
            
        except Exception as e:
            logger.error(f"Error fetching items by date range with suppliers: {str(e)}", exc_info=True)
            raise
