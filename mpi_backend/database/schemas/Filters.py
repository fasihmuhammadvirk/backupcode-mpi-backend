from pydantic import BaseModel
from typing import List, Dict, Any, Union
from datetime import date


class ComparisonFilter(BaseModel):
    column: str
    operator: str
    value: Union[str, int, float, date]  # supports date, int, and float


class FilterRequest(BaseModel):
    filters: Dict[str, List[Any]] = {}
    comparison_filters: List[ComparisonFilter] = []
