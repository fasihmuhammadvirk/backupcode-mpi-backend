import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from mpi_backend.database import Base


class EmailDownloadQueue(Base):
    """Track email download status for bulk processing"""
    __tablename__ = 'email_download_queue'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_uid = Column(String(100), nullable=False, unique=True)
    message_id = Column(String(255), nullable=True)
    sender = Column(String(255), nullable=False)
    subject = Column(Text, nullable=True)
    email_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default='PENDING', nullable=False)
    s3_keys = Column(JSONB, default=list)  # JSONB array of uploaded S3 keys
    attachment_count = Column(Integer, default=0)  # Total attachments (all types)
    in_email_pdf_count = Column(Integer, default=0)  # PDFs found in email
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deletion_reason = Column(String(500), nullable=True)

    __table_args__ = (
        Index('idx_email_queue_status', 'status'),
        Index('idx_email_queue_email_date', 'email_date'),
        Index('idx_email_queue_sender', 'sender'),
        {'schema': 'raw'}
    )

    # Status constants
    STATUS_PENDING = 'PENDING'
    STATUS_DOWNLOADING = 'DOWNLOADING'
    STATUS_DOWNLOADED = 'DOWNLOADED'
    STATUS_PARTIAL = 'PARTIAL'  # Some PDFs uploaded, some failed
    STATUS_FAILED = 'FAILED'
    STATUS_SKIPPED = 'SKIPPED'
