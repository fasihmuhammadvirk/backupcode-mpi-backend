from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from mpi_backend.database import Base


class Company(Base):
    __tablename__ = 'companies'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
