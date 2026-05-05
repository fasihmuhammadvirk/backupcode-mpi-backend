"""
Extraction Queue Pydantic Schemas - Request/response validation models.

Extracted from routes to follow ADR-0014 (Schema-Level Validation).
"""

import re
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator


# ==============================================================================
# REQUEST MODELS
# ==============================================================================

class QueueStatusFilters(BaseModel):
    """Input validation for queue status endpoint date filtering"""
    date_from: Optional[AwareDatetime] = Field(None, description="Filter from this date (ISO 8601 with timezone, e.g. 2024-01-15T00:00:00Z)")
    date_to: Optional[AwareDatetime] = Field(None, description="Filter to this date (ISO 8601 with timezone, e.g. 2024-01-15T23:59:59Z)")

    @field_validator('date_to')
    @classmethod
    def validate_date_range(cls, v: Optional[datetime], info) -> Optional[datetime]:
        if v and info.data.get('date_from'):
            if (v - info.data['date_from']).days > 90:
                raise ValueError("Date range cannot exceed 90 days")
        return v


class QueueDetailFilters(BaseModel):
    """Input validation for queue detail endpoint - prevents SQL injection"""
    status: Optional[str] = Field(None, pattern=r'^[A-Z_a-z]+$', description="Queue status filter")
    extraction_status: Optional[str] = Field(
        None, pattern=r'^(unextracted|failed|completed)$',
        description="Card-level extraction status filter: unextracted, failed, completed"
    )
    sender: Optional[str] = Field(None, max_length=255, description="Sender email filter")
    subject: Optional[str] = Field(None, max_length=255, description="Subject line filter")
    date_from: Optional[AwareDatetime] = Field(None, description="Filter from this date (ISO 8601 with timezone, e.g. 2024-01-15T00:00:00Z)")
    date_to: Optional[AwareDatetime] = Field(None, description="Filter to this date (ISO 8601 with timezone, e.g. 2024-01-15T23:59:59Z)")
    limit: int = Field(50, ge=1, le=1000, description="Number of records (1-1000)")
    offset: int = Field(0, ge=0, description="Number of records to skip")

    @field_validator('sender')
    @classmethod
    def sanitize_sender(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return re.sub(r'[^\w@.\-]', '', v)
        return v

    @field_validator('subject')
    @classmethod
    def sanitize_subject(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return re.sub(r'[\x00-\x1f\x7f]', '', v)[:255]
        return v

    @field_validator('date_to')
    @classmethod
    def validate_date_range(cls, v: Optional[datetime], info) -> Optional[datetime]:
        if v and info.data.get('date_from'):
            if (v - info.data['date_from']).days > 90:
                raise ValueError("Date range cannot exceed 90 days")
        return v


class ReprocessRequest(BaseModel):
    """Input validation for reprocess single endpoint. At least one of email_id or pdf_id required."""
    email_id: Optional[str] = Field(None, description="Email ID to reprocess")
    pdf_id: Optional[str] = Field(None, description="Specific PDF ID to reprocess")

    @model_validator(mode='after')
    def at_least_one_id(self):
        if not self.email_id and not self.pdf_id:
            raise ValueError("At least one of email_id or pdf_id is required")
        return self


class ReprocessBatchRequest(BaseModel):
    """Input validation for batch reprocess endpoint"""
    pdf_ids: List[str] = Field(..., description="List of PDF extraction queue IDs to reprocess", min_length=1, max_length=100)


class BypassValidationRequest(BaseModel):
    """Input validation for bypass-validation endpoint"""
    pdf_id: str = Field(..., description="PDF extraction queue ID to bypass")
    reason: Optional[str] = Field(None, max_length=500, description="Optional reason for bypass")


# ==============================================================================
# RESPONSE MODELS
# ==============================================================================

class PaginationMeta(BaseModel):
    """Reusable pagination metadata"""
    total_count: int


class QueueStatusResponse(BaseModel):
    """Response model for queue status endpoint"""
    failed_extractions: int
    awaiting_extraction: int
    total_invoices: int


class QueueDetailItem(BaseModel):
    """Single item in queue detail response -- only fields consumed by the frontend"""
    email_id: Optional[str] = None
    email_date: Optional[datetime] = None
    email_error: Optional[str] = None
    email_created: Optional[datetime] = None
    pdf_id: Optional[str] = None
    pdf_status: Optional[str] = None
    pdf_error: Optional[str] = None
    s3_key: Optional[str] = None

    # Enhanced business invoice data fields
    ref_no: Optional[str] = None
    job_address: Optional[str] = None
    invoice_date: Optional[datetime] = None
    supplier: Optional[str] = None
    amount: Optional[float] = None
    validation_score: Optional[float] = None
    validation_reason: Optional[str] = None
    raw_json: Optional[Dict[str, Any]] = None

    @field_validator('*', mode='before')
    @classmethod
    def ensure_tz_aware(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class QueueDetailResponse(BaseModel):
    """Response model for queue detail endpoint"""
    items: List[QueueDetailItem]
    pagination: PaginationMeta


class VendorPatternItem(BaseModel):
    """Single vendor pattern"""
    sender_pattern: str
    vendor_name: Optional[str] = None
    last_matched_at: Optional[datetime] = None
    match_count: int = 0
    recent_emails: int = 0
    last_email_date: Optional[datetime] = None
    is_recently_active: bool = False

    @field_validator('*', mode='before')
    @classmethod
    def ensure_tz_aware(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class VendorPatternsResponse(BaseModel):
    """Response model for vendors endpoint"""
    patterns: List[VendorPatternItem]
    summary: Dict[str, Any]
    cache_timestamp: datetime
    ttl_seconds: int


class ReprocessSingleResponse(BaseModel):
    """Response model for reprocess-single endpoint"""
    status: str
    message: str
    pdf_id: str
    email_id: Optional[str]
    previous_status: str
    new_status: str
    email_info: Dict[str, Any]
    timestamp: datetime

    @field_validator('*', mode='before')
    @classmethod
    def ensure_tz_aware(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class ReprocessBatchResult(BaseModel):
    """Single reprocess result"""
    pdf_id: str
    success: bool
    message: str


class ReprocessBatchResponse(BaseModel):
    """Response for batch reprocess endpoint"""
    total_requested: int
    successful: int
    failed: int
    results: List[ReprocessBatchResult]
    message: str


class BypassValidationResponse(BaseModel):
    """Response for bypass-validation endpoint"""
    status: str = Field(..., description="Operation status (success/error)")
    message: str = Field(..., description="Human-readable message")
    filename: str = Field(..., description="S3 filename (last part of s3_key) or fallback to PDF ID")
    model_extracted_data_id: str = Field(..., description="Model extracted data ID")
    previous_validation_score: Optional[float] = Field(None, description="Previous validation score")
    new_validation_score: float = Field(95.123, description="New validation score after bypass")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Operation timestamp")

    @field_validator('*', mode='before')
    @classmethod
    def ensure_tz_aware(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
