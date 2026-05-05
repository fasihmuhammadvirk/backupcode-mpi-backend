import uuid
from sqlalchemy.sql import func
from sqlalchemy import Column, UUID, String, Date, Integer, ForeignKey, Boolean, DateTime
from sqlalchemy.dialects.postgresql import CITEXT
from mpi_backend.database import Base
from sqlalchemy.orm import relationship


class User(Base):
    __tablename__ = 'users'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(CITEXT, unique=True, index=True)
    password= Column(String)
    email = Column(String, unique=True, nullable=True)
    role = Column(String, default='standard', nullable=False)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    project_estimations = relationship("ProjectEstimation", back_populates="user")

