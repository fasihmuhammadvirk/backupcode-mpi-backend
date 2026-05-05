"""
Data Access Object for analytics.mart__address_sheet_aggregates table.

Provides stateless functions for querying the dbt-managed mart table
with pre-computed aggregations for the analysis page.
"""

import logging
import time
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from mpi_backend.database.models.AddressSheetAggregate import AddressSheetAggregate
from mpi_backend.database.dao.dao_models import DaoAggregateResult
from mpi_backend.database.dao.dao_utils import check_table_exists


logger = logging.getLogger(__name__)


def check_mart_table_exists(db: Session) -> bool:
    """
    Check if the analytics.mart__address_sheet_aggregates table exists.

    Args:
        db: SQLAlchemy database session

    Returns:
        True if table exists, False otherwise
    """
    return check_table_exists(db, "analytics", "mart__address_sheet_aggregates")


def get_aggregates_by_address_and_sheet(
    db: Session,
    address: Optional[str] = None
) -> Optional[DaoAggregateResult]:
    """
    Query analytics.mart__address_sheet_aggregates for pre-computed aggregations.

    This function retrieves pre-aggregated data from the dbt mart table and computes:
    - Global category averages (average per address for each sheet_name)
    - Grand total across all addresses
    - If address provided: detailed breakdown for that specific address

    Args:
        db: SQLAlchemy database session
        address: Optional customer_job address to filter by

    Returns:
        DaoAggregateResult if successful, None to fall back to invoice_items

    Raises:
        None - returns None on any error to allow fallback
    """
    logger.info(f"DAO: Attempting optimized mart table for address: {address}")

    try:
        # Check if mart table exists
        if not check_mart_table_exists(db):
            logger.info("mart__address_sheet_aggregates not found, using invoice_items fallback")
            return None

        # TODO: Make a decorator to time functions instead
        start_time = time.time()

        # Step 1: Calculate global category averages, category totals, and grand total
        # This query computes:
        # - For each sheet_name: the average per address (category_average)
        # - For each sheet_name: the total across all addresses (category_sum)
        # - The grand total across all addresses and all sheet_names
        global_query = text("""
            SELECT
                sheet_name,
                SUM(total_amount) / NULLIF(COUNT(DISTINCT customer_job), 0) as category_average,
                SUM(total_amount) as category_total,
                SUM(SUM(total_amount)) OVER () as grand_total
            FROM analytics.mart__address_sheet_aggregates
            GROUP BY sheet_name
            ORDER BY sheet_name
        """)

        global_results = db.execute(global_query).fetchall()

        # Build category_averages, category_totals dicts and extract grand_total
        category_averages = {}
        category_totals = {}
        grand_total = 0.0

        for row in global_results:
            sheet_name = row[0]
            category_avg = float(row[1]) if row[1] is not None else 0.0
            category_total = float(row[2]) if row[2] is not None else 0.0
            category_averages[sheet_name] = category_avg
            category_totals[sheet_name] = category_total
            if row[3] is not None:
                grand_total = float(row[3])

        # If no address filter, return only global stats
        if not address:
            execution_time = time.time() - start_time
            logger.info(
                f"DAO OPTIMIZED MART QUERY (global): "
                f"{execution_time:.3f}s, {len(category_averages)} categories, "
                f"grand_total: {grand_total:.2f}"
            )

            return DaoAggregateResult(
                data=None,  # No address-specific data
                category_averages=category_averages,
                category_totals=category_totals,
                grand_total=grand_total,
                source=AddressSheetAggregate.__tablename__
            )

        # Step 2: If address provided, get address-specific data
        address_query = text("""
            SELECT
                customer_job,
                sheet_name,
                total_amount,
                address_total
            FROM analytics.mart__address_sheet_aggregates
            WHERE customer_job = :address
            ORDER BY sheet_name
        """)

        address_results = db.execute(address_query, {"address": address}).fetchall()

        # Build nested data structure for the specific address
        data = {}

        if address_results:
            addr = address_results[0][0]  # customer_job from first row

            # Initialize address structure
            data[addr] = {
                "address": addr,
                "categories": {},
                "address_total": 0.0
            }

            # Build categories dict
            for row in address_results:
                sheet_name = row[1]
                total_amount = float(row[2]) if row[2] is not None else 0.0
                address_total = float(row[3]) if row[3] is not None else 0.0

                # Get global average for this sheet_name
                category_avg = category_averages.get(sheet_name, 0.0)

                # Calculate differences from global average
                difference = total_amount - category_avg
                percentage_diff = (difference / category_avg * 100) if category_avg != 0 else 0.0

                # Store category data (formatting should be done in controller)
                data[addr]["categories"][sheet_name] = {
                    "sheet_name": sheet_name,
                    "total_amount": total_amount,
                    "category_average": category_avg,
                    "difference_from_average": difference,
                    "percentage_difference": round(percentage_diff, 2)
                }

                # Store address_total (same for all rows)
                data[addr]["address_total"] = address_total

        execution_time = time.time() - start_time
        # Use address_results[0][0] if available, otherwise address param
        addr_key = address_results[0][0] if address_results else address
        logger.info(
            f"DAO OPTIMIZED MART QUERY (address='{address}'): "
            f"{execution_time:.3f}s, {len(data.get(addr_key, {}).get('categories', {}))} categories"
        )

        return DaoAggregateResult(
            data=data if data else None,
            category_averages=category_averages,
            category_totals=category_totals,
            grand_total=grand_total,
            source=AddressSheetAggregate.__tablename__
        )

    except Exception as e:
        logger.exception("Error using optimized mart table, falling back to invoice_items.")
        return None
