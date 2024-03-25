import uuid
from sqlalchemy import Column, UUID, String, Date, Integer, ForeignKey
from mpi_backend.database import Base
from sqlalchemy.orm import relationship


class TempItemMapping(Base):
    __tablename__ = 'temporary_item_mappings'

    id = Column(Integer, primary_key=True)
    original_item_number = Column(String)
    description = Column(String)
    temporary_item_number = Column(String)
