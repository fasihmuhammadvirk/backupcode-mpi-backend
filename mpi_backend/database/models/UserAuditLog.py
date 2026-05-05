from sqlalchemy import Column, Integer, String, JSON, DateTime, UUID, ForeignKey
from sqlalchemy.sql import func
from mpi_backend.database import Base


class UserAuditLog(Base):
    __tablename__ = 'user_audit_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    action = Column(String, nullable=False)  # created, updated, deactivated, role_changed
    changed_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
