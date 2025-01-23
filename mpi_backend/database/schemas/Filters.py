from pydantic import BaseModel
from typing import List, Dict, Any, Union,Optional
from datetime import date
from uuid import UUID


class ComparisonFilter(BaseModel):
    column: str
    operator: str
    value: Union[str, int, float, date]  # supports date, int, and float

class OrderByFilter(BaseModel):
    column: str
    order: str  # "asc" for ascending or "desc" for descending

class FilterRequest(BaseModel):
    filters: Dict[str, List[Any]] = {}
    comparison_filters: List[ComparisonFilter] = []
    order_by: Optional[List[OrderByFilter]] = None  # multiple ordering supported

class SendtoQBFilterRequest(BaseModel):
    filters: Dict[str, List[Any]] = {}
    comparison_filters: List[ComparisonFilter] = []
    order_by: Optional[List[OrderByFilter]] = None
    excluded_invoice_ids: List[UUID] = None

class ExportToExcelFilterRequest(BaseModel):
    filters: Dict[str, List[Any]] = {}
    comparison_filters: List[ComparisonFilter] = []
    order_by: Optional[List[OrderByFilter]] = None
    excluded_rows_ids: List[int] = None
    columns: Optional[List[str]] = []