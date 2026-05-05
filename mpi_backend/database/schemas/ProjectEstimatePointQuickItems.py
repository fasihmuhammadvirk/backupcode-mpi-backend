from pydantic import BaseModel
from typing import Optional
from decimal import Decimal

class ProjectEstimatePointQuickItemsRequest(BaseModel):
    name: str
    amount: float

    class Config:
        orm_mode = True

class ProjectEstimatePointQuickItemsResponse(ProjectEstimatePointQuickItemsRequest):
    id: Optional[int] = None

