import uuid
from sqlalchemy import Column, Integer, String, Date
from mpi_backend.database import Base
from sqlalchemy.orm import relationship


class Supplier(Base):
    __tablename__ = 'suppliers'

    id = Column(Integer, primary_key=True)
    supplier_name = Column(String)

    supplier = relationship("Invoice", back_populates="supplier_fk")
