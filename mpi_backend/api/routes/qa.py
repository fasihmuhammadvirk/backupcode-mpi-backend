"""
Q/A API Routes for natural language database queries
Production-ready version with essential endpoints only
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from mpi_backend.database.controllers.QAController import get_qa_controller

logger = logging.getLogger(__name__)


# Create router
router = APIRouter(prefix="/qa", tags=["Q/A System"])


# Request/Response models
class QueryRequest(BaseModel):
    """Request model for natural language queries"""
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Natural language question about the database",
        example="Show me all invoices from BMW Plumbing Supplies in July"
    )


class QueryResponse(BaseModel):
    """Response model for query results"""
    answer: str = Field(
        ..., description="Natural language answer to the question"
    )
    sql_query: Optional[str] = Field(
        None,
        description="SQL query that was executed"
    )
    raw_results: Optional[str] = Field(
        None,
        description="Raw query results summary"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if any"
    )


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Process Natural Language Query",
    description="""
    Process a natural language question about the MPI backend database.
    
    **Features:**
    - Converts natural language to SQL
    - Executes query safely (SELECT only)
    - Returns natural language answer only
    
    **Safety:**
    - Only SELECT queries are allowed
    - SQL injection protection
    - Query result limiting
    - Input validation
    
    **Example Questions:**
    - "Show me all invoices from BMW Plumbing Supplies"
    - "What is the total amount of invoice items for customer job ABC123?"
    - "How many suppliers do we have?"
    - "Find all items with 'pipe' in the description from July 2024"
    """
)
async def query_database(request: QueryRequest) -> QueryResponse:
    """Process a natural language database query"""
    try:
        logger.info(
            "Received query request: %s...", request.question[:100]
        )

        # Get controller and process query
        controller = get_qa_controller()
        result = await controller.process_query(request.question)

        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in query endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get(
    "/health",
    summary="QA System Health Check",
    description="Check the health status of the Q/A system"
)
async def qa_health_check():
    """Check Q/A system health"""
    try:
        controller = get_qa_controller()
        info = controller.get_system_info()
        
        return {
            "status": info["status"],
            "llm_model": info.get("llm_model", "unknown"),
            "available_tables": len(info.get("available_tables", [])),
            "llm_status": info.get("llm_status", {})
        }
    except Exception as e:
        logger.error(f"QA health check failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.get(
    "/examples",
    summary="Get Query Examples",
    description="Get example questions and usage tips for the Q/A system"
)
async def get_examples():
    """Get example questions and tips"""
    return {
        "examples": [
            "Show me all invoices from BMW Plumbing Supplies",
            "What is the total amount of invoice items for customer job ABC123?",
            "How many suppliers do we have?",
            "Find all items with 'pipe' in the description from July 2024",
            "Show me invoices from the last 30 days",
            "What are the most expensive items this month?",
            "Find all items for customer job 'Office Building Project'",
            "Show me all suppliers and their invoice counts"
        ],
        "tips": [
            "Be specific about time periods (e.g., 'last month', 'July 2024')",
            "Mention supplier names for supplier-specific queries",
            "Use customer job names for project-specific searches",
            "Ask for totals, counts, or specific item details",
            "Use descriptive terms for item searches"
        ],
        "limitations": [
            "Only SELECT queries are allowed for safety",
            "Complex joins may take longer to process",
            "Large result sets are automatically limited",
            "Some technical database details are hidden for security"
        ]
    }


@router.post(
    "/debug-query",
    summary="Debug Query Processing",
    description="Process a query with detailed debug information"
)
async def debug_query(request: QueryRequest):
    """Process a query with debug information"""
    try:
        logger.info("Received debug query request: %s...", request.question[:100])
        
        controller = get_qa_controller()
        result = await controller.process_debug_query(request.question)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in debug endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get(
    "/system-info",
    summary="Get System Information",
    description="Get detailed system information for debugging"
)
async def get_system_info():
    """Get detailed system information"""
    try:
        controller = get_qa_controller()
        return controller.get_system_info()
    except Exception as e:
        logger.error(f"Failed to get system info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get system info: {str(e)}"
        )