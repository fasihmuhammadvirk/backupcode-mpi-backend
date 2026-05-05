import logging
from typing import Dict, Any, List, Sequence, Mapping

from sqlalchemy import text, RowMapping, desc, UUID
from sqlalchemy.orm import Session

from mpi_backend.database.models import PurchaseOrderDrafts
from mpi_backend.database.schemas.PurchaseOrder import PODraftCreate
from mpi_backend.database.schemas.PurchaseOrder import (
    POBulkImportRequest
)

logger = logging.getLogger(__name__)


class PurchaseOrderDAO:
    """Data Access Object for Purchase Order price comparison operations."""

    def get_price_comparison(
            self,
            db: Session,
            filter_request: POBulkImportRequest
    ) -> Sequence[Mapping[str, Any]]:
        """
        Get purchase order price comparison based on provided filters.

        Args:
            db: SQLAlchemy Session object.
            filter_request: Filters for price comparison.

        Returns:
            List of dicts with fields:
            - invoice_item_id: ID of invoice item entry in model_extracted_data
            - filename: Filename contains file path to download original file
            - item_code: Item code extracted from invoice
            - item_description: Item description extracted from invoice
            - item_cost: Item cost extracted from invoice
            - item_quantity: Item quantity extracted from invoice
            - purchase_date: Date of purchase
            - supplier_id: Supplier ID from suppliers table
            - supplier_name: Supplier name as per suppliers table
            - item_mpi_code: Matched MPI code for item based on item code
            - item_mpi_description: Matched MPI description for item based on item code
        """
        try:
            logger.info(f"Constructing price comparison query with filters: {filter_request}")

            """
            First get items with date range filter.
            """
            rows = self._get_items(db, filter_request)

            """
            When items are not found for date range then we need to get items without date range filter.
            Check if from_date is found in the request:
                - If from_date is not found then the item is already not present in the mart so checking again makes no sense
            """
            rows_for_unfound_items = []
            if filter_request.from_date:
                rows_for_unfound_items = self._get_rows_for_unfound_items(
                    db, filter_request,
                    self._extract_not_found_item_mpi_codes(rows, filter_request.item_mpi_codes)
                )

            logger.info(f"Retrieved {len(rows)} rows from price comparison query")

            combined = [*rows, *rows_for_unfound_items]

            # Sort combined results:
            # 1. In-range items first (is_fallback=False)
            # 2. For In-range: sort by cost ASC (cheapest first)
            # 3. For Fallback: sort by purchase_date DESC (latest first)
            def sort_key(row):
                is_fallback = row.get('is_fallback', False)
                cost = float(row.get('item_cost', 0))
                # For fallback, we want the latest, so we use a descending date sort
                # For in-range, we want the cheapest, so we use an ascending cost sort
                if not is_fallback:
                    return (0, cost)
                else:
                    date_val = row.get('purchase_date')
                    # Use timestamp/ordinal for numerical sorting of dates
                    if hasattr(date_val, 'timestamp'):
                        numeric_date = date_val.timestamp()
                    elif hasattr(date_val, 'toordinal'):
                        numeric_date = date_val.toordinal()
                    else:
                        numeric_date = 0
                    return (1, -numeric_date)

            return sorted(combined, key=sort_key)

        except Exception as e:
            logger.error(f"Error in get_price_comparison: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    @classmethod
    def _construct_query(
            cls,
            where_clause: str,
            group_columns: str,
            rank_column: str
    ) -> str:

        query = f"""
            SELECT * FROM (
                SELECT DISTINCT ON ({group_columns}) *
                FROM analytics.mart__item_price_comparison
                WHERE {where_clause}
                ORDER BY {group_columns}, {rank_column} ASC
            ) sub
            ORDER BY purchase_date DESC
        """

        return query

    @classmethod
    def _construct_conditions(
            cls,
            filter_request: POBulkImportRequest,
            include_date_range: bool = True,
            prioritize_latest: bool = False
    ) -> tuple[str, str, str, Dict[str, Any]]:
        """
        Construct dynamic WHERE clause and parameters for the query.

        Args:
            filter_request: Filter Request for which condition needs to be constructed.

        Returns:
            Tuple containing the WHERE clause string and parameters dictionary.
        """
        conditions = []
        params = {}
        group_columns = "supplier_name"
        prefix = "latest_" if prioritize_latest else ""
        rank_column = None

        if filter_request.item_mpi_codes:
            conditions.append("item_mpi_code = ANY(:item_mpi_codes)")
            params["item_mpi_codes"] = filter_request.item_mpi_codes
            group_columns += ", item_mpi_code"
            rank_column = (
                f"{prefix}rank_by_mpi_item_code"
                if prioritize_latest
                else "rank_by_item_mpi_code"
            )

        if filter_request.item_codes:
            conditions.append("item_code = ANY(:item_codes)")
            params["item_codes"] = filter_request.item_codes
            group_columns += ", item_code"
            current_rank = f"{prefix}rank_by_item_code"
            if rank_column is None:
                rank_column = current_rank
            else:
                # Both filters: PARTITION BY matches mart__item_price_comparison combined columns
                rank_column = (
                    "latest_rank_by_item_and_mpi_code"
                    if prioritize_latest
                    else "cheapest_rank_by_item_and_mpi_code"
                )

        if filter_request.supplier_names:
            conditions.append("supplier_name = ANY(:supplier_names)")
            params["supplier_names"] = filter_request.supplier_names

        if include_date_range:
            if filter_request.from_date:
                conditions.append("purchase_date >= :from_date")
                params["from_date"] = filter_request.from_date

            if filter_request.to_date:
                conditions.append("purchase_date <= :to_date")
                params["to_date"] = filter_request.to_date

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return where_clause, group_columns, rank_column, params

    @classmethod
    def _extract_not_found_item_mpi_codes(
            cls,
            rows: Sequence[Mapping[str, Any]],
            item_mpi_codes: List[str]
    ) -> List[str]:
        """
        Normalize query output and keep unique items by item_mpi_code.

        Handles two shapes:
        - flat row mappings (existing behavior)
        - row mapping with a JSON array in the "rows" key
        """
        unique_codes: set[str] = set()

        for row in rows:
            item_mpi_code = row.get("item_mpi_code")
            if item_mpi_code:
                unique_codes.add(item_mpi_code)

        requested_codes = set(item_mpi_codes or [])
        remaining_codes = requested_codes - unique_codes
        return list(remaining_codes)

    def _get_items(
            self,
            db: Session,
            filter_request: POBulkImportRequest
    ) -> Sequence[Mapping[str, Any]]:
        where_clause, group_columns, rank_column, query_params = self._construct_conditions(
            filter_request, prioritize_latest=False
        )

        logger.info(f"Constructed WHERE clause: {where_clause} with params: {query_params}")

        query_string = self._construct_query(
            where_clause=where_clause,
            group_columns=group_columns,
            rank_column=rank_column
        )

        result = db.execute(text(query_string), query_params)
        return [{**row, "is_fallback": False} for row in result.mappings().all()]

    def _get_rows_for_unfound_items(
            self,
            db: Session,
            filter_request: POBulkImportRequest,
            item_mpi_codes: List[str]
    ) -> Sequence[Mapping[str, Any]]:
        """
        Get items without date range filter.
        """
        if len(item_mpi_codes) == 0:
            return []

        logger.info(f"Getting rows for unfound items: {item_mpi_codes}")

        where_clause, group_columns, rank_column, query_params = self._construct_conditions(
            filter_request, include_date_range=False, prioritize_latest=True
        )

        """
        Override the query params to use new item_mpi_codes received
        """
        query_params["item_mpi_codes"] = item_mpi_codes

        logger.info(f"Constructed WHERE clause: {where_clause} with params: {query_params}")

        query_string = self._construct_query(
            where_clause=where_clause,
            group_columns=group_columns,
            rank_column=rank_column
        )
        result_without_date_range = db.execute(text(query_string), query_params)
        return [{**row, "is_fallback": True} for row in result_without_date_range.mappings().all()]

    @staticmethod
    def create_draft(db: Session, draft_data: PODraftCreate, user_id: UUID) -> PurchaseOrderDrafts:
        # Calculate summary fields
        items_count = len(draft_data.items)

        # Create model instance
        # We store the entire JSON as received from FE in the 'data' column
        db_draft = PurchaseOrderDrafts(
            name=draft_data.name,
            from_date=draft_data.metadata.fromDate,
            to_date=draft_data.metadata.toDate,
            items_count=items_count,
            data=draft_data.model_dump(mode='json'),
            user_id=user_id
        )

        db.add(db_draft)
        db.commit()
        db.refresh(db_draft)
        return db_draft

    @staticmethod
    def get_drafts_summary(db: Session, page: int = 1, size: int = 20):
        offset = (page - 1) * size
        query = db.query(PurchaseOrderDrafts).order_by(desc(PurchaseOrderDrafts.saved_at))

        total = query.count()
        items = query.offset(offset).limit(size).all()

        return items, total

    @staticmethod
    def get_draft_by_id(db: Session, draft_id: UUID) -> type[PurchaseOrderDrafts] | None:
        return db.query(PurchaseOrderDrafts).filter(PurchaseOrderDrafts.id == draft_id).first()

    def delete_draft(self, db: Session, draft_id: UUID) -> bool:
        db_draft = self.get_draft_by_id(db, draft_id)
        if db_draft:
            db.delete(db_draft)
            db.commit()
            return True
        return False