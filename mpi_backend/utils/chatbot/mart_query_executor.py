"""
Mart Query Executor
Executes queries against dbt mart tables using SQLAlchemy ORM.

This executor is specifically designed for the pre-cleaned, optimized mart tables:
- analytics.mart__invoice_items (InvoiceItemMart)
- analytics.mart__price_increases (PriceIncreaseMart)
- analytics.mart__address_sheet_aggregates (AddressSheetAggregate)

Benefits over raw table queries:
- No complex string-to-numeric casting (amount, cost, qty already numeric)
- Pre-normalized columns for fast fuzzy search
- Data already filtered (is_active = TRUE)
- Price increase data available via simple join
- Optimized indexes for common query patterns
"""

import logging
from typing import List, Dict, Any, Optional, Type
from datetime import date, datetime
from sqlalchemy import and_, or_, func, distinct, desc, asc, text
from sqlalchemy.orm import Session, Query
from sqlalchemy.dialects import postgresql

from mpi_backend.database import engine, SessionLocal
from mpi_backend.database.models.InvoiceItemMart import InvoiceItemMart
from mpi_backend.database.models.PriceIncreaseMart import PriceIncreaseMart
from mpi_backend.database.models.AddressSheetAggregate import AddressSheetAggregate
from mpi_backend.database.dao.dao_utils import check_table_exists
from mpi_backend.utils.chatbot.query_schema import (
    QueryParameters, QueryResult, FilterCondition, 
    FilterOperator, AggregateFunction, TableName, SortOrder
)

logger = logging.getLogger(__name__)


