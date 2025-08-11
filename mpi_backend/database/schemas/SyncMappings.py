from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class SyncMappingsResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    new_mappings_count: Optional[int] = None
    existing_mappings_count: Optional[int] = None
    timestamp: datetime = datetime.now()
    # Added fields for visibility of last operations
    last_sync_time: Optional[str] = None
    last_update_no_match_uidi_time: Optional[str] = None
    last_update_all_time: Optional[str] = None

    class Config:
        from_attributes = True
