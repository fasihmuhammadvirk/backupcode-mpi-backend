"""
SQLAlchemy ORM model for analytics.mart__address_sheet_aggregates table.

This table is a dbt-managed materialized table optimized for analysis page queries with:
- Pre-computed aggregations per address + sheet_name combination
- Per-address totals across all sheets
- Optimized indexes for fast filtering
"""

from sqlalchemy import Column, String, Float
from mpi_backend.database import Base


class AddressSheetAggregate(Base):
    """
    ORM model for the analytics.mart__address_sheet_aggregates table.

    This is a dbt-managed mart table that provides optimized access to pre-aggregated
    invoice data grouped by customer_job (address) and sheet_name categories.

    Note: This table is managed by dbt - do not modify via ORM.
    """
    __tablename__ = "mart__address_sheet_aggregates"
    __table_args__ = (
        {"schema": "analytics"}
    )

    # Composite primary key (customer_job + sheet_name)
    customer_job = Column(String, primary_key=True)
    sheet_name = Column(String, primary_key=True)

    # Aggregated amounts
    total_amount = Column(Float, nullable=False)
    address_total = Column(Float, nullable=False)
