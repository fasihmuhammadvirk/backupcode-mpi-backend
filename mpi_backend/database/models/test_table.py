import uuid

from sqlalchemy import Column, UUID, String

from mpi_backend.database import Base


class TestTable(Base):
    __tablename__ = 'test_table'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String)
    age = Column