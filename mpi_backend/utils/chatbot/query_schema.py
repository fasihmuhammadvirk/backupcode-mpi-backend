"""
Query Schema Definition
Defines JSON-based query parameters for ORM-level database queries
"""

from typing import List, Optional, Dict, Any, Literal, Union
from pydantic import BaseModel, Field
from datetime import date, datetime
from enum import Enum


class FilterOperator(str, Enum):
    """Filter operators for query conditions"""
    EQUALS = "eq"
    NOT_EQUALS = "ne"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    IN = "in"
    NOT_IN = "not_in"
    LIKE = "like"
    ILIKE = "ilike"  # Case-insensitive like
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"
    BETWEEN = "between"


class AggregateFunction(str, Enum):
    """Aggregate functions for query results"""
    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    COUNT_DISTINCT = "count_distinct"


class SortOrder(str, Enum):
    """Sort order for query results"""
    ASC = "asc"
    DESC = "desc"


class TableName(str, Enum):
    """Available database tables"""
    # Raw tables (legacy - prefer mart tables for chatbot queries)
    INVOICES = "invoices"
    INVOICE_ITEMS = "invoice_items"
    SUPPLIERS = "suppliers"
    ITEMS_MAPPING = "items_mapping"
    CUSTOMER_JOB_MAPPINGS = "customer_job_mappings"
    UNMAPPED_ITEMS = "unmapped_items"
    ITEM_CLASSIFICATION = "item_classification"
    MONTHLY_STATEMENTS = "monthly_statements"
    
    # DBT Mart tables (preferred for chatbot - pre-cleaned, optimized data)
    INVOICE_ITEMS_MART = "invoice_items_mart"  # analytics.mart__invoice_items
    PRICE_INCREASES_MART = "price_increases_mart"  # analytics.mart__price_increases
    ADDRESS_SHEET_AGGREGATES_MART = "address_sheet_aggregates_mart"  # analytics.mart__address_sheet_aggregates


class FilterCondition(BaseModel):
    """Single filter condition"""
    field: str = Field(..., description="Field name to filter on")
    operator: FilterOperator = Field(..., description="Filter operator")
    value: Optional[Union[str, int, float, bool, List[Any], date, datetime]] = Field(
        None, 
        description="Value to compare against (not needed for is_null/is_not_null)"
    )
    
    class Config:
        use_enum_values = True


class JoinCondition(BaseModel):
    """Join condition for multi-table queries"""
    table: TableName = Field(..., description="Table to join with")
    on_field: str = Field(..., description="Field from the main table")
    join_field: str = Field(..., description="Field from the joined table")
    join_type: Literal["inner", "left", "right", "outer"] = Field(
        "inner", 
        description="Type of join"
    )
    
    class Config:
        use_enum_values = True


class AggregateCondition(BaseModel):
    """Aggregate condition for data aggregation"""
    function: AggregateFunction = Field(..., description="Aggregate function")
    field: Optional[str] = Field(None, description="Field to aggregate (None for COUNT)")
    alias: str = Field(..., description="Alias for the aggregated result")
    
    class Config:
        use_enum_values = True


class SortCondition(BaseModel):
    """Sort condition for ordering results"""
    field: str = Field(..., description="Field to sort by")
    order: SortOrder = Field(SortOrder.ASC, description="Sort order")
    
    class Config:
        use_enum_values = True


class QueryParameters(BaseModel):
    """
    JSON-based query parameters for ORM-level database queries
    This replaces raw SQL generation with structured parameters
    """
    
    # Core query parameters
    table: TableName = Field(..., description="Primary table to query")
    
    # Fields to select
    fields: List[str] = Field(
        default_factory=lambda: ["*"],
        description="Fields to select (use '*' for all)"
    )
    
    # Filters
    filters: List[FilterCondition] = Field(
        default_factory=list,
        description="Filter conditions (combined with AND logic)"
    )
    
    # OR filters - if provided, these are OR'ed with the main filters
    or_filters: Optional[List[List[FilterCondition]]] = Field(
        None,
        description="Groups of OR filter conditions"
    )
    
    # Joins
    joins: List[JoinCondition] = Field(
        default_factory=list,
        description="Join conditions for multi-table queries"
    )
    
    # Aggregations
    aggregates: List[AggregateCondition] = Field(
        default_factory=list,
        description="Aggregate functions to apply"
    )
    
    # Group by
    group_by: List[str] = Field(
        default_factory=list,
        description="Fields to group by (required if aggregates are used)"
    )
    
    # Sorting
    sort: List[SortCondition] = Field(
        default_factory=list,
        description="Sort conditions"
    )
    
    # Pagination
    limit: Optional[int] = Field(
        None,
        description="Maximum number of results to return",
        ge=1,
        le=1000
    )
    
    offset: Optional[int] = Field(
        None,
        description="Number of results to skip",
        ge=0
    )
    
    # Distinct
    distinct: bool = Field(
        False,
        description="Return only distinct results"
    )
    
    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "table": "invoices",
                "fields": ["id", "date", "supplier_id", "status"],
                "filters": [
                    {
                        "field": "status",
                        "operator": "eq",
                        "value": "PROCESSED"
                    },
                    {
                        "field": "date",
                        "operator": "gte",
                        "value": "2024-01-01"
                    }
                ],
                "sort": [
                    {
                        "field": "date",
                        "order": "desc"
                    }
                ],
                "limit": 50
            }
        }


class QueryResult(BaseModel):
    """Result of a query execution"""
    success: bool = Field(..., description="Whether the query executed successfully")
    data: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Query results as list of dictionaries"
    )
    count: int = Field(..., description="Number of results returned")
    total_count: Optional[int] = Field(
        None,
        description="Total count without pagination (if requested)"
    )
    error: Optional[str] = Field(None, description="Error message if failed")
    query_info: Dict[str, Any] = Field(
        default_factory=dict,
        description="Information about the executed query"
    )

