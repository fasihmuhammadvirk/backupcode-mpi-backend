from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class SyncMappingsResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    new_mappings_count: Optional[int] = None
    existing_mappings_count: Optional[int] = None
    timestamp: datetime = datetime.now()

    class Config:
        from_attributes = True 