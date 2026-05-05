"""
SQLAlchemy ORM model for analytics.mart__invoice_items_map table.
"""

from sqlalchemy import Column, String, Date, Integer, Float, UUID, Boolean, DateTime
from mpi_backend.database import Base


class InvoiceItemsMapMart(Base):
    """
    ORM model for the analytics.mart__invoice_items_map table.

    This is a dbt-managed mart table for invoice item mappings.
    Note: This table is managed by dbt - do not modify via ORM.
    """
    __tablename__ = "mart__invoice_items_map"
    __table_args__ = {"schema": "analytics"}

    # Primary key
    id = Column("id", Integer, primary_key=True, index=True)

    # File and Invoice Tracking
    filename = Column(String)
    invoice_id = Column(UUID)
    ref_no = Column(String)
    po_number = Column(String)

    # Original Item Data
    item = Column(String)
    description = Column(String)

    # Resolved Mapping Values
    sheet_name = Column(String)
    mpi_item = Column(String)
    mpi_description = Column(String)

    # Supplier Info
    supplier = Column(String)
    supplier_id = Column(Integer)
    vendor = Column(String)

    # Financial Data
    qty = Column(Float)
    cost = Column(Float)
    amount = Column(Float)

    # Job and Customer Tracking
    customer_job = Column(String)
    buyer = Column(String)

    # Date Fields
    date = Column(Date)
    date_added = Column(Date)

    # Account Assignment
    account = Column(String)

    # Status
    is_active = Column(Boolean)

    # Audit Columns
    mapping_type = Column(String)  # 'permanent', 'temporary', 'no_match'
    mapping_source = Column(String)
    mapped_at = Column(DateTime)

    # Original Values (for Reference/Audit)
    original_mpi_item = Column(String)
    original_mpi_description = Column(String)
    original_sheet_name = Column(String)
