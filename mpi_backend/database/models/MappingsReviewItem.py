import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from mpi_backend.database import Base

class MappingsReviewItem(Base):
    """Model for storing isolated items for review from mappings page"""
    __tablename__ = 'mappings_review_items'
    __table_args__ = {'schema': 'public'}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor = Column(String, nullable=False)
    item_id = Column(String, nullable=False)  # The original item ID from the supplier
    reason = Column(String, nullable=False)
    map_to_item = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)