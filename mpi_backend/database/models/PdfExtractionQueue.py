import uuid
from enum import Enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from mpi_backend.database import Base


class PdfExtractionStatus(str, Enum):
    """Canonical statuses for raw.pdf_extraction_queue records"""
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    FAILED = 'failed'
    VALIDATION_FAILED = 'validation_failed'
    BYPASSED = 'bypassed'


class PdfExtractionQueue(Base):
    """Track PDF extraction status for invoice processing"""
    __tablename__ = 'pdf_extraction_queue'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_queue_id = Column(UUID(as_uuid=True), ForeignKey('raw.email_download_queue.id'), nullable=True)
    user_upload_id = Column(UUID(as_uuid=True), ForeignKey('raw.user_uploaded_pdfs.id'), nullable=True)
    s3_key = Column(Text, nullable=False)
    supplier_name = Column(String(255), nullable=True)
    status = Column(String(20), default=PdfExtractionStatus.PENDING, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    extracted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deletion_reason = Column(String(500), nullable=True)

    __table_args__ = (
        Index('idx_pdf_extraction_queue_status', 'status'),
        Index('idx_pdf_extraction_queue_email_id', 'email_queue_id'),
        Index('idx_pdf_extraction_queue_user_upload_id', 'user_upload_id'),
        {'schema': 'raw'}
    )

    # Relationships
    model_extracted_data = relationship("ModelExtractedData", back_populates="pdf_extraction_queue")

    # Deprecated: use PdfExtractionStatus enum directly
    STATUS_PENDING = PdfExtractionStatus.PENDING
    STATUS_IN_PROGRESS = PdfExtractionStatus.IN_PROGRESS
    STATUS_COMPLETED = PdfExtractionStatus.COMPLETED
    STATUS_FAILED = PdfExtractionStatus.FAILED
