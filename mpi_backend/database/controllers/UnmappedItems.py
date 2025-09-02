from mpi_backend.database.models import UnmappedItems
from mpi_backend.database.models.InvoiceItems import InvoiceItem
import pandas as pd
# Note: extract_supplier_id is not used in this controller
# from mpi_backend.utils.item_utils import (
#     extract_supplier_id
# )
from sqlalchemy import and_, or_, exists, text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from typing import Dict, Any, Optional, List
from datetime import date
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from mpi_backend.utils.number_formatter import format_currency, format_quantity

logger = logging.getLogger(__name__)


class UnmappedItemsController:
    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self) -> AsyncSession:
        """
        Get a database session object, whether db_context is a factory or
        an existing session.
        """
        # Check if it's already a session instance (has query, add, commit)
        if (hasattr(self.db_context, 'query') and 
            hasattr(self.db_context, 'commit')):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

    async def get_items_mappings(self):
        result = await self.db_context.execute(select(UnmappedItems))
        query_result = result.scalars().all()
        data = [
            (
                item.google_sheet_name,
                item.mpi_code,
                item.description,
                item.supplier_item_ids,
                item.supplier_id,
            )
            for item in query_result
        ]
        columns = [
            'google_sheet_name',
            'mpi_code',
            'description',
            'supplier_item_ids',
            'supplier_id',
        ]
        items_mappings = pd.DataFrame(data, columns=columns)
        return items_mappings

    async def insert_unmapped_item(self, item_code, description, supplier_id):
        new_item = UnmappedItems(
            google_sheet_name='',
            mpi_code='',
            description=description,
            supplier_item_ids=item_code,
            supplier_id=supplier_id,
        )
        try:
            self.db_context.add(new_item)
            await self.db_context.commit()
        except IntegrityError as ie:
            logger.error(
                f"UnmappedItems insert failed with IntegrityError: {ie}. Attempting sequence resync and retry."
            )
            await self.db_context.rollback()
            try:
                # Resync sequence to max(id) to avoid duplicate primary key values
                await self.db_context.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence('unmapped_items','id'), "
                        "COALESCE((SELECT MAX(id) FROM unmapped_items), 1), true)"
                    )
                )
                self.db_context.add(new_item)
                await self.db_context.commit()
                logger.info("UnmappedItems insert succeeded after sequence resync")
            except Exception as inner:
                logger.error(
                    f"UnmappedItems insert retry failed: {inner}. Skipping this unmapped item."
                )
                await self.db_context.rollback()
        except Exception as e:
            logger.error(f"UnmappedItems insert failed: {e}")
            await self.db_context.rollback()

    async def is_item_code_present(self, item_code, supplier_id=None):
        """
        Check if an item code is present in unmapped items.
        
        Args:
            item_code (str): Item code to check
            supplier_id (int, optional): Supplier ID (not used for suffix cleaning)
            
        Returns:
            bool: True if item is present, False otherwise
        """
        try:
            # Get all unmapped items
            result = await self.db_context.execute(select(UnmappedItems))
            all_unmapped = result.scalars().all()
            
            # Check for exact match only
            for unmapped_item in all_unmapped:
                if unmapped_item.supplier_item_ids == item_code:
                    return True
                    
            return False
            
        except Exception as e:
            print(f'Unmapped item-{item_code} could not be looked up in db ->{e}')
            return False

    async def get_unmapped_items(
        self,
        item_type: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        search: Optional[str] = None,
        order_by: Optional[List[dict]] = None,
        page: int = 1,
        size: int = 10
    ) -> Dict[str, Any]:
        """
        Get unmapped items with pagination and filtering.
        
        Args:
            item_type (str): 'temporary' or 'unmapped'
            date_from (date, optional): Start date filter
            date_to (date, optional): End date filter
            supplier_names (List[str], optional): Supplier names to filter by
            page (int): Page number (1-based)
            size (int): Number of items per page
            
        Returns:
            Dict with items, pagination metadata
        """
        try:
            return await self._get_unmapped_items_query(
                self.db_context,
                item_type,
                date_from,
                date_to,
                supplier_names,
                search,
                order_by,
                page,
                size,
            )
        except Exception as e:
            logger.error(f"Error retrieving unmapped items: {e}")
            return {
                "items": [],
                "total_count": 0,
                "page": page,
                "size": size,
                "pages": 0
            }

    async def _get_unmapped_items_query(
        self,
        db,
        item_type: str,
        date_from: Optional[date],
        date_to: Optional[date],
        supplier_names: Optional[List[str]],
        search: Optional[str],
        order_by: Optional[List[dict]],
        page: int,
        size: int
    ) -> Dict[str, Any]:
        """Internal method to execute the unmapped items query"""
        
        if item_type == "temporary":
            return await self._get_temporary_items(
                db,
                date_from,
                date_to,
                supplier_names,
                search,
                order_by,
                page,
                size,
            )
        elif item_type == "unmapped":
            return await self._get_all_unmapped_items(
                db,
                date_from,
                date_to,
                supplier_names,
                search,
                order_by,
                page,
                size,
            )
        elif item_type == "no_temporary":
            return await self._get_unmapped_items_logic(
                db,
                date_from,
                date_to,
                supplier_names,
                search,
                order_by,
                page,
                size,
            )
        else:
            raise ValueError(
                (
                    "Invalid item_type: {item_type}. Must be 'temporary', "
                    "'unmapped', or 'no_temporary'"
                ).format(item_type=item_type)
            )

    async def _get_all_unmapped_items(
        self,
        db,
        date_from: Optional[date],
        date_to: Optional[date],
        supplier_names: Optional[List[str]],
        search: Optional[str],
        order_by: Optional[List[dict]],
        page: int,
        size: int
    ) -> Dict[str, Any]:
        """Get ALL items with No Match or UIDI regardless of sheet_name, but EXCLUDE items with valid mappings"""
        
        # Base query for all unmapped items (No Match or UIDI)
        query = select(InvoiceItem).where(
            or_(
                InvoiceItem.mpi_item == 'No Match',
                InvoiceItem.mpi_item.like('UIDI%'),
                InvoiceItem.mpi_description == 'No Match',
                InvoiceItem.mpi_description.like('UIDI%')
            )
        )
        
        # Apply filters (date and supplier filters)
        query = self._apply_common_filters(query, date_from, date_to, supplier_names)
        
        # Filter out items that have valid mappings using a single query
        from mpi_backend.database.models.ItemsMapping import ItemsMapping
        from mpi_backend.database.models.Suppliers import Supplier
        
        # Build the exists condition for valid mappings
        exists_condition = exists().where(
            and_(
                ItemsMapping.supplier_item_ids == InvoiceItem.item,
                ItemsMapping.supplier_id == Supplier.id,
                Supplier.supplier_name == InvoiceItem.vendor
            )
        )
        
        # Apply the filter to exclude items with valid mappings
        query = query.where(~exists_condition)
        
        # Get unique items based on cleaned original item ID (without search filter first)
        return await self._get_unique_items_with_pagination(db, query, page, size, order_by, search)

    async def _get_unmapped_items_logic(
        self,
        db,
        date_from: Optional[date],
        date_to: Optional[date],
        supplier_names: Optional[List[str]],
        search: Optional[str],
        order_by: Optional[List[dict]],
        page: int,
        size: int
    ) -> Dict[str, Any]:
        """
        Get items that do not have a sheet_name and have no valid mapping.

        This returns only those (vendor, item) groups that are truly
        "no temporary" – i.e. none of their unmapped rows has a non-empty
        sheet_name. This guarantees that counts of "temporary" and
        "no_temporary" partition the "unmapped" set without overlap.
        """

        # Start from rows that are unmapped (No Match or UIDI), regardless of sheet_name
        base_unmapped = select(InvoiceItem).where(
            or_(
                InvoiceItem.mpi_item == 'No Match',
                InvoiceItem.mpi_item.like('UIDI%'),
                InvoiceItem.mpi_description == 'No Match',
                InvoiceItem.mpi_description.like('UIDI%')
            )
        )

        # Apply common date/supplier filters first so subquery respects them too
        base_unmapped = self._apply_common_filters(base_unmapped, date_from, date_to, supplier_names)
        
        # Get unique items based on cleaned original item ID (without search filter first)
        return await self._get_unique_items_with_pagination(db, base_unmapped, page, size, order_by, search)

    async def _get_temporary_items(
        self,
        db,
        date_from: Optional[date],
        date_to: Optional[date],
        supplier_names: Optional[List[str]],
        search: Optional[str],
        order_by: Optional[List[dict]],
        page: int,
        size: int
    ) -> Dict[str, Any]:
        """Get items that have a sheet_name but are 'No Match' or start with 'UIDI'"""
        
        # Base query for temporary items
        query = select(InvoiceItem).where(
            and_(
                InvoiceItem.sheet_name.isnot(None),
                InvoiceItem.sheet_name != '',
                or_(
                    InvoiceItem.mpi_item == 'No Match',
                    InvoiceItem.mpi_item.like('UIDI%'),
                    InvoiceItem.mpi_description == 'No Match',
                    InvoiceItem.mpi_description.like('UIDI%')
                )
            )
        )
        
        # Apply filters (date and supplier filters)
        query = self._apply_common_filters(query, date_from, date_to, supplier_names)
        
        # Filter out items that have valid mappings using a single query
        from mpi_backend.database.models.ItemsMapping import ItemsMapping
        from mpi_backend.database.models.Suppliers import Supplier
        
        # Build the exists condition for valid mappings
        exists_condition = exists().where(
            and_(
                ItemsMapping.supplier_item_ids == InvoiceItem.item,
                ItemsMapping.supplier_id == Supplier.id,
                Supplier.supplier_name == InvoiceItem.vendor
            )
        )
        
        # Apply the filter to exclude items with valid mappings
        query = query.where(~exists_condition)
        
        # Get unique items based on cleaned original item ID (without search filter first)
        return await self._get_unique_items_with_pagination(db, query, page, size, order_by, search)

    def _apply_common_filters(self, query, date_from, date_to, supplier_names):
        """Apply common date and supplier filters"""
        
        # Apply date filters
        if date_from:
            query = query.where(InvoiceItem.date >= date_from)
        if date_to:
            query = query.where(InvoiceItem.date <= date_to)
        
        # Apply supplier filter
        if supplier_names and len(supplier_names) > 0:
            # Skip if 'All' is in the list
            if not (len(supplier_names) == 1 and supplier_names[0].lower() == 'all'):
                query = query.where(InvoiceItem.vendor.in_(supplier_names))
        
        return query

    async def _get_unique_items_with_pagination(self, db, query, page, size, order_by=None, search=None):
        """Get unique items per supplier with supplier suffixes for distinction"""
        
        # Use a CTE to aggregate unique items per supplier on the DB side
        from sqlalchemy import func
        base = (
            select(
                InvoiceItem.vendor.label("supplier"),
                InvoiceItem.item.label("original_item_id"),
                func.min(InvoiceItem.description).label("original_description"),
                func.min(InvoiceItem.sheet_name).label("sheet_name"),
                func.min(InvoiceItem.cost).label("cost"),
                func.min(InvoiceItem.qty).label("quantity"),
                (func.min(InvoiceItem.cost) * func.min(InvoiceItem.qty)).label("amount"),
            )
            .where(
                InvoiceItem.item.isnot(None),
                InvoiceItem.item != "",
            )
            .group_by(
                InvoiceItem.vendor,
                InvoiceItem.item,
            )
            .cte("unique_items_cte")
        )

        q = select(
            base.c.original_item_id,
            base.c.original_description,
            base.c.cost,
            base.c.amount,
            base.c.quantity,
            base.c.sheet_name,
            base.c.supplier,
        )

        # Apply search AFTER aggregation (SQL-level for consistent counts/pagination)
        if search and search.strip():
            s = f"%{search.strip()}%"
            q = q.where(
                or_(
                    base.c.original_item_id.ilike(s),
                    base.c.original_description.ilike(s),
                )
            )

        # Ordering
        if order_by and len(order_by) > 0:
            for order_item in order_by:
                col = order_item.get("column", "amount")
                order = order_item.get("order", "desc").lower()
                col_expr = {
                    "amount": base.c.amount,
                    "cost": base.c.cost,
                    "quantity": base.c.quantity,
                    "supplier": base.c.supplier,
                    "original_item_id": base.c.original_item_id,
                }.get(col, base.c.amount)
                q = q.order_by(col_expr.desc() if order == "desc" else col_expr.asc())
        else:
            q = q.order_by(base.c.amount.desc())

        # Pagination (SQL-level only)
        count_result = await db.execute(select(func.count()).select_from(q.subquery()))
        total_count = count_result.scalar()
        if size > 0:
            q = q.offset((page - 1) * size).limit(size)

        result = await db.execute(q)
        rows = result.all()
        unique_items = []
        for r in rows:
            unique_items.append(
                {
                    "original_item_id": r.original_item_id,
                    "original_description": r.original_description or "",
                    "cost": format_currency(r.cost or 0.0),
                    "amount": format_currency(r.amount or 0.0),
                    "quantity": format_quantity(r.quantity or 0),
                    "sheet_name": r.sheet_name or "",
                    "supplier": r.supplier or "",
                }
            )
        
        # Keep ordering as defined by SQL to ensure stable pagination
        
        # Calculate pagination
        if total_count == 0:
            total_pages = 0
        else:
            total_pages = (total_count + size - 1) // size if size > 0 else 1
        
        # Results are already paginated at SQL level; do not re-slice here
        paginated_items = unique_items
        
        # Log summary for debugging
        logger.info(f"Pagination result: {len(paginated_items)} items")
        
        return {
            "items": paginated_items,
            "total_count": total_count,
            "page": page,
            "size": size,
            "pages": total_pages
        }


