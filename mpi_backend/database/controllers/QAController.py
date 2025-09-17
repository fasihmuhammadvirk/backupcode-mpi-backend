"""
QA Controller for managing natural language database queries
Production-ready version with essential functionality only
"""

import logging
from typing import Dict, Any
from fastapi import HTTPException
from mpi_backend.utils.database_qa_agent import get_qa_agent

logger = logging.getLogger(__name__)


class QAController:
    """Controller for handling Q/A operations"""

    def __init__(self):
        """Initialize QA Controller"""
        self.qa_agent = None

    def _get_qa_agent(self):
        """Get QA agent instance with lazy loading"""
        if self.qa_agent is None:
            try:
                self.qa_agent = get_qa_agent()
                logger.info("QA Agent initialized successfully")
            except Exception as e:
                logger.error("Failed to initialize QA Agent: %s", e)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to initialize QA system: {str(e)}"
                )
        return self.qa_agent

    async def process_query(self, question: str) -> Dict[str, Any]:
        """
        Process a natural language question and return answer

        Args:
            question (str): Natural language question about the database

        Returns:
            Dict containing answer, sql_query, raw_results, and any errors

        Raises:
            HTTPException: If question is invalid or processing fails
        """
        try:
            # Validate input
            if not question or not isinstance(question, str):
                raise HTTPException(
                    status_code=400,
                    detail="Question must be a non-empty string"
                )
            
            question = question.strip()
            if len(question) < 3:
                raise HTTPException(
                    status_code=400,
                    detail="Question must be at least 3 characters long"
                )
            
            if len(question) > 1000:
                raise HTTPException(
                    status_code=400,
                    detail="Question must be less than 1000 characters"
                )
            
            logger.info("Processing query: %s...", question[:100])

            # Get QA agent and process question
            qa_agent = self._get_qa_agent()
            result = await qa_agent.query(question)

            logger.info("Query processed successfully")
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process query: {str(e)}"
            )

    async def process_debug_query(self, question: str) -> Dict[str, Any]:
        """
        Process a natural language question and return debug information

        Args:
            question (str): Natural language question about the database

        Returns:
            Dict containing answer, sql_query, raw_results, debug_info, and any errors

        Raises:
            HTTPException: If question is invalid or processing fails
        """
        try:
            # Validate input
            if not question or not isinstance(question, str):
                raise HTTPException(
                    status_code=400,
                    detail="Question must be a non-empty string"
                )
            
            question = question.strip()
            if len(question) < 3:
                raise HTTPException(
                    status_code=400,
                    detail="Question must be at least 3 characters long"
                )
            
            if len(question) > 1000:
                raise HTTPException(
                    status_code=400,
                    detail="Question must be less than 1000 characters"
                )
            
            logger.info("Processing debug query: %s...", question[:100])

            # Get QA agent and process question with debug info
            qa_agent = self._get_qa_agent()
            result = await qa_agent.debug_query(question)

            logger.info("Debug query processed successfully")
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing debug query: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process debug query: {str(e)}"
            )

    def get_system_info(self) -> Dict[str, Any]:
        """
        Get system information for debugging and monitoring

        Returns:
            Dict containing system information including available tables
        """
        try:
            qa_agent = self._get_qa_agent()
            
            # Get table information
            table_names = qa_agent._get_table_names()
            table_info = qa_agent._get_enhanced_table_info()
            
            return {
                "status": "active",
                "available_tables": table_names,
                "table_info": table_info,
                "llm_model": "gemini-pro",
                "llm_status": {
                    "primary_llm": "available" if qa_agent.primary_llm else "unavailable",
                    "fallback_llm": "available" if qa_agent.fallback_llm else "unavailable"
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting system info: {e}")
            return {
                "status": "error",
                "error": str(e),
                "available_tables": [],
                "table_info": {},
                "llm_status": {
                    "primary_llm": "unavailable",
                    "fallback_llm": "unavailable"
                }
            }


# Global controller instance
_qa_controller = None


def get_qa_controller() -> QAController:
    """Get or create QA Controller instance (singleton pattern)"""
    global _qa_controller
    if _qa_controller is None:
        _qa_controller = QAController()
    return _qa_controller