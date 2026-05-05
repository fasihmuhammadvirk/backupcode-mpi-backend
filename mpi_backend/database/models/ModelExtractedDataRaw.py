"""
ModelExtractedDataRaw - Raw extraction data model for normalized architecture.

This model stores one row per extraction attempt (not per line item).
All invoice data (global fields + line items) are stored in the raw_data JSONB column.
dbt handles parsing and transformation into the analytics layer.

Schema: raw
Table: model_extracted_data
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from mpi_backend.database import Base


class ModelExtractedDataRaw(Base):
    """
    Raw extraction data - one row per extraction attempt.

    All invoice data (global fields + line items) stored in raw_data JSONB.
    dbt handles parsing and transformation.

    raw_data structure:
    {
        "ref_no": "INV-12345",
        "date": "2026-01-15",
        "vendor": "World Wide Plumbing",
        "buyer": "John Smith",
        "po_no": "PO-98765",
        "customer_job": "123 Main St, Brooklyn",
        "bill": "Bill info",
        "tax": "20.70",
        "sub_total": "205.00",
        "freight": "10.00",
        "line_items": [
            {"item": "PVC-101", "description": "PVC Pipe", "qty": 10, "cost": "15.50", "amount": "155.00"},
            {"item": "FITTING-45", "description": "Elbow", "qty": 20, "cost": "2.50", "amount": "50.00"}
        ],
        "confidence_score": 0.92,
        "_validation_passed": true,
        "_header_details": {...},
        "_line_items_details": {...}
    }
    """
    __tablename__ = 'model_extracted_data'

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign Keys / References
    s3_file_key = Column(String, nullable=False)  # Identifies the PDF
    pdf_extraction_queue_id = Column(UUID(as_uuid=True), nullable=True)
    email_queue_id = Column(UUID(as_uuid=True), nullable=True)

    # Extraction Metadata
    model_name = Column(String(100), nullable=False)  # gemini-2.0-flash, etc.
    prompt_hash = Column(String(12), nullable=True)   # Hash of extraction prompt

    # Quality Metrics (indexed for fast filtering before dbt)
    status = Column(String(50), default='human_review_required')
    validation_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)

    # The Source of Truth - Complete Extraction Response
    raw_data = Column(JSONB, nullable=False)

    # Timestamps
    extracted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deletion_reason = Column(String(500), nullable=True)

    __table_args__ = (
        Index('ix_med_raw_s3_file_key', 's3_file_key'),
        Index('ix_med_raw_extracted_at', 'extracted_at'),
        Index('ix_med_raw_pdf_queue_id', 'pdf_extraction_queue_id'),
        Index('ix_med_raw_status', 'status'),
        Index('ix_med_raw_deleted_at', 'deleted_at'),
        # Composite index for deduplication queries
        Index('ix_med_raw_dedup', 's3_file_key', 'model_name', 'extracted_at'),
        {'schema': 'raw'}
    )

    # Status constants
    STATUS_HUMAN_REVIEW = 'human_review_required'
    STATUS_MODEL_APPROVED = 'model_approved'
    STATUS_REJECTED = 'rejected'

    def __repr__(self):
        return f"<ModelExtractedDataRaw(id={self.id}, s3_file_key={self.s3_file_key}, model={self.model_name})>"
