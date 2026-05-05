from enum import Enum

from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Text, UUID
from sqlalchemy.sql import func
from mpi_backend.database import Base


class DbtRunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


class DbtRunType(str, Enum):
    REGULAR = "regular"
    FULL_REFRESH = "full-refresh"


class DbtRunLog(Base):
    __tablename__ = 'dbt_run_log'

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, default=DbtRunStatus.RUNNING.value)
    run_type = Column(String, default=DbtRunType.REGULAR.value)
    error_message = Column(Text, nullable=True)
    execution_time = Column(Float, nullable=True)
    triggered_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)

    def __repr__(self):
        return f"<DbtRunLog(id={self.id}, status='{self.status}', run_type='{self.run_type}', started_at='{self.started_at}')>"