class MartQueryExecutor:
    """
    Executes database queries against dbt mart tables using SQLAlchemy ORM.
    
    Designed for simplified queries on pre-cleaned data:
    - Numeric fields are already cast (amount, cost, qty are Float/Numeric)
    - Normalized columns available for fuzzy search
    - Only active records (no is_active filtering needed)
    - Price increase data via join to PriceIncreaseMart
    """
    
    # Mart table name to model mapping
    MART_MODELS: Dict[str, Type] = {
        TableName.INVOICE_ITEMS_MART.value: InvoiceItemMart,
        TableName.PRICE_INCREASES_MART.value: PriceIncreaseMart,
        TableName.ADDRESS_SHEET_AGGREGATES_MART.value: AddressSheetAggregate,
        # Legacy table names map to mart models for chatbot
        TableName.INVOICE_ITEMS.value: InvoiceItemMart,
    }
    
    # Column name mapping: raw table columns -> mart columns
    # This allows the LLM to use familiar column names from raw tables
    # while the executor maps them to mart table columns.
    # Key difference: "invoice_items_id" maps to "id" because the mart table
    # exposes the database column "invoice_items_id" as "id" in the ORM model.
    COLUMN_MAPPING = {
        # Numeric columns (already cast in mart)
        "amount": "amount",  # Already Float in mart
        "cost": "cost",      # Already Float in mart
        "qty": "qty",        # Already Integer in mart
        
        # Normalized columns for fuzzy search
        "customer_job": "customer_job",  # Already normalized in mart
        "sheet_name": "sheet_name",      # Already normalized in mart
        
        # Standard columns (same names)
        "id": "id",
        "invoice_items_id": "id",
        "invoice_id": "invoice_id",
        "item": "item",
        "mpi_item": "mpi_item",
        "description": "description",
        "mpi_description": "mpi_description",
        "vendor": "vendor",
        "buyer": "buyer",
        "date": "date",
        "ref_no": "ref_no",
        "po_number": "po_number",
        "account": "account",
        "assigned_account": "assigned_account",
        "class_": "class_",
        "filename": "filename",
        "bill": "bill",
        "export_status": "export_status",
        "memo": "memo",
        "date_added": "date_added",
        
        # Normalized search columns
        "item_normalized": "item_normalized",
        "description_normalized": "description_normalized",
        "vendor_search_normalized": "vendor_search_normalized",
        "customer_job_normalized": "customer_job_normalized",
        "sheet_name_normalized": "sheet_name_normalized",
        "mpi_item_normalized": "mpi_item_normalized",
        "mpi_description_normalized": "mpi_description_normalized",
        "buyer_normalized": "buyer_normalized",
        "ref_no_normalized": "ref_no_normalized",
    }
    
    def __init__(self):
        """Initialize the mart query executor"""
        self.engine = engine
        self._mart_available = None  # Lazy check
        logger.info("MartQueryExecutor initialized")
    
    def is_mart_available(self, session: Optional[Session] = None) -> bool:
        """
        Check if the mart__invoice_items table exists.
        Caches the result for performance.
        """
        if self._mart_available is not None:
            return self._mart_available
        
        own_session = False
        try:
            if session is None:
                session = SessionLocal()
                own_session = True
            
            self._mart_available = check_table_exists(
                session, 
                InvoiceItemMart.__table_args__.get("schema"), 
                InvoiceItemMart.__tablename__
            )
            logger.info(f"Mart table availability: {self._mart_available}")
            return self._mart_available
            
        except Exception as e:
            logger.warning(f"Error checking mart availability: {e}")
            self._mart_available = False
            return False
        finally:
            if own_session and session:
                session.close()
    
    def execute_query(
        self, 
        params: QueryParameters,
        session: Optional[Session] = None
    ) -> QueryResult:
        """
        Execute a query against mart tables based on JSON parameters.
        
        Args:
            params: Query parameters (will be translated to mart schema)
            session: Optional existing database session
            
        Returns:
            QueryResult with data and metadata
        """
        own_session = False
        try:
            # Create session if not provided
            if session is None:
                session = SessionLocal()
                own_session = True
            
            # Check if mart is available
            if not self.is_mart_available(session):
                return QueryResult(
                    success=False,
                    data=[],
                    count=0,
                    error="Mart tables not available. Please ensure dbt has been run.",
                    query_info={"table": params.table, "mart_available": False}
                )
            
            # Get the model for the table
            model = self._get_model(params.table)
            
            # Build the base query
            query = self._build_base_query(session, model, params)
            
            # Apply filters
            query = self._apply_filters(query, model, params.filters)
            
            # Apply OR filters if provided
            if params.or_filters:
                query = self._apply_or_filters(query, model, params.or_filters)
            
            # Apply distinct
            if params.distinct:
                query = query.distinct()
            
            # Get total count before pagination (if aggregates not used)
            total_count = None
            if not params.aggregates and (params.limit or params.offset):
                total_count = query.count()
            
            # Apply sorting
            for sort in params.sort:
                query = self._apply_sort(query, model, sort)
            
            # Apply pagination
            if params.offset:
                query = query.offset(params.offset)
            if params.limit:
                query = query.limit(params.limit)
            
            # Execute query
            if params.aggregates:
                # Handle aggregate queries
                results = self._execute_aggregate_query(session, model, params)
            else:
                # Handle regular queries
                logger.info("Executing mart query...")
                
                # Log the SQL for debugging
                try:
                    compiled = str(query.statement.compile(
                        dialect=postgresql.dialect(), 
                        compile_kwargs={"literal_binds": True}
                    ))
                    logger.debug(f"Generated SQL:\n{compiled}")
                except Exception as e:
                    logger.exception("Could not compile SQL for logging")
                
                results = query.all()
                logger.info(f"Query returned {len(results)} results from mart")
                results = self._serialize_results(results, params.fields)
            
            return QueryResult(
                success=True,
                data=results,
                count=len(results),
                total_count=total_count,
                query_info={
                    "table": params.table,
                    "source": InvoiceItemMart.__tablename__,
                    "filters_applied": len(params.filters),
                    "aggregates_applied": len(params.aggregates)
                }
            )
            
        except Exception as e:
            logger.exception("Error executing mart query")
            return QueryResult(
                success=False,
                data=[],
                count=0,
                error=str(e),
                query_info={"table": params.table if params else "unknown"}
            )
        
        finally:
            if own_session and session:
                session.close()
    
    def _get_model(self, table_name: str) -> Type:
        """Get the SQLAlchemy model for a table name"""
        if table_name in self.MART_MODELS:
            return self.MART_MODELS[table_name]
        
        # Default to InvoiceItemMart for invoice_items queries
        if table_name == "invoice_items":
            return InvoiceItemMart
        
        raise ValueError(
            f"Unknown table: {table_name}. "
            f"Available mart tables: {list(self.MART_MODELS.keys())}"
        )
    
    def _map_column(self, column_name: str) -> str:
        """Map a column name to the mart column name"""
        return self.COLUMN_MAPPING.get(column_name, column_name)
    
    def _build_base_query(
        self, 
        session: Session, 
        model: Type, 
        params: QueryParameters
    ) -> Query:
        """Build the base query with field selection"""
        
        # Handle field selection
        if params.fields and params.fields != ["*"]:
            columns = []
            for field in params.fields:
                # Skip relationship paths for mart queries (not needed)
                if '.' in field:
                    logger.debug(f"Skipping relationship field {field} for mart query")
                    continue
                
                # Map column name
                mapped_field = self._map_column(field)
                
                if hasattr(model, mapped_field):
                    columns.append(getattr(model, mapped_field))
                else:
                    logger.warning(f"Field {field} (mapped to {mapped_field}) not found in {model.__name__}")
            
            if columns:
                query = session.query(*columns)
            else:
                query = session.query(model)
        else:
            query = session.query(model)
        
        return query
    
    def _apply_filters(
        self, 
        query: Query, 
        model: Type, 
        filters: List[FilterCondition]
    ) -> Query:
        """Apply filter conditions to the query"""
        
        logger.info(f"Applying {len(filters)} filters to mart query")
        conditions = []
        
        for idx, filter_cond in enumerate(filters, 1):
            # Skip relationship paths - mart has flat structure
            if '.' in filter_cond.field:
                # Extract the final field name for relationship paths
                # e.g., "invoice.supplier_fk.supplier_name" -> use "vendor" instead
                field_name = filter_cond.field.split('.')[-1]
                if field_name == "supplier_name":
                    # Map supplier_name to vendor in mart
                    filter_cond.field = "vendor"
                else:
                    logger.warning(f"Relationship filter {filter_cond.field} not supported in mart, skipping")
                    continue
            
            logger.info(f"Filter {idx}: field={filter_cond.field}, operator={filter_cond.operator}, value={filter_cond.value}")
            
            condition = self._build_filter_condition(model, filter_cond)
            if condition is not None:
                conditions.append(condition)
            else:
                logger.warning(f"Filter {idx} returned None")
        
        if conditions:
            query = query.filter(and_(*conditions))
            logger.info(f"Applied {len(conditions)} conditions to query")
        
        return query
    
    def _apply_or_filters(
        self,
        query: Query,
        model: Type,
        or_filters: List[List[FilterCondition]]
    ) -> Query:
        """Apply OR filter conditions to the query"""
        
        or_groups = []
        for filter_group in or_filters:
            conditions = []
            for filter_cond in filter_group:
                condition = self._build_filter_condition(model, filter_cond)
                if condition is not None:
                    conditions.append(condition)
            if conditions:
                or_groups.append(or_(*conditions))
        
        if or_groups:
            query = query.filter(or_(*or_groups))
        
        return query
    
    def _build_filter_condition(
        self, 
        model: Type, 
        filter_cond: FilterCondition
    ):
        """Build a single filter condition for mart table"""
        
        # Map the column name
        mapped_field = self._map_column(filter_cond.field)
        
        # Check if field exists in model
        if not hasattr(model, mapped_field):
            # Try to use normalized column for text searches
            if filter_cond.operator in [FilterOperator.ILIKE, FilterOperator.LIKE, FilterOperator.CONTAINS]:
                normalized_field = f"{mapped_field}_normalized"
                if hasattr(model, normalized_field):
                    mapped_field = normalized_field
                    logger.info(f"Using normalized column {normalized_field} for fuzzy search")
                else:
                    logger.warning(f"Field {filter_cond.field} not found in {model.__name__}")
                    return None
            else:
                logger.warning(f"Field {filter_cond.field} not found in {model.__name__}")
                return None
        
        field = getattr(model, mapped_field)
        operator = filter_cond.operator
        value = filter_cond.value
        
        # Build condition based on operator
        if operator == FilterOperator.EQUALS:
            return field == value
        elif operator == FilterOperator.NOT_EQUALS:
            return field != value
        elif operator == FilterOperator.GREATER_THAN:
            return field > value
        elif operator == FilterOperator.GREATER_THAN_OR_EQUAL:
            return field >= value
        elif operator == FilterOperator.LESS_THAN:
            return field < value
        elif operator == FilterOperator.LESS_THAN_OR_EQUAL:
            return field <= value
        elif operator == FilterOperator.IN:
            if isinstance(value, list):
                return field.in_(value)
            return None
        elif operator == FilterOperator.NOT_IN:
            if isinstance(value, list):
                return ~field.in_(value)
            return None
        elif operator == FilterOperator.LIKE:
            return field.like(f"%{value}%")
        elif operator == FilterOperator.ILIKE:
            return field.ilike(f"%{value}%")
        elif operator == FilterOperator.CONTAINS:
            return field.contains(value)
        elif operator == FilterOperator.STARTS_WITH:
            return field.startswith(value)
        elif operator == FilterOperator.ENDS_WITH:
            return field.endswith(value)
        elif operator == FilterOperator.IS_NULL:
            return field.is_(None)
        elif operator == FilterOperator.IS_NOT_NULL:
            return field.isnot(None)
        elif operator == FilterOperator.BETWEEN:
            if isinstance(value, list) and len(value) == 2:
                return field.between(value[0], value[1])
            return None
        else:
            logger.warning(f"Unknown operator: {operator}")
            return None
    
    def _apply_sort(
        self, 
        query: Query, 
        model: Type, 
        sort_cond
    ) -> Query:
        """Apply sort condition to the query"""
        
        # Map column name
        mapped_field = self._map_column(sort_cond.field)
        
        if not hasattr(model, mapped_field):
            logger.warning(f"Sort field {sort_cond.field} not found in {model.__name__}")
            return query
        
        field = getattr(model, mapped_field)
        
        if sort_cond.order == SortOrder.DESC:
            query = query.order_by(desc(field))
        else:
            query = query.order_by(asc(field))
        
        return query
    
    def _execute_aggregate_query(
        self,
        session: Session,
        model: Type,
        params: QueryParameters
    ) -> List[Dict[str, Any]]:
        """
        Execute an aggregate query on mart table.
        
        Note: Aggregations on mart tables are simpler since:
        - amount, cost, qty are already numeric (no casting needed)
        - No complex string validation required
        """
        
        # Build aggregate expressions
        aggregate_exprs = []
        for agg in params.aggregates:
            expr = self._build_aggregate_expression(model, agg)
            if expr is not None:
                aggregate_exprs.append(expr.label(agg.alias))
        
        if not aggregate_exprs:
            raise ValueError("No valid aggregate expressions")
        
        # Build group by fields
        group_by_fields = []
        for field_name in params.group_by:
            mapped_field = self._map_column(field_name)
            if hasattr(model, mapped_field):
                group_by_fields.append(getattr(model, mapped_field))
        
        # Build query
        if group_by_fields:
            query = session.query(*group_by_fields, *aggregate_exprs)
        else:
            query = session.query(*aggregate_exprs)
        
        # Apply filters
        query = self._apply_filters(query, model, params.filters)
        
        # Apply OR filters
        if params.or_filters:
            query = self._apply_or_filters(query, model, params.or_filters)
        
        # Apply group by
        if group_by_fields:
            query = query.group_by(*group_by_fields)
        
        # Apply sorting
        for sort in params.sort:
            mapped_field = self._map_column(sort.field)
            if hasattr(model, mapped_field):
                field = getattr(model, mapped_field)
                if sort.order == SortOrder.DESC:
                    query = query.order_by(desc(field))
                else:
                    query = query.order_by(asc(field))
        
        # Apply pagination
        if params.offset:
            query = query.offset(params.offset)
        if params.limit:
            query = query.limit(params.limit)
        
        logger.info(f"Executing aggregate query on mart: {query}")
        
        # Execute and serialize
        results = query.all()
        return self._serialize_aggregate_results(results, params)
    
    def _build_aggregate_expression(self, model: Type, agg):
        """
        Build an aggregate expression.
        
        Note: Mart tables have pre-cast numeric columns, so no complex
        string-to-numeric casting is needed like in the raw ORM executor.
        """
        agg_func = agg.function
        
        if agg_func == AggregateFunction.COUNT:
            if agg.field:
                mapped_field = self._map_column(agg.field)
                if hasattr(model, mapped_field):
                    return func.count(getattr(model, mapped_field))
            return func.count()
        
        elif agg_func == AggregateFunction.COUNT_DISTINCT:
            if agg.field:
                mapped_field = self._map_column(agg.field)
                if hasattr(model, mapped_field):
                    return func.count(distinct(getattr(model, mapped_field)))
        
        elif agg_func == AggregateFunction.SUM:
            if agg.field:
                mapped_field = self._map_column(agg.field)
                if hasattr(model, mapped_field):
                    # Mart tables have numeric columns - no casting needed!
                    return func.sum(getattr(model, mapped_field))
        
        elif agg_func == AggregateFunction.AVG:
            if agg.field:
                mapped_field = self._map_column(agg.field)
                if hasattr(model, mapped_field):
                    # Mart tables have numeric columns - no casting needed!
                    return func.avg(getattr(model, mapped_field))
        
        elif agg_func == AggregateFunction.MIN:
            if agg.field:
                mapped_field = self._map_column(agg.field)
                if hasattr(model, mapped_field):
                    return func.min(getattr(model, mapped_field))
        
        elif agg_func == AggregateFunction.MAX:
            if agg.field:
                mapped_field = self._map_column(agg.field)
                if hasattr(model, mapped_field):
                    return func.max(getattr(model, mapped_field))
        
        logger.warning(f"Unknown or invalid aggregate: {agg_func}")
        return None
    
    def _serialize_results(
        self, 
        results: List, 
        fields: List[str]
    ) -> List[Dict[str, Any]]:
        """Serialize ORM results to dictionaries"""
        from sqlalchemy.inspection import inspect as sa_inspect
        
        serialized = []
        for result in results:
            if hasattr(result, '__dict__'):
                # Full model object
                data = {}
                mapper = sa_inspect(result.__class__)
                
                # Get column attributes from mapper - use attr.key for Python attribute name
                for attr in mapper.mapper.column_attrs:
                    attr_name = attr.key  # Python attribute name (e.g., 'id')
                    try:
                        value = getattr(result, attr_name)
                        # Convert dates/datetimes to strings
                        if isinstance(value, (date, datetime)):
                            value = value.isoformat()
                        data[attr_name] = value
                    except AttributeError:
                        # Skip attributes that don't exist on the object
                        continue
                
                serialized.append(data)
            else:
                # Tuple or individual values (partial selection)
                if hasattr(result, '_asdict'):
                    data = result._asdict()
                elif isinstance(result, tuple) and fields and fields != ["*"]:
                    data = {fields[i]: result[i] for i in range(min(len(result), len(fields)))}
                else:
                    data = {"value": result}
                
                # Convert dates/datetimes to strings
                for key, value in data.items():
                    if isinstance(value, (date, datetime)):
                        data[key] = value.isoformat()
                
                serialized.append(data)
        
        return serialized
    
    def _serialize_aggregate_results(
        self,
        results: List,
        params: QueryParameters
    ) -> List[Dict[str, Any]]:
        """Serialize aggregate query results"""
        
        serialized = []
        for result in results:
            data = {}
            
            # Add group by fields
            for i, field_name in enumerate(params.group_by):
                value = result[i]
                if isinstance(value, (date, datetime)):
                    value = value.isoformat()
                data[field_name] = value
            
            # Add aggregate values
            offset = len(params.group_by)
            for i, agg in enumerate(params.aggregates):
                value = result[offset + i]
                if isinstance(value, (date, datetime)):
                    value = value.isoformat()
                # Round numeric values for cleaner output
                if isinstance(value, float):
                    value = round(value, 2)
                data[agg.alias] = value
            
            serialized.append(data)
        
        return serialized
    
    def execute_with_price_increases(
        self,
        params: QueryParameters,
        session: Optional[Session] = None
    ) -> QueryResult:
        """
        Execute a query that includes price increase data.
        
        This joins mart__invoice_items with mart__price_increases to include
        percentage_increase, previous_price, and price_change data.
        """
        own_session = False
        try:
            if session is None:
                session = SessionLocal()
                own_session = True
            
            if not self.is_mart_available(session):
                return QueryResult(
                    success=False,
                    data=[],
                    count=0,
                    error="Mart tables not available",
                    query_info={"mart_available": False}
                )
            
            # Build query with join to price increases
            query = session.query(
                InvoiceItemMart,
                PriceIncreaseMart.percentage_increase,
                PriceIncreaseMart.previous_price,
                PriceIncreaseMart.price_change,
                PriceIncreaseMart.percentage_increase_formatted
            ).outerjoin(
                PriceIncreaseMart,
                InvoiceItemMart.id == PriceIncreaseMart.invoice_items_id
            )
            
            # Apply filters
            query = self._apply_filters(query, InvoiceItemMart, params.filters)
            
            # Apply sorting
            for sort in params.sort:
                query = self._apply_sort(query, InvoiceItemMart, sort)
            
            # Apply pagination
            if params.offset:
                query = query.offset(params.offset)
            if params.limit:
                query = query.limit(params.limit)
            
            # Execute
            results = query.all()
            
            # Serialize results with price data
            serialized = []
            for row in results:
                item = row[0]
                data = self._serialize_results([item], params.fields)[0]
                
                # Add price increase data
                data["percentage_increase"] = row[1]
                data["previous_price"] = row[2]
                data["price_change"] = row[3]
                data["percentage_increase_formatted"] = row[4]
                
                serialized.append(data)
            
            return QueryResult(
                success=True,
                data=serialized,
                count=len(serialized),
                query_info={
                    "table": "invoice_items_mart",
                    "source": "mart__invoice_items + mart__price_increases",
                    "filters_applied": len(params.filters)
                }
            )
            
        except Exception as e:
            logger.exception("Error executing price increase query")
            return QueryResult(
                success=False,
                data=[],
                count=0,
                error=str(e)
            )
        finally:
            if own_session and session:
                session.close()


# Global instance
_mart_executor: Optional[MartQueryExecutor] = None


def get_mart_executor() -> MartQueryExecutor:
    """Get or create MartQueryExecutor instance (singleton pattern)"""
    global _mart_executor
    if _mart_executor is None:
        _mart_executor = MartQueryExecutor()
        logger.info("Created global MartQueryExecutor instance")
    return _mart_executor

