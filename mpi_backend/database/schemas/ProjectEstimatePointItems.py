from pydantic import BaseModel
from typing import Optional

class ProjectEstimatePointItemsRequest(BaseModel):
    name: str
    pts: str
    qty: str
    amount: str
    project_estimate_id: int

    class Config:
        orm_mode = True


class ProjectEstimatePointItemsResponse(ProjectEstimatePointItemsRequest):
    id: Optional[int] = None

    class Config:
        orm_mode = True
