import uuid
from sqlalchemy import Column, UUID, String, Date, Integer, ForeignKey, DateTime
from mpi_backend.database import Base
from sqlalchemy.orm import relationship
from datetime import datetime


class TempItemMapping(Base):
    __tablename__ = 'temporary_item_mappings'

    id = Column(Integer, primary_key=True)
    original_item = Column(String)
    original_description = Column(String)
    sheet_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
