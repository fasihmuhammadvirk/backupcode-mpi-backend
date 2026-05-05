from pydantic import BaseModel
from typing import Optional

class ProjectEstimateFinishItemsRequest(BaseModel):
    name: str
    price: str
    qty: str
    amount: str
    project_estimate_id: int

    class Config:
        orm_mode = True


class ProjectEstimateFinishItemsResponse(ProjectEstimateFinishItemsRequest):
    id: Optional[int] = None
