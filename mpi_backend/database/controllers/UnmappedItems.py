from datetime import datetime, date
from mpi_backend.database.models import UnmappedItems
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.InvoiceItemsMapMart import InvoiceItemsMapMart
import pandas as pd
# Note: extract_supplier_id is not used in this controller
# from mpi_backend.utils.item_utils import (
#     extract_supplier_id
# )
from sqlalchemy import and_, or_, exists, text, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from typing import Dict, Any, Optional, List
from datetime import date
import logging
from sqlalchemy.orm import Session
from mpi_backend.utils.number_formatter import format_currency, format_quantity
from mpi_backend.database.dao import get_unmapped_items as dao_get_unmapped_items
from mpi_backend.database.dao import get_unmapped_items_graph_stats as dao_get_unmapped_items_graph_stats
from mpi_backend.database.dao.invoice_items_map import get_mapping_types
from mpi_backend.database.dao.invoice_items_map.get_unmapped_items import EXPECTED_MAPPING_TYPES
from mpi_backend.database.dao.invoice_items_map.constants import ALLOWED_GROUP_BY


logger = logging.getLogger(__name__)


class UnmappedItemsController:
    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self) -> Session:
        """
        Get a database session object, whether db_context is a factory or
        an existing session.
        """
        # Check if it's already a session instance (has query, add, commit)
        if hasattr(self.db_context, 'query') and hasattr(self.db_context, 'commit'):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

    def get_items_mappings(self):
        db = self._get_db_session()
        query_result = db.query(UnmappedItems).all()
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

    def insert_unmapped_item(self, item_code, description, supplier_id):
        db = self._get_db_session()
        new_item = UnmappedItems(
            google_sheet_name='',
            mpi_code='',
            description=description,
            supplier_item_ids=item_code,
            supplier_id=supplier_id,
        )
        try:
            db.add(new_item)
            db.commit()
        except IntegrityError as ie:
            logger.error(
                f"UnmappedItems insert failed with IntegrityError: {ie}. Attempting sequence resync and retry."
            )
            db.rollback()
            try:
                # Resync sequence to max(id) to avoid duplicate primary key values
                db.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence('unmapped_items','id'), "
                        "COALESCE((SELECT MAX(id) FROM unmapped_items), 1), true)"
                    )
                )
                db.add(new_item)
                db.commit()
                logger.info("UnmappedItems insert succeeded after sequence resync")
            except Exception as inner:
                logger.error(
                    f"UnmappedItems insert retry failed: {inner}. Skipping this unmapped item."
                )
                db.rollback()
        except Exception as e:
            logger.error(f"UnmappedItems insert failed: {e}")
            db.rollback()

    def is_item_code_present(self, item_code, supplier_id=None):
        """
        Check if an item code is present in unmapped items.

        Args:
            item_code (str): Item code to check
            supplier_id (int, optional): Supplier ID (not used for suffix cleaning)

        Returns:
            bool: True if item is present, False otherwise
        """
        try:
            db = self._get_db_session()
            # Get all unmapped items
            all_unmapped = db.query(UnmappedItems).all()

            # Check for exact match only
            for unmapped_item in all_unmapped:
                if unmapped_item.supplier_item_ids == item_code:
                    return True

            return False

        except Exception as e:
            print(f'Unmapped item-{item_code} could not be looked up in db ->{e}')
            return False

    def validate_request_params(
        self,
        db: Session,
        item_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        date_history: Optional[str] = None,
        order_by: Optional[list[Dict[str, str]]] = None,
        group_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate request parameters for unmapped items queries.

        Args:
            db: Database session
            item_type: The item type to validate (if provided)

        Raises:
            ValueError: If any parameter is invalid
        """
        mapping_types_result = get_mapping_types(db)
        valid_mapping_types = mapping_types_result.mapping_types

        valid_request = {}
        if item_type and item_type not in valid_mapping_types and item_type != 'all':
            raise ValueError(f"Invalid item_type: '{item_type}'. Must be one of: {valid_mapping_types}")
        valid_request['item_type'] = item_type

        try:
            if date_from:
                date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
                valid_request['date_from'] = date_from_obj
            if date_to:
                date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
                valid_request['date_to'] = date_to_obj
            if date_history:
                date_history_obj = datetime.strptime(date_history, "%Y-%m-%d").date()
                valid_request['date_history'] = date_history_obj
        except ValueError:
            raise

        # Provide default ordering if order_by is None or empty
        if not order_by:
            # Default ordering: descending by amount (highest amounts first)
            valid_request['order_by'] = [{"column": "amount", "order": "desc"}]
        else:
            # Validate order_by columns against the actual model
            mapper = inspect(InvoiceItemsMapMart)
            valid_columns = {col.key for col in mapper.columns}

            # Also include computed/aliased columns used in DAO queries
            # From get_unmapped_items.py DAO: original_description -> description
            column_mapping = {'original_item_id', 'original_description', 'quantity', 'times_bought', 'status'}
            valid_order_columns = valid_columns | column_mapping

            valid_orders = {"asc", "desc"}

            validated_order_by = []
            for ob in order_by:
                col = ob.get("column", "amount")
                order = ob.get("order", "desc").lower()

                if col not in valid_order_columns:
                    raise ValueError(f"Invalid order_by column: '{col}'. Valid columns: {sorted(valid_order_columns)}")
                if order not in valid_orders:
                    raise ValueError(f"Invalid order direction: '{order}'. Must be 'asc' or 'desc'")

                # We might need to map from the column that the frontend sent to the table column name
                validated_order_by.append({"column": col, "order": order})

            valid_request['order_by'] = validated_order_by

        # group_by has already been normalized and validated by the Pydantic schema.
        valid_request['group_by'] = group_by if group_by else None

        return valid_request

    def get_unmapped_items(
        self,
        item_type: str,
        db: Optional[Session] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        date_history: Optional[str] = None,
        supplier_names: Optional[List[str]] = None,
        search: Optional[str] = None,
        order_by: Optional[List[dict]] = None,
        page: int = 1,
        size: int = 10,
        group_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get unmapped items with pagination and filtering.

        Args:
            item_type (str): Must be one of the valid mapping types from the database
            date_from (date, optional): Start date filter
            date_to (date, optional): End date filter
            date_history (date, optional): Specific date for filtering
            supplier_names (List[str], optional): Supplier names to filter by
            page (int): Page number (1-based)
            size (int): Number of items per page

        Returns:
            Dict with items, pagination metadata
        """
        # Backwards compatibility for existing code
        if not db:
            db = self._get_db_session()

        # Validate request parameters
        valid_request = self.validate_request_params(db, item_type, date_from, date_to, date_history, order_by, group_by)

        try:
            logger.info("GETTING FROM ANALYTICS")
            return self._get_unmapped_items_from_analytics(
                db,
                valid_request['item_type'],
                valid_request.get('date_from'),
                valid_request.get('date_to'),
                valid_request.get('date_history'),
                supplier_names,
                search,
                valid_request.get('order_by'),
                page,
                size,
                valid_request.get('group_by')
            )
        except Exception as e:
            logger.exception(f"Error retrieving unmapped items from analytics: {e}")
            return {
                "items": [],
                "total_count": 0,
                "page": page,
                "size": size,
                "pages": 0
            }


    def _get_unmapped_items_from_analytics(
        self,
        db,
        item_type: str,
        date_from: Optional[date],
        date_to: Optional[date],
        date_history: Optional[date],
        supplier_names: Optional[List[str]],
        search: Optional[str],
        order_by: Optional[List[dict]],
        page: int,
        size: int,
        group_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get unmapped items from analytics.mart__invoice_items_map using DAO.

        Args:
            db: Database session
            item_type: Type of items - 'temporary', 'unmapped', or 'no_temporary'
            date_from: Start date filter
            date_to: End date filter
            date_history: Specific date for filtering
            supplier_names: List of supplier names to filter
            search: Search term for item/description
            order_by: List of order_by dicts
            page: Page number
            size: Items per page

        Returns:
            Dict with formatted items and pagination metadata
        """
        # Call DAO function
        dao_result = dao_get_unmapped_items(
            db=db,
            item_type=item_type,
            date_from=date_from,
            date_to=date_to,
            date_history=date_history,
            supplier_names=supplier_names,
            search=search,
            order_by=order_by,
            page=page,
            size=size,
            group_by=group_by
        )

        logger.info(f"DAO returned {len(dao_result.items)}")

        # Format items for controller response
        formatted_items = []
        for item in dao_result.items:
            # Format date if present
            item_date = item.get("date")
            if item_date:
                # Handle both datetime objects and strings
                if hasattr(item_date, 'strftime'):
                    item_date = item_date.strftime("%Y-%m-%d")
                else:
                    item_date = str(item_date)
            else:
                item_date = ""
            
            formatted_items.append({
                "original_item_id": item.get("original_item_id", ""),
                "original_description": item.get("original_description", ""),
                "cost": format_currency(item.get("cost") or 0.0),
                "amount": format_currency(item.get("amount") or 0.0),
                "quantity": int(item.get("quantity") or 0),
                "times_bought": int(item.get("times_bought") or 0),
                "sheet_name": item.get("sheet_name", ""),
                "supplier": item.get("supplier", ""),
                "mapping_type": item.get("mapping_type", ""),
                "is_isolated": bool(item.get("is_isolated", False)),
                "is_price_rerated": bool(item.get("is_price_rerated", False)),
                "original_quantity": int(item.get("original_quantity") or 0),
                "date": item_date
            })

        return {
            "items": formatted_items,
            "total_count": dao_result.total_count,
            "page": dao_result.page,
            "size": dao_result.size,
            "pages": dao_result.pages,
            "aggregates": dao_result.aggregates or {
                "total_cost": 0.0,
                "total_amount": 0.0,
                "total_qty": 0,
                "total_times_bought": 0,
            },
            # Exposed for mappings UI when group_by is set (per-group row counts for charts/labels)
            "group_counts": dao_result.group_counts,
        }

    def _get_unmapped_items_query(
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
            return self._get_temporary_items(
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
            return self._get_all_unmapped_items(
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
            return self._get_unmapped_items_logic(
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

    def _get_all_unmapped_items(
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
        query = db.query(InvoiceItem).filter(
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
        query = query.filter(~exists_condition)
        
        # Get unique items based on cleaned original item ID (without search filter first)
        return self._get_unique_items_with_pagination(db, query, page, size, order_by, search)

    def _get_unmapped_items_logic(
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
        base_unmapped = db.query(InvoiceItem).filter(
            or_(
                InvoiceItem.mpi_item == 'No Match',
                InvoiceItem.mpi_item.like('UIDI%'),
                InvoiceItem.mpi_description == 'No Match',
                InvoiceItem.mpi_description.like('UIDI%')
            )
        )

        # Apply common date/supplier filters first so subquery respects them too
        base_unmapped = self._apply_common_filters(
            base_unmapped,
            date_from,
            date_to,
            supplier_names,
        )

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
        base_unmapped = base_unmapped.filter(~exists_condition)

        # Alias for correlated NOT EXISTS check
        ItemAlias = aliased(InvoiceItem)

        # Now restrict to rows with NO sheet_name for the current rows
        # In production, empty sheet names have been converted to "NO SHEET NAME"
        query = base_unmapped.filter(
            or_(
                InvoiceItem.sheet_name.is_(None),
                InvoiceItem.sheet_name == '',
                InvoiceItem.sheet_name.ilike('NO SHEET NAME')
            )
        )

        # Exclude any vendor+item that has at least one unmapped row WITH a sheet_name
        # so that mixed groups (some rows with sheet, some without) are counted only in
        # the "temporary" bucket and not here.
        exists_conditions = [
            ItemAlias.vendor == InvoiceItem.vendor,
            ItemAlias.item == InvoiceItem.item,
            # Consider only active (or NULL) rows like the global filter
            or_(ItemAlias.is_active.is_(True), ItemAlias.is_active.is_(None)),
            # Only among unmapped rows
            or_(
                ItemAlias.mpi_item == 'No Match',
                ItemAlias.mpi_item.like('UIDI%'),
                ItemAlias.mpi_description == 'No Match',
                ItemAlias.mpi_description.like('UIDI%'),
            ),
            # With a non-empty sheet_name (excluding "NO SHEET NAME" which is treated as empty)
            and_(
                ItemAlias.sheet_name.isnot(None), 
                ItemAlias.sheet_name != '',
                ~ItemAlias.sheet_name.ilike('NO SHEET NAME')
            ),
        ]

        # Apply date range to the correlated EXISTS so partitioning respects filters
        if date_from:
            exists_conditions.append(ItemAlias.date >= date_from)
        if date_to:
            exists_conditions.append(ItemAlias.date <= date_to)

        query = query.filter(~exists().where(and_(*exists_conditions)))

        # Get unique items based on original item ID per supplier
        return self._get_unique_items_with_pagination(db, query, page, size, order_by, search)

    def _get_temporary_items(
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
        # Items must have a sheet_name (not NULL, not empty, and not "NO SHEET NAME")
        query = db.query(InvoiceItem).filter(
            and_(
                InvoiceItem.sheet_name.isnot(None),
                InvoiceItem.sheet_name != '',
                ~InvoiceItem.sheet_name.ilike('NO SHEET NAME'),
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
        query = query.filter(~exists_condition)
        
        # Get unique items based on cleaned original item ID (without search filter first)
        return self._get_unique_items_with_pagination(db, query, page, size, order_by, search)

    def _apply_common_filters(self, query, date_from, date_to, supplier_names):
        """Apply common date and supplier filters"""
        
        # Apply date filters
        if date_from:
            query = query.filter(InvoiceItem.date >= date_from)
        if date_to:
            query = query.filter(InvoiceItem.date <= date_to)
        
        # Apply supplier filter
        if supplier_names and len(supplier_names) > 0:
            # Skip if 'All' is in the list
            if not (len(supplier_names) == 1 and supplier_names[0].lower() == 'all'):
                query = query.filter(InvoiceItem.vendor.in_(supplier_names))
        
        return query

    def _get_unique_items_with_pagination(self, db, query, page, size, order_by=None, search=None):
        """Get unique items per supplier with supplier suffixes for distinction"""
        
        # Use a CTE to aggregate unique items per supplier on the DB side
        from sqlalchemy import func
        base = (
            query.with_entities(
                InvoiceItem.vendor.label("supplier"),
                InvoiceItem.item.label("original_item_id"),
                func.min(InvoiceItem.description).label("original_description"),
                func.min(InvoiceItem.sheet_name).label("sheet_name"),
                func.min(InvoiceItem.cost).label("cost"),
                func.min(InvoiceItem.qty).label("quantity"),
                (func.min(InvoiceItem.cost) * func.min(InvoiceItem.qty)).label("amount"),
            )
            .filter(
                InvoiceItem.item.isnot(None),
                InvoiceItem.item != "",
            )
            .group_by(
                InvoiceItem.vendor,
                InvoiceItem.item,
            )
            .cte("unique_items_cte")
        )

        q = db.query(
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
            q = q.filter(
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
        total_count = q.count()
        if size > 0:
            q = q.offset((page - 1) * size).limit(size)

        rows = q.all()
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

    def get_unmapped_items_graph_stats(
        self,
        item_type: str,
        db: Optional[Session] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        date_history: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get date-based statistics for unmapped items graph (no pagination).
        Returns dynamic mapping type counts.

        Args:
            item_type (str): Must be one of the valid mapping types or 'all'
            date_from (date, optional): Start date filter (reserved for future use)
            date_to (date, optional): End date filter (reserved for future use)
            supplier_names (List[str], optional): Supplier names to filter by
            search (str, optional): Search term for filtering

        Returns:
            Dict with date_stats array and dynamic totals
            Example: {
                "date_stats": [{"date": "2024-01-01", "permanent": 10, "no_match": 5}],
                "totals": {"permanent": 10, "no_match": 5, "total": 15}
            }
        """
        # Backwards compatibility for existing code
        if not db:
            db = self._get_db_session()

        # Validate request parameters (skip order_by validation since we don't need it)
        valid_request = self.validate_request_params(db, item_type, date_from, date_to, date_history, order_by=None)

        try:
            logger.info("Getting graph stats from analytics")
            
            # Call DAO function - returns dynamic mapping type keys
            date_stats = dao_get_unmapped_items_graph_stats(
                db=db,
                item_type=valid_request['item_type'],
                date_from=valid_request.get('date_from'),
                date_to=valid_request.get('date_to'),
                date_history=valid_request.get('date_history'),
                supplier_names=supplier_names,
                search=search,
            )

            # Calculate totals dynamically based on whatever mapping types are present
            # Initialize with all expected mapping types set to 0
            totals: Dict[str, int] = {mt: 0 for mt in EXPECTED_MAPPING_TYPES}
            total_count = 0

            for stat in date_stats:
                for key, value in stat.items():
                    if key == "date":
                        continue  # Skip the date field
                    if isinstance(value, (int, float)):
                        if key not in totals:
                            totals[key] = 0
                        totals[key] += int(value)
                        total_count += int(value)

            totals["total"] = total_count

            return {
                "date_stats": date_stats,
                "totals": totals
            }

        except Exception as e:
            logger.exception(f"Error retrieving graph stats: {e}")
            return {
                "date_stats": [],
                "totals": {"total": 0}
            }


