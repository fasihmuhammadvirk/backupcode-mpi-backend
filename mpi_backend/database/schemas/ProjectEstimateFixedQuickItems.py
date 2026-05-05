from pydantic import BaseModel
from typing import Optional

class ProjectEstimateFixedQuickItemsRequest(BaseModel):
    name: str
    amount: float

    class Config:
        orm_mode = True

class ProjectEstimateFixedQuickItemsResponse(ProjectEstimateFixedQuickItemsRequest):
    id: Optional[int] = None

    class Config:
        orm_mode = True