"""
Chatbot System for MPI Backend
Natural language chatbot for database queries

Main Components:
- engine.py: Core engine (natural language -> SQL -> answer)
- conversation_manager.py: Handles greetings, help, context
- agents/: Multi-agent system (Database, Excel, Email, Report)
- prompts/: AI prompts and templates
- mart_query_executor.py: Optimized query executor for dbt mart tables

Query Execution:
- MartQueryExecutor: Queries pre-cleaned dbt mart tables (preferred)
- ORMQueryExecutor: Queries raw tables (fallback)
"""

# Lazy imports to avoid circular dependencies
def get_chatbot_engine():
    """Get or create the chatbot engine instance"""
    from .engine import get_chatbot_engine as _get_engine
    return _get_engine()


def get_mart_executor():
    """Get or create the mart query executor instance"""
    from .mart_query_executor import get_mart_executor as _get_mart
    return _get_mart()


def get_orm_executor():
    """Get or create the ORM query executor instance"""
    from .orm_query_executor import get_orm_executor as _get_orm
    return _get_orm()


__all__ = [
    'get_chatbot_engine',
    'get_mart_executor',
    'get_orm_executor'
]
