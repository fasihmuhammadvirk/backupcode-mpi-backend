"""
SQLAlchemy ORM model for analytics.mart__quickbooks_preview table.

This table is dbt-managed — do NOT modify via ORM.

Refactored Structure:
One row per invoice. Contains pre-computed arrays of QuickBooksPreviewItem 
objects for both 'all' and 'unprocessed' filters.
"""

from sqlalchemy import Column, String, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from mpi_backend.database import Base


class QuickBooksPreviewMart(Base):
    """
    ORM model for analytics.mart__quickbooks_preview (read-only, dbt-managed).

    Each row represents one invoice.
    """

    __tablename__ = "mart__quickbooks_preview"
    __table_args__ = {"schema": "analytics"}

    id = Column(UUID, primary_key=True)

    # Invoice identity (header fields)
    invoice_id = Column(UUID, nullable=False, index=True)
    ref_no = Column(String)
    vendor = Column(String)
    date = Column(Date, nullable=False, index=True)
    customer_job = Column(String)
    date_added = Column(Date)
    filename = Column(String)

    # JSONB columns containing lists of QuickBooksPreviewItem dicts
    # These match the QuickBooksPreviewItem pydantic model structure
    all_data_json = Column(JSONB, nullable=False)
    unprocessed_data_json = Column(JSONB, nullable=False)

    # Metadata
    computed_at = Column(DateTime, nullable=False)
