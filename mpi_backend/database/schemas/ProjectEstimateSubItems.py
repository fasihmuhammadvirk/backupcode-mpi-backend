from pydantic import BaseModel
from enum import Enum
from typing import Optional


class EstimateType(str, Enum):
    LABOR_ONLY = "LABOR_ONLY"
    LABOR_AND_MATERIAL = "LABOR_AND_MATERIAL"
    
class ProjectEstimateSubItemRequest(BaseModel):
    name: str
    price: str
    type: EstimateType
    project_estimate_id: int  # Foreign key for ProjectEstimation

    class Config:
        orm_mode = True

class ProjectEstimateSubItemResponse(ProjectEstimateSubItemRequest):
    id: Optional[int] = None

