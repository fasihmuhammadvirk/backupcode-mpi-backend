"""
SQLAlchemy ORM model for public.invoice_voided table.

Only voided invoices have rows here. Insert on void, delete on restore.
Key: (ref_no, date, vendor) — matches how invoices are identified in the
extraction / mart pipeline.
"""

from sqlalchemy import Column, String, Date, DateTime
from sqlalchemy.sql import func
from mpi_backend.database import Base


class InvoiceVoid(Base):
    __tablename__ = "invoice_voided"

    ref_no = Column(String, primary_key=True)
    date = Column(Date, primary_key=True)
    vendor = Column(String, primary_key=True)
    invoice_voided_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    invoice_voided_by = Column(String, nullable=True)
    void_reason = Column(String, nullable=True)
