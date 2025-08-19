from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, text
from typing import List, Optional, Dict, Any
from datetime import date
import logging

from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.database.schemas.MonthlyComparison import (
    ItemInfo, 
    ItemPriceResponse,
    SupplierPriceInfo,
    PaginatedItemInfoResponse,
    EnrichedItemPriceResponse,
    PaginatedEnrichedItemResponse
)

logger = logging.getLogger(__name__)

class MonthlyComparisonController:
    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self) -> Session:
        """Get a database session object, whether db_context is a factory or session."""
        # Check if it's already a session instance (has query, add, commit methods)
        if hasattr(self.db_context, 'query') and hasattr(self.db_context, 'commit'):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

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

            # Count distinct mpi_item within filters for stable pagination metadata
            total = db.query(func.count(func.distinct(InvoiceItem.mpi_item))).filter(
                and_(
                    InvoiceItem.date >= from_date,
                    InvoiceItem.date <= to_date,
                    InvoiceItem.mpi_item != 'No Match',
                    InvoiceItem.mpi_description.notlike('%No Match%'),
                    ~InvoiceItem.mpi_item.contains('UIDI'),
                    ~InvoiceItem.mpi_description.contains('UIDI'),
                    ~InvoiceItem.mpi_item.like('%10 Materials%')
                )
            ).scalar() or 0

            # Deterministic selection: one row per mpi_item (latest date, tie-break by id)
            # Using Postgres DISTINCT ON for stable, unique results
            distinct_sql = text(
                """
                SELECT DISTINCT ON (ii.mpi_item)
                    ii.id,
                    ii.mpi_item,
                    ii.item,
                    ii.mpi_description
                FROM invoice_items ii
                WHERE ii.date >= :from_date
                  AND ii.date <= :to_date
                  AND ii.mpi_item <> 'No Match'
                  AND ii.mpi_description NOT LIKE '%No Match%'
                  AND ii.mpi_item NOT LIKE '%UIDI%'
                  AND ii.mpi_description NOT LIKE '%UIDI%'
                  AND ii.mpi_item NOT LIKE '%10 Materials%'
                ORDER BY ii.mpi_item ASC, ii.date DESC, ii.id ASC
                OFFSET :offset LIMIT :limit
                """
            )

            offset_value = (page - 1) * size
            rows = db.execute(
                distinct_sql,
                {
                    "from_date": from_date,
                    "to_date": to_date,
                    "offset": offset_value,
                    "limit": size,
                },
            ).fetchall()

            # Calculate total pages
            pages = (total + size - 1) // size if size > 0 else 1

            # Format response
            items = [
                ItemInfo(
                    id=row[0] or 0,
                    mpi_item=row[1] or '',
                    original_item=row[2] or '',
                    mpi_description=row[3] or '',
                )
                for row in rows
            ]

            return PaginatedItemInfoResponse(
                items=items,
                total=total,
                page=page,
                size=size,
                pages=pages,
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
            # Strip spaces from search term and convert to uppercase
            search_term = (search_term or '').strip().upper()
            
            if not search_term or len(search_term) < 1:
                return PaginatedItemInfoResponse(
                    items=[],
                    total=0,
                    page=page,
                    size=size,
                    pages=0
                )
            
            # Build base query with common filters - fetch full items for suffix calculation
            query = db.query(InvoiceItem).filter(
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
            
            # Apply pagination and ordering directly to the main query
            # For DISTINCT queries, we need to include ORDER BY expressions in the SELECT
            items = query.distinct()\
                    .add_columns(
                        func.upper(InvoiceItem.mpi_item).like(f'{search_term}%').label('starts_with'),
                        func.upper(InvoiceItem.mpi_item).like(f'%{search_term}%').label('contains_term')
                    )\
                    .order_by(
                        func.upper(InvoiceItem.mpi_item).like(f'{search_term}%').desc(),  # Starts with first
                        func.upper(InvoiceItem.mpi_item).like(f'%{search_term}%').desc(),  # Contains the term
                        InvoiceItem.mpi_item.asc()  # Then sort alphabetically
                    )\
                    .offset((page - 1) * size)\
                    .limit(size)\
                    .all()
            
            # Extract the InvoiceItem objects from the result tuples
            invoice_items = [item[0] for item in items]
            
            # Format response with suffixed item codes
            formatted_items = [
                ItemInfo(
                    id=item.id,  # Use the database item ID
                    mpi_item=item.mpi_item or '',
                    original_item=item.item or '',  # Use full item code
                    mpi_description=item.mpi_description or ''
                )
                for item in invoice_items
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
        OPTIMIZED: Get enriched item information with both the cheapest price and supplier details.
        Uses bulk SQL queries instead of individual item processing for better performance.
        
        Args:
            items (List[ItemInfo]): List of items to get prices for
            page (int): Page number for pagination (1-based)
            size (int): Number of items per page
            
        Returns:
            PaginatedEnrichedItemResponse: Paginated list of items with prices and supplier information
        """
        import time
        start_time = time.time()
        
        try:
            db = self._get_db_session()
            
            # Calculate pagination indices
            start_idx = (page - 1) * size
            end_idx = start_idx + size
            total_items = len(items)
            
            # Get the items for the current page
            paginated_items = items[start_idx:end_idx] if total_items > 0 else []
            
            if not paginated_items:
                return PaginatedEnrichedItemResponse(
                    items=[],
                    total=total_items,
                    page=page,
                    size=size,
                    pages=0
                )
            
            # Extract mpi_items for bulk processing
            mpi_items = [item.mpi_item for item in paginated_items if item.mpi_item]
            
            if not mpi_items:
                return PaginatedEnrichedItemResponse(
                    items=[],
                    total=total_items,
                    page=page,
                    size=size,
                    pages=(total_items + size - 1) // size if size > 0 else 1
                )
            
            # Use optimized SQL query to get all price data at once
            price_query = text("""
                WITH supplier_prices AS (
                    SELECT 
                        ii.mpi_item,
                        ii.vendor,
                        s.id as supplier_id,
                        MIN(ii.cost) as min_cost
                    FROM invoice_items ii
                    LEFT JOIN suppliers s ON s.supplier_name = ii.vendor
                    WHERE ii.mpi_item = ANY(:mpi_items)
                    AND ii.cost IS NOT NULL 
                    AND ii.cost > 0
                    AND ii.vendor IS NOT NULL
                    GROUP BY ii.mpi_item, ii.vendor, s.id
                ),
                item_cheapest AS (
                    SELECT 
                        mpi_item,
                        MIN(min_cost) as absolute_cheapest_price
                    FROM supplier_prices
                    GROUP BY mpi_item
                )
                SELECT 
                    sp.mpi_item,
                    sp.vendor,
                    sp.supplier_id,
                    sp.min_cost,
                    ic.absolute_cheapest_price
                FROM supplier_prices sp
                JOIN item_cheapest ic ON sp.mpi_item = ic.mpi_item
                ORDER BY sp.mpi_item, sp.min_cost
            """)
            
            # Execute the optimized query
            query_result = db.execute(price_query, {"mpi_items": mpi_items}).fetchall()
            
            # Group results by mpi_item for efficient processing
            price_data = {}
            for row in query_result:
                mpi_item, vendor, supplier_id, min_cost, absolute_cheapest = row
                
                if mpi_item not in price_data:
                    price_data[mpi_item] = {
                        'absolute_cheapest_price': float(absolute_cheapest),
                        'suppliers': []
                    }
                
                price_data[mpi_item]['suppliers'].append(
                    SupplierPriceInfo(
                        id=supplier_id,
                        name=vendor or "Unknown",
                        unit_price=float(min_cost)
                    )
                )
            
            # Build the result using the pre-processed data
            result = []
            for item in paginated_items:
                if item.mpi_item in price_data:
                    data = price_data[item.mpi_item]
                    suppliers = sorted(data['suppliers'], key=lambda x: x.unit_price)
                    result.append(
                        EnrichedItemPriceResponse(
                            id=item.id or 0,
                            mpi_item=item.mpi_item or "",
                            original_item=item.original_item or "",
                            mpi_description=item.mpi_description or "",
                            cheapest_unit_price=data['absolute_cheapest_price'],
                            suppliers=suppliers
                        )
                    )
                else:
                    # Ensure item appears even if no suppliers/prices found
                    result.append(
                        EnrichedItemPriceResponse(
                            id=item.id or 0,
                            mpi_item=item.mpi_item or "",
                            original_item=item.original_item or "",
                            mpi_description=item.mpi_description or "",
                            cheapest_unit_price=0.0,
                            suppliers=[]
                        )
                    )
            
            # Calculate total pages
            pages = (total_items + size - 1) // size if size > 0 else 1
            
            processing_time = time.time() - start_time
            logger.info(f"Enriched items with suppliers processed in {processing_time:.2f}s "
                       f"for {len(paginated_items)} items")
            
            return PaginatedEnrichedItemResponse(
                items=result,
                total=total_items,
                page=page,
                size=size,
                pages=pages
            )
            
        except Exception as e:
            logger.error(f"Error in optimized enriched items with suppliers: {str(e)}", exc_info=True)
            logger.info("Falling back to legacy method...")
            return self._get_enriched_items_with_suppliers_legacy(items, page, size)
    
    def _get_enriched_items_with_suppliers_legacy(self, items: List[ItemInfo], page: int = 1, size: int = 10):
        """
        Legacy implementation as fallback for get_enriched_items_with_suppliers.
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

            # Build dynamic filter SQL for exclusions
            excluded_list = [item.mpi_item for item in (unselected_items or []) if getattr(item, 'mpi_item', None)]

            # Total unique items by mpi_item under filters and exclusions
            total_query = db.query(func.count(func.distinct(InvoiceItem.mpi_item))).filter(
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
            if excluded_list:
                total_query = total_query.filter(~InvoiceItem.mpi_item.in_(excluded_list))
            total = total_query.scalar() or 0

            # Deterministic page of unique items (one per mpi_item)
            # Use DISTINCT ON with stable ordering
            base_sql = """
                SELECT DISTINCT ON (ii.mpi_item)
                    ii.id,
                    ii.mpi_item,
                    ii.item,
                    ii.mpi_description,
                    ii.date
                FROM invoice_items ii
                WHERE ii.date >= :from_date
                  AND ii.date <= :to_date
                  AND ii.mpi_item <> 'No Match'
                  AND ii.mpi_description NOT LIKE '%No Match%'
                  AND ii.mpi_item NOT LIKE '%UIDI%'
                  AND ii.mpi_description NOT LIKE '%UIDI%'
                  AND ii.mpi_item NOT LIKE '%10 Materials%'
            """
            if excluded_list:
                base_sql += "\n                  AND NOT (ii.mpi_item = ANY(:excluded))\n"
            base_sql += """
                ORDER BY ii.mpi_item ASC, ii.date DESC, ii.id ASC
                OFFSET :offset LIMIT :limit
            """

            offset_value = (page - 1) * size
            params: Dict[str, Any] = {
                "from_date": from_date,
                "to_date": to_date,
                "offset": offset_value,
                "limit": size,
            }
            if excluded_list:
                params["excluded"] = excluded_list

            rows = db.execute(text(base_sql), params).fetchall()

            # Convert to ItemInfo list
            item_infos = [
                ItemInfo(
                    id=row[0] or 0,
                    mpi_item=row[1] or '',
                    original_item=row[2] or '',
                    mpi_description=row[3] or '',
                )
                for row in rows
            ]

            # Calculate total pages
            pages = (total + size - 1) // size if size > 0 else 1

            # Enrich with supplier information
            result = []
            for item in item_infos:
                item_id = item.id or 0

                # Get all prices for this item across all suppliers within date range
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
                    InvoiceItem.cost > 0,
                    InvoiceItem.vendor.isnot(None),
                    InvoiceItem.date >= from_date,
                    InvoiceItem.date <= to_date
                ).all()

                # Keep the item in the result even if no supplier prices in range
                if not all_prices:
                    result.append(
                        EnrichedItemPriceResponse(
                            id=item_id,
                            mpi_item=item.mpi_item or "",
                            original_item=item.original_item or "",
                            mpi_description=item.mpi_description or "",
                            cheapest_unit_price=0.0,
                            suppliers=[],
                        )
                    )
                    continue

                # Absolute cheapest price across all suppliers and dates (> 0)
                absolute_cheapest_price = min(
                    [float(cost) for _, cost, _ in all_prices if cost is not None and float(cost) > 0]
                )

                # Lowest price per supplier
                supplier_prices_dict: Dict[str, Any] = {}
                for vendor, cost, supplier_id in all_prices:
                    if cost is None:
                        continue
                    price_value = float(cost)
                    if vendor not in supplier_prices_dict or price_value < supplier_prices_dict[vendor][1]:
                        supplier_prices_dict[vendor] = (supplier_id, price_value)

                suppliers = [
                    SupplierPriceInfo(
                        id=supplier_id,
                        name=vendor or "Unknown",
                        unit_price=price
                    )
                    for vendor, (supplier_id, price) in supplier_prices_dict.items()
                ]

                suppliers.sort(key=lambda x: x.unit_price)
                if not suppliers:
                    continue

                result.append(
                    EnrichedItemPriceResponse(
                        id=item_id,
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
                pages=pages,
            )
            
        except Exception as e:
            logger.error(f"Error fetching items by date range with suppliers: {str(e)}", exc_info=True)
            raise
