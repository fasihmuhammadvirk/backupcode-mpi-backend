import uuid
from sqlalchemy import Column, String, Date, Integer, ForeignKey
from mpi_backend.database import Base


class ItemClassification(Base):
    __tablename__ = 'item_classification'
    id = Column(Integer, primary_key=True)
    item = Column(String)
    category = Column(String)
