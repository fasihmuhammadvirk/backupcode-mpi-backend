import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, Index, ForeignKey, Float
from sqlalchemy.dialects.postgresql import UUID
from mpi_backend.database import Base


class ValidationBypassLog(Base):
    """Audit log for validation bypass operations"""
    __tablename__ = 'validation_bypass_log'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pdf_extraction_queue_id = Column(UUID(as_uuid=True), ForeignKey('raw.pdf_extraction_queue.id'), nullable=False)
    # `model_extracted_data` uses soft deletes (`deleted_at`). The FK only validates row existence, not
    # soft-delete state. Application-layer queries must still filter `deleted_at IS NULL`. Verify no
    # existing `validation_bypass_log` rows reference orphaned `model_extracted_data` IDs before migrating.
    model_extracted_data_id = Column(UUID(as_uuid=True), ForeignKey('raw.model_extracted_data.id'), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('public.users.id'), nullable=False)
    bypassed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    reason = Column(Text, nullable=True)
    previous_validation_score = Column(Float, nullable=True)

    __table_args__ = (
        Index('ix_vbl_pdf_id', 'pdf_extraction_queue_id'),
        Index('ix_vbl_user_id', 'user_id'),
        {'schema': 'public'}
    )
