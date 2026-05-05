from pydantic import BaseModel, field_validator, Field
from typing import Optional


class ProjectEstimationRequest(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    contract_value: Optional[str] = None
    budget_allocation: Optional[str] = None
    labor_percentage: Optional[str] = None
    material_percentage: Optional[str] = None
    dollar_point: Optional[str] = None
    budget_limit: Optional[str] = None
    labor_rem: Optional[str] = None
    material_rem: Optional[str] = None
    finishing: Optional[str] = None
    point_value: Optional[str] = None
    target_value: Optional[str] = None
    fixed_costs: Optional[str] = None

class ProjectEstimationResponse(ProjectEstimationRequest):
    id: Optional[int] = None
    