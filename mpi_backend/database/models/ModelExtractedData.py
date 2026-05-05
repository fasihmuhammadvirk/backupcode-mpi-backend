import uuid
from sqlalchemy import Column, String, Integer, Float, JSON, ForeignKey, UUID, Date
from mpi_backend.database import Base
from sqlalchemy.orm import relationship
from datetime import datetime
from sqlalchemy import DateTime

class ModelExtractedData(Base):
    __tablename__ = 'model_extracted_data'
    
    id = Column(Integer, primary_key=True)
    item = Column(String)
    description = Column(String)
    qty = Column(String)
    cost = Column(String)
    amount = Column(String)
    date = Column(Date)
    ref_no = Column(String)
    po_number = Column(String)
    customer_job = Column(String)
    bill = Column(String)
    vendor = Column(String)
    buyer = Column(String)
    raw_data = Column(JSON)
    model_name = Column(String)
    file_path = Column(String)
    s3_file_key = Column(String)
    confidence_score = Column(Float)
    tax = Column(String)
    sub_total = Column(String)
    freight = Column(String)
    total = Column(String, nullable=True)
    misc_charges = Column(JSON, nullable=True)
    prompt_hash = Column(String(12), nullable=True, index=True)
    pdf_extraction_queue_id = Column(UUID(as_uuid=True), ForeignKey('raw.pdf_extraction_queue.id'))
    pdf_extraction_queue = relationship("PdfExtractionQueue", back_populates="model_extracted_data")
    status = Column(String, default='human_review_required')
    validation_score = Column(Float, nullable=True)
    extracted_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deletion_reason = Column(String(500), nullable=True)
    line_order = Column(Integer, nullable=True)
    