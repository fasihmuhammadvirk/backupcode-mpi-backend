"""
ORM Query Executor
Executes queries based on JSON parameters using SQLAlchemy ORM
"""

import logging
from typing import List, Dict, Any, Optional, Type
from datetime import date, datetime
from sqlalchemy import and_, or_, func, distinct, desc, asc
from sqlalchemy.orm import Session, Query
from sqlalchemy.inspection import inspect as sa_inspect

from mpi_backend.database import engine, SessionLocal
from mpi_backend.database.models import (
    Invoice, InvoiceItem, Supplier, ItemsMapping, 
    CustomerJobMapping, UnmappedItems, ItemClassification
)
from mpi_backend.utils.chatbot.query_schema import (
    QueryParameters, QueryResult, FilterCondition, 
    FilterOperator, AggregateFunction, TableName,
    JoinCondition, SortOrder
)

logger = logging.getLogger(__name__)


class ORMQueryExecutor:
    """
    Executes database queries using ORM based on JSON parameters
    Replaces raw SQL generation with structured ORM queries
    """
    
    # Table name to model mapping
    TABLE_MODELS: Dict[str, Type] = {
        TableName.INVOICES.value: Invoice,
        TableName.INVOICE_ITEMS.value: InvoiceItem,
        TableName.SUPPLIERS.value: Supplier,
        TableName.ITEMS_MAPPING.value: ItemsMapping,
        TableName.CUSTOMER_JOB_MAPPINGS.value: CustomerJobMapping,
        TableName.UNMAPPED_ITEMS.value: UnmappedItems,
        TableName.ITEM_CLASSIFICATION.value: ItemClassification,
    }
    
    def __init__(self):
        """Initialize the ORM query executor"""
        self.engine = engine
        logger.info("ORMQueryExecutor initialized")
    
    def execute_query(
        self, 
        params: QueryParameters,
        session: Optional[Session] = None
    ) -> QueryResult:
        """
        Execute a query based on JSON parameters
        
        Args:
            params: Query parameters
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
            
            # Get the model for the primary table
            model = self._get_model(params.table)
            
            # Detect and collect all relationship paths used
            relationship_paths = self._collect_relationship_paths(params)
            
            # Build the base query
            query = self._build_base_query(session, model, params)
            
            # Auto-join relationships that are referenced
            query = self._auto_join_relationships(query, model, relationship_paths)
            
            # Apply filters
            query = self._apply_filters(query, model, params.filters)
            
            # Apply OR filters if provided
            if params.or_filters:
                query = self._apply_or_filters(query, model, params.or_filters)
            
            # Apply manual joins
            for join in params.joins:
                query = self._apply_join(query, model, join)
            
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
                results = self._execute_aggregate_query(
                    session, model, params
                )
            else:
                # Handle regular queries
                logger.info("🚀 Executing regular query...")
                
                # Try to log the SQL
                try:
                    from sqlalchemy.dialects import postgresql
                    compiled = str(query.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
                    logger.info(f"🔧 Generated SQL:\n{compiled}")
                except Exception as e:
                    logger.debug(f"Could not compile SQL for logging: {e}")
                
                results = query.all()
                logger.info(f"📦 Query returned {len(results)} results")
                results = self._serialize_results(results, params.fields)
            
            return QueryResult(
                success=True,
                data=results,
                count=len(results),
                total_count=total_count,
                query_info={
                    "table": params.table,
                    "filters_applied": len(params.filters),
                    "joins_applied": len(params.joins),
                    "aggregates_applied": len(params.aggregates)
                }
            )
            
        except Exception as e:
            logger.error(f"Error executing query: {e}", exc_info=True)
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
        if table_name not in self.TABLE_MODELS:
            raise ValueError(f"Unknown table: {table_name}")
        return self.TABLE_MODELS[table_name]
    
    def _extract_all_relationship_paths(self, field: str) -> set:
        """
        Extract all intermediate relationship paths from a dotted field.
        
        For a field like "invoice.supplier_fk.supplier_name", returns:
        - {"invoice", "invoice.supplier_fk"}
        
        This ensures all intermediate tables are joined in the correct order.
        """
        paths = set()
        if '.' in field:
            parts = field.split('.')
            for i in range(len(parts) - 1):
                rel_path = '.'.join(parts[:i+1])
                paths.add(rel_path)
        return paths
    
    def _collect_relationship_paths(self, params: QueryParameters) -> set:
        """
        Collect all relationship paths used in the query.
        Returns a set of all relationship paths (including intermediate hops).
        
        Uses _extract_all_relationship_paths helper for consistency.
        """
        relationships = set()
        
        # Check fields
        for field in params.fields:
            relationships.update(self._extract_all_relationship_paths(field))
        
        # Check filters
        for filter_cond in params.filters:
            relationships.update(self._extract_all_relationship_paths(filter_cond.field))
        
        # Check OR filters
        if params.or_filters:
            for filter_group in params.or_filters:
                for filter_cond in filter_group:
                    relationships.update(self._extract_all_relationship_paths(filter_cond.field))
        
        # Check sort fields
        for sort in params.sort:
            relationships.update(self._extract_all_relationship_paths(sort.field))
        
        # Check group by fields
        for field in params.group_by:
            relationships.update(self._extract_all_relationship_paths(field))
        
        return relationships
    
    def _auto_join_relationships(self, query: Query, model: Type, relationship_names: set) -> Query:
        """
        Automatically join relationships that are referenced in the query.
        Supports nested relationships (e.g., "invoice.supplier_fk").
        """
        # Sort relationship paths by depth to ensure parent joins happen first
        sorted_paths = sorted(relationship_names, key=lambda x: x.count('.'))
        
        for rel_path in sorted_paths:
            try:
                # Handle nested relationships (e.g., "invoice.supplier_fk")
                if '.' in rel_path:
                    parts = rel_path.split('.')
                    current_model = model
                    
                    # Traverse the relationship path
                    for i, part in enumerate(parts):
                        if hasattr(current_model, part):
                            rel_attr = getattr(current_model, part)
                            
                            # Check if it's a relationship
                            if hasattr(rel_attr.property, 'mapper'):
                                related_model = rel_attr.property.mapper.class_
                                
                                # Add the join
                                query = query.join(related_model, rel_attr)
                                logger.info(f"Auto-joined relationship: {part} ({current_model.__name__} -> {related_model.__name__})")
                                
                                # Move to the next model in the chain
                                current_model = related_model
                            else:
                                logger.warning(f"Attribute {part} in {current_model.__name__} is not a relationship")
                                break
                        else:
                            logger.warning(f"Attribute {part} not found in {current_model.__name__}")
                            break
                
                # Handle simple single-level relationships
                else:
                    if hasattr(model, rel_path):
                        rel_attr = getattr(model, rel_path)
                        # Check if it's a relationship
                        if hasattr(rel_attr.property, 'mapper'):
                            # Get the related model
                            related_model = rel_attr.property.mapper.class_
                            # Add the join
                            query = query.join(related_model, rel_attr)
                            logger.info(f"Auto-joined relationship: {rel_path} -> {related_model.__name__}")
                    
            except Exception as e:
                logger.warning(f"Failed to auto-join relationship {rel_path}: {e}", exc_info=True)
        
        return query
    
    def _build_base_query(
        self, 
        session: Session, 
        model: Type, 
        params: QueryParameters
    ) -> Query:
        """Build the base query with field selection"""
        
        # Handle field selection
        if params.fields and params.fields != ["*"]:
            # Select specific fields
            columns = []
            for field in params.fields:
                # Handle relationship paths (e.g., "supplier_fk.supplier_name")
                if '.' in field:
                    try:
                        parts = field.split('.')
                        current_obj = model
                        for i, part in enumerate(parts):
                            if hasattr(current_obj, part):
                                attr = getattr(current_obj, part)
                                # If this is a relationship (not the last part), get the related model
                                if i < len(parts) - 1:
                                    if hasattr(attr.property, 'mapper'):
                                        current_obj = attr.property.mapper.class_
                                    else:
                                        current_obj = attr
                                else:
                                    current_obj = attr
                            else:
                                logger.warning(f"Relationship path {field} invalid")
                                current_obj = None
                                break
                        if current_obj is not None:
                            columns.append(current_obj.label(field.replace('.', '_')))
                    except Exception as e:
                        logger.warning(f"Error handling relationship field {field}: {e}")
                elif hasattr(model, field):
                    columns.append(getattr(model, field))
                else:
                    logger.warning(f"Field {field} not found in {model.__name__}")
            
            if columns:
                query = session.query(*columns)
            else:
                # Fallback to full model if no valid columns
                query = session.query(model)
        else:
            # Select all fields
            query = session.query(model)
        
        return query
    
    def _apply_filters(
        self, 
        query: Query, 
        model: Type, 
        filters: List[FilterCondition]
    ) -> Query:
        """Apply filter conditions to the query"""
        
        logger.info(f"=== APPLYING {len(filters)} FILTERS ===")
        conditions = []
        for idx, filter_cond in enumerate(filters, 1):
            logger.info(f"Filter {idx}: field={filter_cond.field}, operator={filter_cond.operator}, value={filter_cond.value}")
            condition = self._build_filter_condition(model, filter_cond)
            if condition is not None:
                logger.info(f"Filter {idx} built successfully: {condition}")
                conditions.append(condition)
            else:
                logger.warning(f"Filter {idx} returned None!")
        
        if conditions:
            logger.info(f"Applying {len(conditions)} conditions to query with AND")
            query = query.filter(and_(*conditions))
            logger.info(f"Filters applied successfully")
        else:
            logger.warning("No valid conditions to apply!")
        
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
    
    def _build_relationship_filter(
        self,
        model: Type,
        filter_cond: FilterCondition
    ):
        """
        Build a filter condition for relationship fields
        E.g., "supplier_fk.supplier_name" -> filter through relationship
        """
        parts = filter_cond.field.split('.')
        logger.info(f"🔍 Building relationship filter: {filter_cond.field} -> parts: {parts}")
        
        # Start with the model
        current_obj = model
        logger.info(f"📍 Starting with model: {model.__name__}")
        
        # Navigate through the relationship path
        for i, part in enumerate(parts):
            logger.info(f"📂 Step {i+1}/{len(parts)}: Looking for '{part}' in {current_obj.__name__ if hasattr(current_obj, '__name__') else type(current_obj)}")
            if not hasattr(current_obj, part):
                logger.warning(
                    f"❌ Relationship path {filter_cond.field} invalid: "
                    f"{part} not found in {current_obj.__name__ if hasattr(current_obj, '__name__') else current_obj}"
                )
                return None
            
            attr = getattr(current_obj, part)
            logger.info(f"✓ Found attribute: {attr}")
            
            # If this is a relationship (not the last part), get the related model
            if i < len(parts) - 1:
                # Check if this is a relationship property
                if hasattr(attr.property, 'mapper'):
                    # This is a relationship, get the related model class
                    current_obj = attr.property.mapper.class_
                    logger.info(f"🔗 '{part}' is a RELATIONSHIP to: {current_obj.__name__}")
                else:
                    # Not a relationship, just continue
                    current_obj = attr
                    logger.info(f"📝 '{part}' is NOT a relationship")
            else:
                # This is the final field
                current_obj = attr
                logger.info(f"🎯 FINAL FIELD: {current_obj}")
        
        # Now current_obj is the final field, apply the operator
        operator = filter_cond.operator
        value = filter_cond.value
        logger.info(f"⚙️  Applying operator: {operator} with value: '{value}'")
        
        # Build condition based on operator
        if operator == FilterOperator.EQUALS:
            return current_obj == value
        elif operator == FilterOperator.NOT_EQUALS:
            return current_obj != value
        elif operator == FilterOperator.GREATER_THAN:
            return current_obj > value
        elif operator == FilterOperator.GREATER_THAN_OR_EQUAL:
            return current_obj >= value
        elif operator == FilterOperator.LESS_THAN:
            return current_obj < value
        elif operator == FilterOperator.LESS_THAN_OR_EQUAL:
            return current_obj <= value
        elif operator == FilterOperator.IN:
            if isinstance(value, list):
                return current_obj.in_(value)
            return None
        elif operator == FilterOperator.NOT_IN:
            if isinstance(value, list):
                return ~current_obj.in_(value)
            return None
        elif operator == FilterOperator.LIKE:
            return current_obj.like(f"%{value}%")
        elif operator == FilterOperator.ILIKE:
            return current_obj.ilike(f"%{value}%")
        elif operator == FilterOperator.CONTAINS:
            return current_obj.contains(value)
        elif operator == FilterOperator.STARTS_WITH:
            return current_obj.startswith(value)
        elif operator == FilterOperator.ENDS_WITH:
            return current_obj.endswith(value)
        elif operator == FilterOperator.IS_NULL:
            return current_obj.is_(None)
        elif operator == FilterOperator.IS_NOT_NULL:
            return current_obj.isnot(None)
        elif operator == FilterOperator.BETWEEN:
            if isinstance(value, list) and len(value) == 2:
                return current_obj.between(value[0], value[1])
            return None
        else:
            logger.warning(f"Unknown operator in relationship filter: {operator}")
            return None
    
    def _build_filter_condition(
        self, 
        model: Type, 
        filter_cond: FilterCondition
    ):
        """Build a single filter condition"""
        
        # Handle relationship paths (e.g., "supplier_fk.supplier_name")
        if '.' in filter_cond.field:
            logger.info(f"Detected relationship path in filter: {filter_cond.field}")
            return self._build_relationship_filter(model, filter_cond)
        
        if not hasattr(model, filter_cond.field):
            logger.warning(
                f"Field {filter_cond.field} not found in {model.__name__}"
            )
            return None
        
        field = getattr(model, filter_cond.field)
        operator = filter_cond.operator
        value = filter_cond.value
        logger.info(f"Building direct field filter: {model.__name__}.{filter_cond.field} {operator} {value}")
        
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
            else:
                logger.warning(f"IN operator requires list value, got {type(value)}")
                return None
        elif operator == FilterOperator.NOT_IN:
            if isinstance(value, list):
                return ~field.in_(value)
            else:
                logger.warning(f"NOT_IN operator requires list value")
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
            else:
                logger.warning(f"BETWEEN operator requires list of 2 values")
                return None
        else:
            logger.warning(f"Unknown operator: {operator}")
            return None
    
    def _apply_join(
        self, 
        query: Query, 
        model: Type, 
        join: JoinCondition
    ) -> Query:
        """Apply join condition to the query"""
        
        # Get the joined model
        join_model = self._get_model(join.table)
        
        # Build join condition
        if not hasattr(model, join.on_field):
            logger.warning(f"Field {join.on_field} not found in {model.__name__}")
            return query
        
        if not hasattr(join_model, join.join_field):
            logger.warning(
                f"Field {join.join_field} not found in {join_model.__name__}"
            )
            return query
        
        on_field = getattr(model, join.on_field)
        join_field = getattr(join_model, join.join_field)
        
        # Apply join based on type
        if join.join_type == "inner":
            query = query.join(join_model, on_field == join_field)
        elif join.join_type == "left":
            query = query.outerjoin(join_model, on_field == join_field)
        else:
            logger.warning(f"Join type {join.join_type} not fully supported, using inner join")
            query = query.join(join_model, on_field == join_field)
        
        return query
    
    def _apply_sort(
        self, 
        query: Query, 
        model: Type, 
        sort_cond
    ) -> Query:
        """Apply sort condition to the query"""
        
        # Handle relationship paths
        if '.' in sort_cond.field:
            try:
                parts = sort_cond.field.split('.')
                current_obj = model
                for i, part in enumerate(parts):
                    if hasattr(current_obj, part):
                        attr = getattr(current_obj, part)
                        # If this is a relationship (not the last part), get the related model
                        if i < len(parts) - 1:
                            if hasattr(attr.property, 'mapper'):
                                current_obj = attr.property.mapper.class_
                            else:
                                current_obj = attr
                        else:
                            current_obj = attr
                    else:
                        logger.warning(f"Relationship path {sort_cond.field} invalid for sorting")
                        return query
                field = current_obj
            except Exception as e:
                logger.warning(f"Error handling relationship sort field {sort_cond.field}: {e}")
                return query
        else:
            if not hasattr(model, sort_cond.field):
                logger.warning(f"Field {sort_cond.field} not found in {model.__name__}")
                return query
            field = getattr(model, sort_cond.field)
        
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
        """Execute an aggregate query"""
        
        # Build aggregate expressions
        aggregate_exprs = []
        for agg in params.aggregates:
            expr = self._build_aggregate_expression(model, agg)
            if expr is not None:
                aggregate_exprs.append(expr.label(agg.alias))
        
        if not aggregate_exprs:
            raise ValueError("No valid aggregate expressions")
        
        # Detect relationships in group_by fields and filters using shared helper
        relationship_paths = set()
        for field in params.group_by:
            relationship_paths.update(self._extract_all_relationship_paths(field))
        
        # Also check filters for nested relationships
        for filter_cond in params.filters:
            relationship_paths.update(self._extract_all_relationship_paths(filter_cond.field))
        
        # Build group by fields
        group_by_fields = []
        for field_name in params.group_by:
            # Handle relationship paths
            if '.' in field_name:
                try:
                    parts = field_name.split('.')
                    current_obj = model
                    for i, part in enumerate(parts):
                        if hasattr(current_obj, part):
                            attr = getattr(current_obj, part)
                            # If this is a relationship (not the last part), get the related model
                            if i < len(parts) - 1:
                                if hasattr(attr.property, 'mapper'):
                                    current_obj = attr.property.mapper.class_
                                else:
                                    current_obj = attr
                            else:
                                current_obj = attr
                        else:
                            logger.warning(f"Relationship path {field_name} invalid for group_by")
                            current_obj = None
                            break
                    if current_obj is not None:
                        group_by_fields.append(current_obj.label(field_name.replace('.', '_')))
                except Exception as e:
                    logger.warning(f"Error handling relationship group_by field {field_name}: {e}")
            elif hasattr(model, field_name):
                group_by_fields.append(getattr(model, field_name))
        
        # Build query
        if group_by_fields:
            query = session.query(*group_by_fields, *aggregate_exprs)
        else:
            query = session.query(*aggregate_exprs)
        
        # Auto-join relationships
        query = self._auto_join_relationships(query, model, relationship_paths)
        
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
            # Handle relationship paths
            if '.' in sort.field:
                try:
                    parts = sort.field.split('.')
                    current_obj = model
                    for i, part in enumerate(parts):
                        if hasattr(current_obj, part):
                            attr = getattr(current_obj, part)
                            # If this is a relationship (not the last part), get the related model
                            if i < len(parts) - 1:
                                if hasattr(attr.property, 'mapper'):
                                    current_obj = attr.property.mapper.class_
                                else:
                                    current_obj = attr
                            else:
                                current_obj = attr
                        else:
                            logger.warning(f"Relationship path {sort.field} invalid for sorting in aggregate")
                            current_obj = None
                            break
                    if current_obj is not None:
                        if sort.order == SortOrder.DESC:
                            query = query.order_by(desc(current_obj))
                        else:
                            query = query.order_by(asc(current_obj))
                except Exception as e:
                    logger.warning(f"Error handling relationship sort field {sort.field} in aggregate: {e}")
            elif hasattr(model, sort.field):
                field = getattr(model, sort.field)
                if sort.order == SortOrder.DESC:
                    query = query.order_by(desc(field))
                else:
                    query = query.order_by(asc(field))
        
        # Apply pagination
        if params.offset:
            query = query.offset(params.offset)
        if params.limit:
            query = query.limit(params.limit)
        
        logger.info(f"Executing aggregate query: {query}")
        
        # Execute and serialize
        results = query.all()
        return self._serialize_aggregate_results(results, params)
    
    def _build_aggregate_expression(self, model: Type, agg):
        """Build an aggregate expression with special handling for amount column"""
        from sqlalchemy import cast, Float, and_
        from sqlalchemy.sql import case
        
        agg_func = agg.function
        
        if agg_func == AggregateFunction.COUNT:
            if agg.field:
                if hasattr(model, agg.field):
                    return func.count(getattr(model, agg.field))
            else:
                return func.count()
        
        elif agg_func == AggregateFunction.COUNT_DISTINCT:
            if agg.field and hasattr(model, agg.field):
                return func.count(distinct(getattr(model, agg.field)))
        
        elif agg_func == AggregateFunction.SUM:
            if agg.field and hasattr(model, agg.field):
                field_attr = getattr(model, agg.field)
                
                # Special handling for InvoiceItem.amount column
                # Amount is stored as string and needs casting with validation
                if model.__name__ == 'InvoiceItem' and agg.field == 'amount':
                    # Apply the same complex casting logic as get_aggregates
                    calculated_amount_case = case(
                        (
                            and_(
                                field_attr.isnot(None),
                                field_attr != '',
                                # Validation - amount should be reasonable length
                                func.length(field_attr) < 100,
                                func.length(field_attr) > 0,
                                # Filter out malformed strings containing non-numeric text
                                ~field_attr.like('%Merchandise%'),
                                ~field_attr.like('%Freight%'),
                                ~field_attr.like('%MiscCharges%'),
                                ~field_attr.like('%SubTotal%'),
                                ~field_attr.like('%Taxable%'),
                                ~field_attr.like('%Tax(%'),
                                ~field_attr.like('%Tax)%'),
                                # Ensure string can be converted to numeric
                                func.replace(field_attr, ',', '').regexp_match('^-?[0-9]*\\.?[0-9]+$')
                            ),
                            cast(func.replace(field_attr, ',', ''), Float)
                        ),
                        else_=0.0
                    )
                    return func.sum(calculated_amount_case)
                else:
                    # Standard sum for other fields
                    return func.sum(field_attr)
        
        elif agg_func == AggregateFunction.AVG:
            if agg.field and hasattr(model, agg.field):
                field_attr = getattr(model, agg.field)
                
                # Special handling for InvoiceItem.amount column
                if model.__name__ == 'InvoiceItem' and agg.field == 'amount':
                    calculated_amount_case = case(
                        (
                            and_(
                                field_attr.isnot(None),
                                field_attr != '',
                                func.length(field_attr) < 100,
                                func.length(field_attr) > 0,
                                ~field_attr.like('%Merchandise%'),
                                ~field_attr.like('%Freight%'),
                                ~field_attr.like('%MiscCharges%'),
                                ~field_attr.like('%SubTotal%'),
                                ~field_attr.like('%Taxable%'),
                                ~field_attr.like('%Tax(%'),
                                ~field_attr.like('%Tax)%'),
                                func.replace(field_attr, ',', '').regexp_match('^-?[0-9]*\\.?[0-9]+$')
                            ),
                            cast(func.replace(field_attr, ',', ''), Float)
                        ),
                        else_=0.0
                    )
                    return func.avg(calculated_amount_case)
                else:
                    return func.avg(field_attr)
        
        elif agg_func == AggregateFunction.MIN:
            if agg.field and hasattr(model, agg.field):
                return func.min(getattr(model, agg.field))
        
        elif agg_func == AggregateFunction.MAX:
            if agg.field and hasattr(model, agg.field):
                return func.max(getattr(model, agg.field))
        
        logger.warning(f"Unknown or invalid aggregate: {agg_func}")
        return None
    
    def _serialize_results(
        self, 
        results: List, 
        fields: List[str]
    ) -> List[Dict[str, Any]]:
        """Serialize ORM results to dictionaries"""
        
        serialized = []
        for result in results:
            if hasattr(result, '__dict__'):
                # Full model object
                data = {}
                mapper = sa_inspect(result.__class__)
                for column in mapper.columns:
                    value = getattr(result, column.name)
                    # Convert dates/datetimes to strings
                    if isinstance(value, (date, datetime)):
                        value = value.isoformat()
                    data[column.name] = value
                serialized.append(data)
            else:
                # Tuple or individual values (partial selection)
                if hasattr(result, '_asdict'):
                    # Named tuple
                    data = result._asdict()
                elif isinstance(result, tuple) and fields and fields != ["*"]:
                    # Regular tuple with known fields
                    data = {fields[i]: result[i] for i in range(len(result))}
                else:
                    # Single value
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
                data[agg.alias] = value
            
            serialized.append(data)
        
        return serialized


# Global instance
_orm_executor: Optional[ORMQueryExecutor] = None


def get_orm_executor() -> ORMQueryExecutor:
    """Get or create ORM executor instance (singleton pattern)"""
    global _orm_executor
    if _orm_executor is None:
        _orm_executor = ORMQueryExecutor()
        logger.info("Created global ORMQueryExecutor instance")
    return _orm_executor

