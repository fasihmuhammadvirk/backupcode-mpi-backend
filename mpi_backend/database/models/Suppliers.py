from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from mpi_backend.database import Base


class Supplier(Base):
    __tablename__ = 'suppliers'

    id = Column(Integer, primary_key=True)
    supplier_name = Column(String)
    suffix = Column(String, nullable=True)  # Supplier suffix (e.g., 'B', 'W', 'F')
    is_subject_resolved = Column(
        Boolean, nullable=False, server_default=text("false"),
    )

    supplier = relationship("Invoice", back_populates="supplier_fk")
    mpi_mapping = relationship("ItemsMapping", back_populates="mpi_mapping_fk")
    unmapped_items = relationship("UnmappedItems", back_populates="unmapped_items_fk")
    email_patterns = relationship(
        "SupplierEmailPattern",
        back_populates="supplier",
        cascade="all, delete-orphan",
    )
