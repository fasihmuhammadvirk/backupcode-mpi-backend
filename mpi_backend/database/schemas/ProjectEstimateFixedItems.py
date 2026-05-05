from pydantic import BaseModel
from typing import Optional

class ProjectEstimateFixedItemsRequest(BaseModel):
    """
    Base schema for project estimate fixed items. This is the base class used for both creation and updating items.
    """
    name: str
    price: str
    project_estimation_id: int  # Foreign key to the ProjectEstimation

    class Config:
        orm_mode = True
        
class ProjectEstimateFixedItemsResponse(ProjectEstimateFixedItemsRequest):
    id: Optional[int] = None  # The item ID, optionally included in the response

    class Config:
        orm_mode = True
