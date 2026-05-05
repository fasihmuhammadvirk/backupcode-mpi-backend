"""
Chatbot Controller for managing natural language database queries.
Supports multi-agent architecture (Database, Excel, Email, Report, etc.)
"""

import logging
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from mpi_backend.database.schemas.Chatbot import (
    QueryResponse,
    AgentInfoResponse,
    AgentInfo,
    AgentStats,
    ChatMessage
)

logger = logging.getLogger(__name__)


# Configuration flag for multi-agent system
USE_MULTI_AGENT = True


class ChatbotController:
    """
    Controller for handling AI-powered chatbot operations.

    Supports multi-agent architecture:
    - Database queries (Database Agent)
    - Excel generation (Excel Agent)
    - Email sending (Email Agent)
    - Report generation (Report Agent)
    """

    def __init__(self, db: Session = None):
        """
        Initialize Chatbot Controller.

        Args:
            db (Session, optional): Database session for query operations
        """
        self.db = db
        self._agent_manager = None
        self._chatbot_engine = None

    def _get_agent_manager(self):
        """
        Get agent manager for multi-agent support.
        Lazy initialization pattern for performance.

        Returns:
            AgentManager: Initialized agent manager instance

        Raises:
            Exception: If agent manager initialization fails
        """
        if self._agent_manager is None:
            try:
                from mpi_backend.utils.chatbot.agents import (
                    get_initialized_manager
                )
                self._agent_manager = get_initialized_manager()
                agent_count = len(self._agent_manager.list_agents())
                logger.info(
                    f"Agent Manager initialized with {agent_count} agents"
                )
            except Exception as e:
                logger.error(f"Failed to initialize Agent Manager: {e}")
                raise Exception(
                    f"Failed to initialize AI system: {str(e)}"
                ) from e
        return self._agent_manager

    def _get_chatbot_engine(self):
        """
        Get chatbot engine for legacy mode.
        Lazy initialization pattern for performance.

        Returns:
            ChatbotEngine: Initialized chatbot engine instance

        Raises:
            Exception: If chatbot engine initialization fails
        """
        if self._chatbot_engine is None:
            try:
                from mpi_backend.utils.chatbot import get_chatbot_engine
                self._chatbot_engine = get_chatbot_engine()
                logger.info("Chatbot Engine initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Chatbot Engine: {e}")
                raise Exception(
                    f"Failed to initialize chatbot system: {str(e)}"
                ) from e
        return self._chatbot_engine

    async def process_query(
        self,
        question: str,
        session_id: Optional[str] = None,
        message_history: Optional[List[ChatMessage]] = None
    ) -> QueryResponse:
        """
        Process a natural language question and return answer.
        Enhanced with conversational intelligence and session management.

        Args:
            question (str): Natural language question about the database
            session_id (Optional[str]): Session ID for context tracking
            message_history (Optional[list]): List of previous messages for context

        Returns:
            QueryResponse: Response containing answer and metadata

        Raises:
            ValueError: If question is invalid
            Exception: If processing fails
        """
        try:
            # Validate input
            self._validate_question(question)

            question = question.strip()
            logger.info(f"Processing query: {question[:100]}...")
            if message_history:
                logger.info(f"Received {len(message_history)} messages in history")

            # Use multi-agent system or legacy single-agent
            if USE_MULTI_AGENT:
                result = await self._process_with_agents(
                    question, session_id, message_history
                )
            else:
                result = await self._process_legacy(question, session_id)

            return QueryResponse(**result)

        except ValueError as e:
            logger.error(f"Validation error in process_query: {e}")
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error in process_query: {e}",
                exc_info=True
            )
            raise Exception(f"Internal server error: {str(e)}") from e

    def _validate_question(self, question: str) -> None:
        """
        Validate the input question.

        Args:
            question (str): Question to validate

        Raises:
            ValueError: If question is invalid
        """
        if not question or not isinstance(question, str):
            raise ValueError("Question must be a non-empty string")

        if len(question.strip()) < 1:
            raise ValueError("Question cannot be empty")

        if len(question) > 1000:
            raise ValueError("Question must be less than 1000 characters")

    async def _process_with_agents(
        self,
        question: str,
        session_id: Optional[str],
        message_history: Optional[List[ChatMessage]] = None
    ) -> Dict[str, Any]:
        """
        Process request using multi-agent system.

        Args:
            question (str): Natural language question
            session_id (Optional[str]): Session ID for context
            message_history (Optional[List[ChatMessage]]): List of previous messages

        Returns:
            Dict[str, Any]: Processed response data
        """
        manager = self._get_agent_manager()
        result = await manager.process_request(
            question=question,
            session_id=session_id,
            context={},
            message_history=message_history
        )

        # Transform agent response to controller format
        if result["success"]:
            return self._format_success_response(result)
        else:
            return self._format_error_response(result)

    def _format_success_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format successful agent response.

        Args:
            result (Dict[str, Any]): Raw agent result

        Returns:
            Dict[str, Any]: Formatted response
        """
        response_data = result.get("data", {})

        # For QA agent responses
        if isinstance(response_data, dict) and "answer" in response_data:
            formatted_response = {
                "answer": response_data.get("answer", "No answer available"),
                "error": None,
                "intent": response_data.get("intent"),
                "is_conversational": response_data.get(
                    "is_conversational",
                    False
                ),
                "metadata": result.get("metadata", {})
            }
            
            # Include download URL if present (for export responses)
            if "download_url" in response_data:
                formatted_response["metadata"]["download_url"] = response_data["download_url"]
                formatted_response["metadata"]["filename"] = response_data.get("filename")
                formatted_response["metadata"]["record_count"] = response_data.get("record_count")
                formatted_response["metadata"]["file_format"] = response_data.get("file_format")
            
            # Include emails if present (for email responses)
            # Check both response_data and metadata from result
            emails = None
            if "emails" in response_data:
                emails = response_data["emails"]
            elif "email" in response_data:
                # Single email response
                emails = [{
                    "supplier": response_data.get("supplier", "Unknown"),
                    "content": response_data.get("email", ""),
                    "item_count": response_data.get("item_count", 0)
                }]
            elif "emails" in result.get("metadata", {}):
                # Emails might be in metadata from agent
                emails = result.get("metadata", {}).get("emails")
            
            if emails:
                formatted_response["metadata"]["emails"] = emails
            
            return formatted_response

        # For other agent responses
        else:
            answer = (
                str(response_data)
                if response_data
                else "Request processed successfully"
            )
            return {
                "answer": answer,
                "error": None,
                "intent": result.get("metadata", {}).get("intent"),
                "is_conversational": False,
                "metadata": result.get("metadata", {})
            }

    def _format_error_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format error agent response.

        Args:
            result (Dict[str, Any]): Raw agent result with error

        Returns:
            Dict[str, Any]: Formatted error response
        """
        error_msg = result.get("error", "Unknown error occurred")
        return {
            "answer": f"Sorry, I couldn't process that request. {error_msg}",
            "error": error_msg,
            "intent": result.get("metadata", {}).get("intent"),
            "is_conversational": True,
            "metadata": result.get("metadata", {})
        }

    async def _process_legacy(
        self,
        question: str,
        session_id: Optional[str]
    ) -> Dict[str, Any]:
        """
        Process request using legacy chatbot engine.

        Args:
            question (str): Natural language question
            session_id (Optional[str]): Session ID for context

        Returns:
            Dict[str, Any]: Processed response data
        """
        engine = self._get_chatbot_engine()
        effective_session_id = session_id or "default"
        result = await engine.query(question, session_id=effective_session_id)

        return {
            "answer": result.get("answer", "No answer available"),
            "error": result.get("error"),
            "intent": result.get("intent"),
            "is_conversational": result.get("is_conversational", False),
            "formatting": result.get("formatting", {}),
            "metadata": {}
        }

    def get_agent_info(self) -> AgentInfoResponse:
        """
        Get information about registered agents.

        Returns:
            AgentInfoResponse: Agent information and statistics
        """
        if USE_MULTI_AGENT:
            try:
                manager = self._get_agent_manager()
                agents_data = manager.list_agents()
                stats_data = manager.get_stats()

                # Convert to proper schema models
                agents = [
                    AgentInfo(**agent) if isinstance(agent, dict) else agent
                    for agent in agents_data
                ]
                stats = (
                    AgentStats(**stats_data)
                    if isinstance(stats_data, dict)
                    else stats_data
                )

                return AgentInfoResponse(
                    mode="multi_agent",
                    agents=agents,
                    stats=stats
                )
            except Exception as e:
                logger.error(f"Error getting agent info: {e}")
                return AgentInfoResponse(
                    mode="multi_agent",
                    agents=[],
                    error=str(e)
                )
        else:
            # Legacy mode agent info
            agent = AgentInfo(
                name="qa_agent",
                capabilities=["query_database"],
                description="Legacy QA agent for database queries"
            )
            return AgentInfoResponse(
                mode="legacy",
                agents=[agent]
            )

    def enable_multi_agent(self) -> None:
        """Enable multi-agent mode."""
        global USE_MULTI_AGENT
        USE_MULTI_AGENT = True
        logger.info("Multi-agent mode enabled")

    def disable_multi_agent(self) -> None:
        """Disable multi-agent mode (use legacy)."""
        global USE_MULTI_AGENT
        USE_MULTI_AGENT = False
        logger.info("Multi-agent mode disabled, using legacy mode")


# Global controller instance
_chatbot_controller: Optional[ChatbotController] = None


def get_chatbot_controller() -> ChatbotController:
    """
    Get or create Chatbot Controller instance (singleton pattern).

    Returns:
        ChatbotController: Singleton controller instance
    """
    global _chatbot_controller
    if _chatbot_controller is None:
        _chatbot_controller = ChatbotController()
    return _chatbot_controller
