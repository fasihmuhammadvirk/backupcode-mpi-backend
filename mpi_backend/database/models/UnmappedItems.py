import uuid
from sqlalchemy import Column, UUID, String, Date, Integer, ForeignKey
from mpi_backend.database import Base
from sqlalchemy.orm import relationship


class UnmappedItems(Base):
    __tablename__ = 'unmapped_items'

    id = Column(Integer, primary_key=True)

    google_sheet_name = Column(String)
    mpi_code = Column(String)
    description = Column(String)
    supplier_item_ids = Column(String)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'))

    unmapped_items_fk = relationship("Supplier", back_populates="unmapped_items")
