import logging
from typing import Dict, Any, Tuple, Sequence

from sqlalchemy import text, RowMapping
from sqlalchemy.orm import Session

from mpi_backend.database.schemas.SupplierComparison import (
    SupplierComparisonRequest
)

logger = logging.getLogger(__name__)

class SupplierComparisonDAO:
    """Data Access Object for Supplier Price Comparison operations."""

    def get_comparison_summary(self, db: Session, request: SupplierComparisonRequest) -> RowMapping | None:
        general_where, item_scope_where, params = self._construct_where_clause(request)

        summary_query = f"""
            WITH target_items AS (
                SELECT DISTINCT item_mpi_code 
                FROM analytics.mart__item_price_comparison
                WHERE {general_where} AND {item_scope_where}
            ),
            base AS (
                SELECT 
                    *, 
                    MIN(item_cost) OVER (PARTITION BY item_mpi_code) as item_best,
                    MAX(item_cost) OVER (PARTITION BY item_mpi_code) as item_worst
                FROM analytics.mart__item_price_comparison
                WHERE {general_where} AND item_cost > 0
                AND item_mpi_code IN (SELECT item_mpi_code FROM target_items)
            ),
            vendor_best AS (
                SELECT DISTINCT ON (item_mpi_code, supplier_name)
                    supplier_name,
                    item_mpi_code,
                    item_cost as min_price,
                    item_best as market_best,
                    item_worst as market_worst,
                    (item_cost - item_best) * item_quantity as item_loss,
                    (item_worst - item_cost) * item_quantity as item_saved
                FROM base
                ORDER BY item_mpi_code, supplier_name, item_cost ASC
            ),
            item_winners AS (
                SELECT 
                    *,
                    MAX(item_loss) OVER (PARTITION BY item_mpi_code) as max_loss_on_item
                FROM vendor_best
            ),
            supplier_metrics AS (
                SELECT 
                    supplier_name,
                    SUM(item_loss) as total_loss,
                    SUM(item_saved) as total_saved,
                    COUNT(DISTINCT item_mpi_code) as total_items,
                    -- High impact: items where THIS supplier is the biggest financial drain
                    array_agg(item_mpi_code) FILTER (WHERE item_loss = max_loss_on_item AND item_loss > 0) as high_price_items,
                    -- Best price: items where this supplier provided the market best price at least once
                    array_agg(item_mpi_code) FILTER (WHERE min_price = market_best) as best_price_items
                FROM item_winners
                GROUP BY supplier_name
            )
            SELECT 
                (SELECT SUM(item_loss) FROM vendor_best) as total_missed_savings,
                (SELECT COUNT(DISTINCT item_mpi_code) FROM base) as item_count,

                -- Highest Priced Supplier
                s1.supplier_name as highest_priced_supplier,
                s1.total_loss as highest_excess,
                (CAST(COALESCE(cardinality(s1.high_price_items), 0) AS FLOAT) / NULLIF(s1.total_items, 0) * 100) as highest_loss_rate,
                s1.high_price_items as highest_impact_item_codes,

                -- Top Value Supplier
                s2.supplier_name as top_value_supplier,
                s2.total_saved as top_saved,
                (CAST(COALESCE(cardinality(s2.best_price_items), 0) AS FLOAT) / NULLIF(s2.total_items, 0) * 100) as top_win_rate,
                s2.best_price_items as top_value_item_codes

            FROM (SELECT 1) dummy
            LEFT JOIN supplier_metrics s1 ON s1.supplier_name = (
                SELECT supplier_name FROM supplier_metrics WHERE total_loss > 0 ORDER BY total_loss DESC LIMIT 1
            )
            LEFT JOIN supplier_metrics s2 ON s2.supplier_name = (
                SELECT supplier_name FROM supplier_metrics 
                ORDER BY CAST(COALESCE(cardinality(best_price_items), 0) AS FLOAT)/NULLIF(total_items, 0) DESC, total_saved DESC 
                LIMIT 1
            )
        """

        try:
            return db.execute(text(summary_query), params).mappings().first()
        except Exception as e:
            logger.error(f"Error in get_comparison_summary: {e}")
            raise

    def get_comparison_table(
            self,
            db: Session,
            request: SupplierComparisonRequest,
            limit: int = None,
            offset: int = None
    ) -> Tuple[Sequence[RowMapping], int]:
        try:
            general_where, item_scope_where, params = self._construct_where_clause(request)

            count_query = f"""
                SELECT COUNT(DISTINCT item_mpi_code)
                FROM analytics.mart__item_price_comparison
                WHERE {general_where} AND {item_scope_where} AND item_cost > 0
            """
            total_count = db.execute(text(count_query), params).scalar() or 0

            limit_clause = ""
            if limit is not None:
                limit_clause = f"LIMIT :limit OFFSET :offset"
                params.update({"limit": limit, "offset": offset if offset is not None else 0})

            table_query = f"""
                WITH target_items AS (
                    -- Items sold by target supplier (within filters and excluding credit memos)
                    SELECT DISTINCT item_mpi_code
                    FROM analytics.mart__item_price_comparison
                    WHERE {general_where} AND {item_scope_where} AND item_cost > 0
                ),
                base AS (
                    -- Get ALL vendor data for just those items
                    SELECT *, MIN(item_cost) OVER (PARTITION BY item_mpi_code) as item_best
                    FROM analytics.mart__item_price_comparison
                    WHERE {general_where} AND item_cost > 0
                    AND item_mpi_code IN (SELECT item_mpi_code FROM target_items)
                ),
                vendor_best AS (
                    -- Ensure only best price per vendor is considered for each item
                    SELECT DISTINCT ON (item_mpi_code, supplier_name) *
                    FROM base
                    ORDER BY item_mpi_code, supplier_name, item_cost ASC
                ),
                page_items AS (
                    SELECT
                        item_mpi_code,
                        MAX(item_description) as item_description,
                        item_best as best_price,
                        SUM((item_cost - item_best) * item_quantity) as potential_savings,
                        MAX((item_cost - item_best) * item_quantity) as max_loss_amt,
                        COUNT(*) as quotes_count
                    FROM vendor_best
                    GROUP BY item_mpi_code, item_best
                    ORDER BY {request.sort_column} {request.sort_dir} NULLS LAST
                    {limit_clause}
                )
                SELECT
                    p.item_mpi_code, p.item_description, p.best_price, p.potential_savings, p.quotes_count,
                    jsonb_agg(jsonb_build_object(
                        'supplier_name', v.supplier_name, 'purchase_date', v.purchase_date, 'ref_no', v.ref_no,
                        'filename', v.filename, 'quantity', v.item_quantity, 'unit_price', v.item_cost,
                        'variance_amount', (v.item_cost - p.best_price),
                        'variance_percentage', CASE WHEN p.best_price > 0 THEN (v.item_cost - p.best_price)/p.best_price*100 ELSE 0 END,
                        'is_best_value', (v.item_cost = p.best_price),
                        'is_worst_quote', ((v.item_cost - p.best_price) * v.item_quantity = p.max_loss_amt AND p.max_loss_amt > 0),
                        'is_price_rerated', v.is_price_rerated,
                        'original_current_qty', v.original_current_qty, 
                        'original_current_price', v.original_current_price
                    ) ORDER BY v.item_cost ASC) as vendor_details

                FROM page_items p
                JOIN vendor_best v ON p.item_mpi_code = v.item_mpi_code
                GROUP BY p.item_mpi_code, p.item_description, p.best_price, p.potential_savings, p.quotes_count
                ORDER BY p.{request.sort_column} {request.sort_dir} NULLS LAST
            """

            return db.execute(text(table_query), params).mappings().all(), total_count
        except Exception as e:
            logger.error(f"Error in get_comparison_table: {e}")
            raise


    @staticmethod
    def _construct_where_clause(request: SupplierComparisonRequest) -> Tuple[str, str, Dict[str, Any]]:
        """
        Returns (general_where, item_scope_where, params).
        general_where: used for detail aggregation (dates, search, cost > 0).
        item_scope_where: used specifically to restrict items based on the supplier_name input.
        """
        conditions = [
            "item_mpi_code IS NOT NULL",
            "supplier_name != 'Unknown'"
        ]
        params = {}
        if request.from_date:
            conditions.append("purchase_date >= :from_date")
            params["from_date"] = request.from_date

        if request.to_date:
            conditions.append("purchase_date <= :to_date")
            params["to_date"] = request.to_date

        if request.item_mpi_codes:
            conditions.append("item_mpi_code = ANY(:item_mpi_codes)")
            params["item_mpi_codes"] = request.item_mpi_codes

        if request.search:
            search_terms = [s.strip() for s in request.search.split(',') if s.strip()]
            if search_terms:
                search_conditions = []
                for i, term in enumerate(search_terms):
                    search_conditions.append(f"(item_mpi_code ILIKE :search_{i} OR ref_no ILIKE :search_{i})")
                    params[f"search_{i}"] = f"%{term}%"
                conditions.append(f"({' OR '.join(search_conditions)})")

        general_where = " AND ".join(conditions)

        # Supplier scope filter
        item_scope_where = "1=1"
        if request.supplier_name:
            item_scope_where = "supplier_name = :supplier_name"
            params["supplier_name"] = request.supplier_name
        return general_where, item_scope_where, params
