import uuid
from sqlalchemy import Column, UUID, String, Date, Integer, ForeignKey
from mpi_backend.database import Base
from sqlalchemy.orm import relationship


class Invoice(Base):
    __tablename__ = 'invoices'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date)
    filename = Column(String)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'))
    status = Column(String)
    storage_path = Column(String)
    is_exported = Column(String, default="Pending")
    # TODO: Add company_id for multi-tenancy
    # company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)

    items = relationship("InvoiceItem", back_populates="invoice")
    supplier_fk = relationship("Supplier", back_populates="supplier")
