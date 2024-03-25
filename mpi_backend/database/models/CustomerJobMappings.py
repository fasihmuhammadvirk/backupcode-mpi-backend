import uuid
from sqlalchemy import Column, UUID, String, Date, Integer, ForeignKey
from mpi_backend.database import Base
from sqlalchemy.orm import relationship


class CustomerJobMapping(Base):
    __tablename__ = 'customer_job_mappings'

    id = Column(Integer, primary_key=True)
    customer_job = Column(String)
    updated_customer_job = Column(String)
