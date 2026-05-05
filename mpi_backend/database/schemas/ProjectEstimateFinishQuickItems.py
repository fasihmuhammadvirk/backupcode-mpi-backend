from pydantic import BaseModel
from typing import Optional

class ProjectEstimateFinishQuickItemsRequest(BaseModel):
    name: str
    price: float

    class Config:
        orm_mode = True
        
class ProjectEstimateFinishQuickItemsResponse(ProjectEstimateFinishQuickItemsRequest):
    id: Optional[int] = None

