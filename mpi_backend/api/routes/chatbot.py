"""
Chatbot API Routes for natural language database queries.
Enhanced with conversational intelligence and multi-turn context support.
"""

import logging
from fastapi import APIRouter, HTTPException, status

from mpi_backend.database.schemas.Chatbot import (
    QueryRequest,
    QueryResponse,
    AgentInfoResponse
)
from mpi_backend.database.controllers.ChatbotController import (
    get_chatbot_controller
)

logger = logging.getLogger(__name__)


# Create router
router = APIRouter(prefix="/qa", tags=["Chatbot"])


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Chat with AI Assistant",
    description="""
    Chat with the AI assistant for natural language database queries.
    Enhanced with conversational intelligence and multi-turn context support.

    **Features:**
    - Natural conversation support (greetings, help, small talk)
    - Converts natural language to SQL for database queries
    - Executes queries safely (SELECT only)
    - Returns natural language answers
    - Multi-agent support (Database, Excel, Email, Reports)

    **Safety:**
    - Only SELECT queries are allowed
    - SQL injection protection
    - Query result limiting
    - Input validation

    **Conversational Examples:**
    - "Hi, what can you do?"
    - "Help me understand how to use this"
    - "How are you today?"

    **Database Query Examples:**
    - "Show me all invoices from BMW Plumbing Supplies"
    - "What is the total amount of invoice items for customer job ABC123?"
    - "How many suppliers do we have?"
    - "Find all items with 'pipe' in the description from July 2024"

    **Session Context (Optional):**
    - Include session_id only if you need conversation context
    - Most queries work perfectly without session_id
    - Example: "Show me invoices from July" → "What about August?"
      (with session_id)
    """
)
async def chat(request: QueryRequest) -> QueryResponse:
    """
    Chat with the AI assistant.

    Args:
        request (QueryRequest): Query request with question and optional session_id

    Returns:
        QueryResponse: Response with answer and metadata

    Raises:
        HTTPException: If processing fails
    """
    try:
        logger.info(
            "Received chat request: %s... (session: %s)",
            request.question[:100],
            request.session_id or "default"
        )

        # Get controller and process query with session support
        controller = get_chatbot_controller()
        result = await controller.process_query(
            request.question,
            session_id=request.session_id,
            message_history=request.message_history
        )

        return result

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in query endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get(
    "/agents",
    response_model=AgentInfoResponse,
    summary="Get Agent Information",
    description="""
    Get information about registered AI agents and their capabilities.

    Returns details about:
    - Current mode (multi-agent or legacy)
    - List of registered agents
    - Agent capabilities
    - Usage statistics
    """
)
async def get_agents() -> AgentInfoResponse:
    """
    Get information about registered agents.

    Returns:
        AgentInfoResponse: Agent information and statistics

    Raises:
        HTTPException: If retrieval fails
    """
    try:
        logger.info("Fetching agent information")
        controller = get_chatbot_controller()
        return controller.get_agent_info()
    except Exception as e:
        logger.error(f"Error fetching agent info: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve agent information: {str(e)}"
        )
