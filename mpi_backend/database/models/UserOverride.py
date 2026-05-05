from sqlalchemy import Boolean, Column, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func, text
from mpi_backend.database import Base


class UserOverride(Base):
    __tablename__ = "user_overrides"

    record_id = Column(Text, primary_key=True)
    overrides = Column(JSONB, nullable=False)
    overridden_by = Column(UUID(as_uuid=True), nullable=False)
    overridden_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # When TRUE the mart row is hidden from all views and aggregations.
    is_row_deleted = Column(Boolean, nullable=False, server_default=text("false"))
