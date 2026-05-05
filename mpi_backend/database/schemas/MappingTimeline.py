import logging
from typing import Optional, List

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import RowMapping

logger = logging.getLogger(__name__)


class MappingHistoryRequest(BaseModel):
    """Request body for fetching a single item's mapping history."""

    supplier_item_ids: str = Field(..., description="Supplier item code (e.g. 'SP*00011341-W')")
    supplier_name: Optional[str] = Field(None, description="Supplier name to look up ID")

    @model_validator(mode='after')
    def validate_request(self):
        if not self.supplier_item_ids or not self.supplier_item_ids.strip():
            raise ValueError("supplier_item_ids must not be empty")
        return self


class MappingHistoryEvent(BaseModel):
    """A single point-in-time mapping state event from mart__item_mapping_timeline."""

    mapping_type: str
    recorded_at: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier: Optional[str] = None
    sheet_title: str
    is_delete_record: bool = False

    @classmethod
    def from_dict(cls, data: RowMapping) -> "MappingHistoryEvent":
        """Create a MappingHistoryEvent from a DB RowMapping."""
        recorded_at = data["recorded_at"]
        return cls(
            mapping_type=data["mapping_type"],
            recorded_at=recorded_at.isoformat() if recorded_at is not None else None,
            supplier_id=data["supplier_id"],
            supplier=data["supplier"],
            sheet_title=data.get("sheet_title") or "UNMAPPED",
            is_delete_record=data.get("is_delete_record", False)
        )



class MappingHistoryResponse(BaseModel):
    """Response for a single item's full mapping history timeline."""

    supplier_item_ids: str
    supplier_id: Optional[int] = None
    events: List[MappingHistoryEvent]
