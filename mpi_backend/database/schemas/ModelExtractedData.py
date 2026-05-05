from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import date
from uuid import UUID


class ModelExtractedDataResponse(BaseModel):
    id: int
    item: Optional[str] = None
    description: Optional[str] = None
    qty: Optional[int] = None
    cost: Optional[float] = None
    amount: Optional[str] = None
    sub_total: Optional[str] = None
    date: date
    ref_no: Optional[str] = None
    po_number: Optional[str] = None
    customer_job: Optional[str] = None
    bill: Optional[str] = None
    vendor: Optional[str] = None
    buyer: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None
    model_name: Optional[str] = None
    file_path: Optional[str] = None
    confidence_score: Optional[float] = None
    tax: Optional[str] = None
    freight: Optional[str] = None
    total: Optional[str] = None
    misc_charges: Optional[List[Dict[str, Any]]] = None
    pdf_extraction_queue_id: Optional[UUID] = None
    status: Optional[str] = None
    signed_url: Optional[str] = None

    class Config:
        from_attributes = True
        populate_by_name = True
        json_encoders = {
            UUID: str,
            date: lambda v: v.strftime('%d/%m/%Y') if v else None
        }


class GroupedModelExtractedDataResponse(BaseModel):
    """Response model for grouped model extracted data."""
    item: Optional[str] = None
    pdf_extraction_queue_id: Optional[UUID] = None
    qty: Optional[int] = None
    records: List[ModelExtractedDataResponse] = Field(default_factory=list)
    
    class Config:
        from_attributes = True
        populate_by_name = True
        json_encoders = {
            UUID: str,
            date: lambda v: v.strftime('%d/%m/%Y') if v else None
        }
        
