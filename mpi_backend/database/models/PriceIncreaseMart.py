"""
SQLAlchemy ORM model for analytics.mart__price_increases table.

This table is a dbt-managed materialized table that tracks price changes over time
for each item-vendor pair with pre-computed percentage increases.
"""

from sqlalchemy import Column, String, Date, Integer, Float, Boolean
from mpi_backend.database import Base


class PriceIncreaseMart(Base):
    """
    ORM model for the analytics.mart__price_increases table.

    This is a dbt-managed mart table that provides price increase analysis with:
    - Historical price comparison for invoice items
    - Supplier-specific price tracking
    - Pre-computed percentage increases

    Relationship:
    - One-to-one with mart__invoice_items via invoice_items_id

    Note: This table is managed by dbt - do not modify via ORM.
    """
    __tablename__ = "mart__price_increases"
    __table_args__ = {"schema": "analytics"}

    # Primary key (same as invoice_items_id in mart__invoice_items)
    invoice_items_id = Column(Integer, primary_key=True, index=True)

    # Item and vendor identifiers
    item = Column(String, nullable=False, index=True)
    vendor = Column(String, nullable=False, index=True)

    # Current purchase data
    purchase_date = Column(Date, nullable=False, index=True)
    current_price = Column(Float, nullable=False)
    current_qty = Column(Integer)

    # Previous purchase data
    previous_price = Column(Float)
    previous_date = Column(Date)
    previous_qty = Column(Integer)

    # Calculated price changes
    percentage_increase = Column(Float)  # Rounded to 1 decimal place
    price_change = Column(Float)  # Absolute dollar change

    # Metadata
    has_previous_price = Column(Boolean, nullable=False)
    percentage_increase_formatted = Column(String, nullable=False)  # e.g. "15.5%" or "N/A"
