"""
SQLAlchemy ORM model for analytics.mart__invoice_items table.

This table is a dbt-managed materialized table optimized for fast queries with:
- Pre-trimmed original columns
- Pre-computed normalized columns for fuzzy searching
- Optimized indexes
"""

from sqlalchemy import Column, String, Date, DateTime, Integer, Float, UUID, Boolean
from mpi_backend.database import Base


class InvoiceItemMart(Base):
    """
    ORM model for the analytics.mart__invoice_items table.

    This is a dbt-managed mart table that provides optimized access to invoice items
    with pre-computed normalized columns for fast searching and filtering.

    Note: This table is managed by dbt - do not modify via ORM.
    """
    __tablename__ = "mart__invoice_items"
    __table_args__ = {"schema": "analytics"}

    # Primary key
    # Note: Column is named 'invoice_items_id' in the database
    id = Column("invoice_items_id", Integer, primary_key=True, index=True)

    # Foreign keys
    invoice_id = Column(UUID)

    # Original columns (pre-trimmed by dbt)
    item = Column(String)
    description = Column(String)
    mpi_item = Column(String)
    mpi_description = Column(String)
    qty = Column(Float)
    cost = Column(Float)
    amount = Column(Float)
    rerated_cost = Column(Float)
    rerated_qty = Column(Float)
    is_price_rerated = Column(Boolean)
    ref_no = Column(String)
    vendor = Column(String)
    customer_job = Column(String)  # Maps to normalized_customer_job in dbt
    street_number = Column(String)
    street_name = Column(String)
    city = Column(String)
    state = Column(String)
    zip_code = Column(String)
    address_confidence = Column(String)
    buyer = Column(String)
    class_ = Column(String)
    account = Column(String)
    po_number = Column(String)
    sheet_name = Column(String)
    date = Column(Date)
    assigned_account = Column(String)

    # Additional fields for compatibility with invoice_items table
    filename = Column(String)
    bill = Column(String)

    # DEPRECATED: Use QuickBooksItems table for export tracking instead
    export_status = Column(String, doc="DEPRECATED: Use QuickBooksItems table instead")
    memo = Column(String)
    date_added = Column(Date)

    # Normalized columns for fuzzy search (pre-computed REGEXP_REPLACE)
    # Convention: all normalized columns use {column}_normalized naming
    item_normalized = Column(String)
    mpi_item_normalized = Column(String)
    description_normalized = Column(String)
    mpi_description_normalized = Column(String)
    vendor_search_normalized = Column(String)
    buyer_normalized = Column(String)
    sheet_name_normalized = Column(String)
    customer_job_normalized = Column(String)
    ref_no_normalized = Column(String)

    line_order = Column(Integer)  # Line ordering for display (Tax records appear last)

    invoice_voided_at = Column(DateTime(timezone=True), nullable=True)
