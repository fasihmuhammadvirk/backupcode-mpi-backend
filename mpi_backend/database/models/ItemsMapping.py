import uuid
from sqlalchemy import Column, UUID, String, Date, Integer, ForeignKey
from mpi_backend.database import Base
from sqlalchemy.orm import relationship


class ItemsMapping(Base):
    __tablename__ = 'supplier_item_mappings'

    id = Column(Integer, primary_key=True)

    google_sheet_name = Column(String)
    mpi_code = Column(String)
    description = Column(String)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'))

    mpi_mapping_fk = relationship("Supplier", back_populates="mpi_mapping")
