import logging
from typing import List, Dict, Any, Tuple
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import text
from mpi_backend.database.models import MappingsReviewItem

logger = logging.getLogger(__name__)

class MappingsReviewDAO:
    """Data Access Object for Mappings Review items."""

    @staticmethod
    def bulk_create_review_items(db: Session, vendor: str, item_id: str, reason: str, map_to_item: str, user_id: str):
        """
        Create mapping review item.
        """
        try:
            db.add(
                MappingsReviewItem(
                    vendor=vendor,
                    item_id=item_id,
                    reason=reason,
                    map_to_item=map_to_item,
                    user_id=user_id
                ))
            db.commit()

        except Exception as e:
            db.rollback()
            logger.error(f"DAO Error in bulk_create_review_items: {e}")
            raise

    @staticmethod
    def get_isolated_items(
        db: Session,
        page: int = 1, 
        size: int = 10,
        status: str = "all"
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Retrieve isolated review items joined with analytics mart for current metadata.
        
        Note: joins with analytics.mart__invoice_items_map to get latest mapping_type, 
        description, and amounts for each item, vendor combo.
        """
        offset = (page - 1) * size
        
        # CTE provided by user for latest item info
        # Using a subquery/CTE to join with isolated items
        status_filter = ""
        if status != "all":
            status_filter = "WHERE mri.status = :status"

        query = f"""
            WITH unique_items AS (
                SELECT
                    vendor AS supplier,
                    mapping_type,
                    item AS original_item_id,
                    MIN(description) AS original_description,
                    MIN(sheet_name) AS sheet_name,
                    MIN(cost) AS cost,
                    MIN(qty) AS quantity,
                    (MIN(cost) * MIN(qty)) AS amount,
                    MAX(date) AS date
                FROM analytics.mart__invoice_items_map
                GROUP BY vendor, item, mapping_type
            )
            SELECT 
                mri.id,
                mri.vendor,
                mri.item_id,
                mri.reason,
                mri.map_to_item,
                mri.status,
                mri.created_at,
                ui.mapping_type,
                ui.original_description,
                ui.amount
            FROM public.mappings_review_items mri
            LEFT JOIN unique_items ui ON mri.vendor = ui.supplier AND mri.item_id = ui.original_item_id
            {status_filter}
            ORDER BY mri.created_at DESC
            {"LIMIT :size OFFSET :offset" if size > 0 else ""}
        """

        count_query = f"SELECT COUNT(*) FROM public.mappings_review_items mri {status_filter}"

        try:
            # Get total count first
            params = {"size": size, "offset": offset, "status": status}
            total_count = db.execute(text(count_query), params).scalar() or 0

            # Get items
            result = db.execute(text(query), params)
            rows = result.fetchall()
            
            items = []
            if rows:
                columns = result.keys()
                for row in rows:
                    items.append(dict(zip(columns, row)))
                    
            return items, total_count
            
        except Exception as e:
            logger.error(f"DAO Error in get_isolated_items: {e}")
            raise

    @staticmethod
    def get_isolated_total_amount(db: Session) -> float:
        """
        Calculate aggregate sum of total amount for all isolated items.
        
        Joins with analytics.mart__invoice_items_map to get latest amounts.
        """
        query = """
            WITH unique_items AS (
                SELECT
                    vendor AS supplier,
                    item AS original_item_id,
                    (MIN(cost) * MIN(qty)) AS amount
                FROM analytics.mart__invoice_items_map
                GROUP BY vendor, item, mapping_type
            )
            SELECT SUM(ui.amount) as total_amount
            FROM public.mappings_review_items mri
            LEFT JOIN unique_items ui ON mri.vendor = ui.supplier AND mri.item_id = ui.original_item_id
        """
        try:
            result = db.execute(text(query)).scalar() or 0.0
            return float(result)
        except Exception as e:
            logger.error(f"DAO Error in get_isolated_total_amount: {e}")
            raise

    @staticmethod
    def remove_isolated_item(db: Session, item_id: str):
        """
        Remove an item from mappings_review_items by ID.
        Raises ValueError if the item has status 'done'.
        """
        try:
            row = db.execute(
                text("SELECT status FROM public.mappings_review_items WHERE id = :id FOR UPDATE"),
                {"id": item_id}
            ).fetchone()

            if row is None:
                raise ValueError(f"Item with ID {item_id} not found.")

            if row.status.lower() == "done":
                raise ValueError("Cannot delete an item with status 'done'.")

            db.execute(
                text("DELETE FROM public.mappings_review_items WHERE id = :id"),
                {"id": item_id}
            )
            db.commit()
        except ValueError:
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"DAO Error in remove_isolated_item: {e}")
            raise

    @staticmethod
    def update_item_status(db: Session, item_id: str, status: str):
        """
        Update the status of a review item.
        """
        try:
            stmt = text("UPDATE public.mappings_review_items SET status = :status WHERE id = :id")
            db.execute(stmt, {"id": item_id, "status": status})
            db.commit()
            return
        except Exception as e:
            db.rollback()
            logger.error(f"DAO Error in update_item_status: {e}")
            raise
