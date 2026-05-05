import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from mpi_backend.database import Base

class UserUploadedPdf(Base):
    """Track metadata for user-uploaded PDFs"""
    __tablename__ = 'user_uploaded_pdfs'
    __table_args__ = {'schema': 'raw'}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    s3_file_key = Column(Text, nullable=False)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False)
    supplier_name = Column(String(255), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deletion_reason = Column(String(500), nullable=True)

