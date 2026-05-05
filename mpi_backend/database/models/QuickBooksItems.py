"""
SQLAlchemy ORM model for public.quickbooks_items table.

This table tracks which invoice items have been exported to QuickBooks.
It serves as an export history/audit log.
"""

from sqlalchemy import Column, Integer, BigInteger, String, Date, DateTime, UUID
from sqlalchemy.sql import func
from mpi_backend.database import Base


class QuickBooksItems(Base):
    """
    ORM model for the public.quickbooks_items table.
    
    Tracks invoice items that have been exported to QuickBooks.
    This table serves as an export history and allows us to determine
    which items are unprocessed without modifying the source data.
    """
    __tablename__ = "quickbooks_items"
    __table_args__ = {"schema": "public"}

    # Primary key - auto-incrementing ID
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    # Reference to the invoice item in InvoiceItemMart
    invoice_items_id = Column(BigInteger, nullable=False, index=True)
    
    # Reference to the invoice
    invoice_id = Column(UUID, nullable=False, index=True)
    ref_no = Column(String)
    vendor = Column(String)
    date = Column(Date)
    
    # Timestamp when the item was exported
    exported_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
