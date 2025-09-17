from sqlalchemy import Column, Integer, String, Date, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from mpi_backend.database import Base


class PlumbingSupplier(Base):
    """Simple model for plumbing suppliers"""
    __tablename__ = "plumbing_suppliers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    is_active = Column(String, default="Active")
    
    statements = relationship("PlumbingStatement", back_populates="supplier")


class PlumbingStatement(Base):
    """Simple model for plumbing statements"""
    __tablename__ = "plumbing_statements"
    
    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("plumbing_suppliers.id"))
    statement_date = Column(Date)
    account_number = Column(String(50))
    total_amount = Column(Numeric(12, 2), default=0)
    total_invoices = Column(Integer, default=0)
    pdf_filename = Column(String(255))
    
    supplier = relationship("PlumbingSupplier", back_populates="statements")
    invoices = relationship("PlumbingInvoice", back_populates="statement")


class PlumbingInvoice(Base):
    """Simple model for individual invoices within statements"""
    __tablename__ = "plumbing_invoices"
    
    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("plumbing_statements.id"))
    invoice_number = Column(String(50))
    invoice_date = Column(Date)
    customer_po = Column(String(100))
    original_amount = Column(Numeric(10, 2))
    payment_date = Column(Date)
    amount_paid = Column(Numeric(10, 2))
    balance = Column(Numeric(10, 2))
    
    statement = relationship("PlumbingStatement", back_populates="invoices") 