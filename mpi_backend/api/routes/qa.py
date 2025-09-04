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

        return QueryResponse(
            answer=result["answer"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in query endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )