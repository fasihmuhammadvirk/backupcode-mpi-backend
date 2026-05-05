"""
Database Agent
Handles natural language database queries using JSON-based ORM queries
"""

from typing import Dict, Any, List, Optional
import logging
import json
from .base_agent import BaseAgent, AgentCapability, AgentPriority
from .intent_router import RequestIntent

logger = logging.getLogger(__name__)


class DatabaseAgent(BaseAgent):
    """
    Agent for handling natural language database queries
    Uses JSON-based query parameters and ORM execution instead of raw SQL
    
    Now uses dbt mart tables for optimized queries:
    - analytics.mart__invoice_items (pre-cleaned, numeric columns)
    - analytics.mart__price_increases (price change analysis)
    - analytics.mart__address_sheet_aggregates (pre-aggregated data)
    """
    
    def __init__(self):
        """Initialize Database Agent"""
        super().__init__(
            agent_name="database_agent",
            priority=AgentPriority.HIGH
        )
        self._llm_instance = None
        self._mart_executor = None  # Use mart executor for optimized queries
        self._prompt_loader = None
        self._use_json_query_mode = True  # Flag to use new JSON-based mode
    
    def _get_llm_instance(self):
        """Lazy load the LLM instance"""
        if self._llm_instance is None:
            import os
            from langchain_google_genai import ChatGoogleGenerativeAI
            from langchain_openai import ChatOpenAI
            
            # Try Gemini first
            try:
                api_key = os.getenv("GOOGLE_CHATBOT_API_KEY")
                if api_key:
                    self._llm_instance = ChatGoogleGenerativeAI(
                        model="gemini-2.5-flash",
                        google_api_key=api_key,
                        temperature=0,
                        convert_system_message_to_human=True
                    )
                    logger.info("Database Agent using Gemini 2.5 Flash")
                    return self._llm_instance
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini: {e}")
            
            # Fallback to OpenAI
            try:
                openai_key = os.getenv("OPENAI_API_KEY")
                if openai_key:
                    self._llm_instance = ChatOpenAI(
                        model="gpt-4o-mini",
                        api_key=openai_key,
                        temperature=0,
                        max_tokens=4000
                    )
                    logger.info("Database Agent using OpenAI GPT-4o mini")
                    return self._llm_instance
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI: {e}")
            
            raise ValueError("No LLM available for Database Agent")
        
        return self._llm_instance
    
    def _get_mart_executor(self):
        """Lazy load the Mart executor instance for chatbot queries"""
        if self._mart_executor is None:
            from mpi_backend.utils.chatbot.mart_query_executor import get_mart_executor
            self._mart_executor = get_mart_executor()
        return self._mart_executor
    
    def _get_prompt_loader(self):
        """Lazy load the prompt loader instance"""
        if self._prompt_loader is None:
            from mpi_backend.utils.chatbot.prompts import get_prompt_loader
            self._prompt_loader = get_prompt_loader()
        return self._prompt_loader
    
    def can_handle(self, request: Dict[str, Any]) -> bool:
        """
        Check if this agent can handle the request
        
        Args:
            request: Request dictionary
            
        Returns:
            bool: True if this is a database query request
        """
        intent = request.get("intent", "")
        
        # Handle all query-related intents
        query_intents = [
            RequestIntent.QUERY_DATABASE.value,
            RequestIntent.SEARCH_DATA.value,
            "greeting",
            "help",
            "small_talk",
            "system_info",
            "capability_inquiry"
        ]
        
        return intent in query_intents
    
    async def process(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a database query request using JSON-based ORM queries
        
        Args:
            request: Request dictionary with:
                - question: str
                - session_id: str (optional)
                - context: Dict (optional)
                - message_history: List (optional) - previous messages for context
                
        Returns:
            Response dictionary
        """
        try:
            question = request["question"]
            session_id = request.get("session_id", "default")
            message_history = request.get("message_history", [])
            
            logger.info(f"Database Agent processing question: {question[:50]}...")
            if message_history:
                logger.info(f"Using {len(message_history)} messages for context")
            
            # Use new JSON-based query mode
            if self._use_json_query_mode:
                result = await self._process_with_json_query(
                    question, session_id, message_history
                )
            else:
                # Fallback to old chatbot engine
                result = await self._process_with_chatbot_engine(question, session_id)
            
            return result
            
        except Exception as e:
            logger.error(f"Database Agent error: {e}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"Query processing failed: {str(e)}",
                "metadata": {"agent": self.agent_name}
            }
    
    async def _process_with_json_query(
        self, 
        question: str, 
        session_id: str,
        message_history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Process query using JSON-based approach with dbt mart tables.
        
        Flow:
        1. Generate JSON query parameters using LLM (with mart-optimized prompt)
        2. Validate and parse JSON
        3. Execute query using MartQueryExecutor (queries analytics.mart__invoice_items)
        4. Generate natural language answer from results
        
        Args:
            question: User's natural language question
            session_id: Session identifier
            message_history: Optional list of previous messages for context
            
        Returns:
            Response dictionary
        """
        try:
            # Step 1: Generate JSON query parameters using LLM
            # Uses mart-optimized prompt if mart tables are enabled
            logger.info("Generating JSON query parameters from question...")
            json_params = await self._generate_json_query_params(
                question, message_history
            )
            
            # Step 2: Validate and parse JSON
            from mpi_backend.utils.chatbot.query_schema import QueryParameters
            try:
                query_params = QueryParameters(**json_params)
                logger.info(f"Generated query params: table={query_params.table}, "
                          f"filters={len(query_params.filters)}, "
                          f"aggregates={len(query_params.aggregates)}")
            except Exception as e:
                logger.error(f"Invalid JSON query parameters: {e}")
                logger.error(f"Generated JSON: {json_params}")
                return {
                    "success": False,
                    "data": None,
                    "error": f"Failed to parse query parameters: {str(e)}",
                    "metadata": {
                        "agent": self.agent_name,
                        "query_mode": "json_mart",
                        "json_params": json_params
                    }
                }
            
            # Step 3: Execute query using mart executor
            logger.info("Executing query on dbt mart tables...")
            mart_executor = self._get_mart_executor()
            
            # Check if mart is available
            if not mart_executor.is_mart_available():
                return {
                    "success": False,
                    "data": None,
                    "error": "Mart tables are not available. Please ensure dbt has been run to create the analytics tables.",
                    "metadata": {
                        "agent": self.agent_name,
                        "query_mode": "json_mart",
                        "mart_available": False
                    }
                }
            
            query_result = mart_executor.execute_query(query_params)
            query_source = "mart"
            
            if not query_result.success:
                return {
                    "success": False,
                    "data": None,
                    "error": query_result.error,
                    "metadata": {
                        "agent": self.agent_name,
                        "query_mode": f"json_{query_source}",
                        "query_params": query_params.dict()
                    }
                }
            
            # Step 4: Generate natural language answer from results
            logger.info(f"Query returned {query_result.count} results from {query_source}")
            answer = await self._generate_answer_from_results(
                question, 
                query_result.data,
                query_params
            )
            
            # Return standardized response
            return {
                "success": True,
                "data": {
                    "answer": answer,
                    "intent": "query_database",
                    "is_conversational": False,
                    "query_params": query_params.dict(),
                    "results_count": query_result.count
                },
                "error": None,
                "metadata": {
                    "agent": self.agent_name,
                    "session_id": session_id,
                    "query_mode": f"json_{query_source}",
                    "query_info": query_result.query_info,
                    "data_source": query_result.query_info.get("source", "unknown")
                }
            }
            
        except Exception as e:
            logger.error(f"Error in JSON query processing: {e}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"JSON query processing failed: {str(e)}",
                "metadata": {"agent": self.agent_name, "query_mode": "json_mart"}
            }
    
    async def _process_with_chatbot_engine(
        self, 
        question: str, 
        session_id: str
    ) -> Dict[str, Any]:
        """
        Fallback: Process using old chatbot engine with raw SQL
        
        Args:
            question: User's natural language question
            session_id: Session identifier
            
        Returns:
            Response dictionary
        """
        try:
            from mpi_backend.utils.chatbot import get_chatbot_engine
            engine = get_chatbot_engine()
            result = await engine.query(question, session_id=session_id)
            
            # Transform to standardized response format
            return {
                "success": True,
                "data": {
                    "answer": result.get("answer"),
                    "intent": result.get("intent"),
                    "is_conversational": result.get("is_conversational", False),
                    "sql_query": result.get("sql_query"),
                    "raw_results": result.get("raw_results")
                },
                "error": result.get("error"),
                "metadata": {
                    "agent": self.agent_name,
                    "session_id": session_id,
                    "query_mode": "sql",
                    "formatting": result.get("formatting", {})
                }
            }
        except Exception as e:
            logger.error(f"Chatbot engine error: {e}", exc_info=True)
            raise
    
    async def _generate_json_query_params(
        self, 
        question: str,
        message_history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Generate JSON query parameters from natural language question.
        
        Uses mart-optimized prompt if mart tables are enabled, which:
        - Uses flat column structure (no relationship paths)
        - References pre-computed numeric columns
        - Uses normalized columns for fuzzy search
        
        Args:
            question: Natural language question
            message_history: Optional list of previous messages for context
            
        Returns:
            Dictionary of query parameters
        """
        try:
            from datetime import datetime
            
            # Get the mart-optimized prompt (simpler schema, no relationship paths)
            prompt_loader = self._get_prompt_loader()
            system_prompt = prompt_loader.get_json_query_generation_prompt_mart()
            logger.info("Using mart-optimized JSON query generation prompt")
            
            # Add current date context to system prompt
            current_date = datetime.now()
            date_context = f"\n\n**CURRENT DATE CONTEXT:**\n"
            date_context += f"- Today's Date: {current_date.strftime('%Y-%m-%d')} ({current_date.strftime('%B %d, %Y')})\n"
            date_context += f"- Current Year: {current_date.year}\n"
            date_context += f"- Current Month: {current_date.strftime('%B %Y')}\n"
            date_context += f"- Day of Week: {current_date.strftime('%A')}\n\n"
            date_context += "Use this date to interpret relative dates like 'today', 'this month', 'last year', 'yesterday', etc.\n"
            
            system_prompt_with_context = system_prompt + date_context
            
            # Get LLM
            llm = self._get_llm_instance()
            
            # Create messages with conversation history
            from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
            messages = [
                SystemMessage(content=system_prompt_with_context),
            ]
            
            # Add conversation history for context (if provided)
            if message_history:
                logger.info(f"Adding {len(message_history)} messages as context")
                for msg in message_history:
                    if msg.role == "user":
                        messages.append(HumanMessage(content=msg.content))
                    elif msg.role == "assistant":
                        messages.append(AIMessage(content=msg.content))
            
            # Add current question
            messages.append(HumanMessage(content=f"Question: {question}"))
            
            # Generate JSON
            response = await llm.ainvoke(messages)
            json_str = response.content.strip()
            
            # Clean up response (remove markdown code blocks if present)
            import re
            json_str = re.sub(r'```json\s*', '', json_str)
            json_str = re.sub(r'```\s*$', '', json_str)
            json_str = json_str.strip()
            
            # Parse JSON
            json_params = json.loads(json_str)
            
            logger.info(f"Generated JSON query params successfully {json_str}")
            return json_params
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {e}")
            logger.error(f"LLM response was: {json_str[:500]}")
            raise ValueError(f"LLM did not generate valid JSON: {e}")
        except Exception as e:
            logger.error(f"Error generating JSON query params: {e}", exc_info=True)
            raise
    
    async def _generate_answer_from_results(
        self,
        question: str,
        results: List[Dict[str, Any]],
        query_params
    ) -> str:
        """
        Generate natural language answer from query results
        
        Args:
            question: Original question
            results: Query results
            query_params: Query parameters used
            
        Returns:
            Natural language answer
        """
        try:
            from datetime import datetime
            
            # Handle empty results
            if not results:
                return "No results found for your query. Try adjusting your search criteria."
            
            # Prepare results summary
            results_summary = self._format_results_summary(results, query_params)
            
            # Get LLM
            llm = self._get_llm_instance()
            
            # Add current date context
            current_date = datetime.now()
            date_context = f"\n\n**Context:** Today is {current_date.strftime('%B %d, %Y')}. Use this when presenting dates in your answer."
            
            # Create answer prompt
            from langchain_core.messages import SystemMessage, HumanMessage
            system_msg = """You are a helpful database assistant. Format the query results into a clear, natural language answer.

Rules:
1. Present the data in a well-organized, easy-to-read format
2. Use markdown tables for tabular data (if 5 or fewer results)
3. Use bullet points or numbered lists for larger datasets
4. Include totals, counts, or summaries when relevant
5. Be concise but informative
6. If there's only one result, present it naturally without a table
7. For aggregated data (counts, sums, averages), emphasize the key metrics
""" + date_context
            
            user_msg = f"""Question: {question}

Query Results ({len(results)} records):
{results_summary}

Please format this data into a clear, natural language answer."""
            
            messages = [
                SystemMessage(content=system_msg),
                HumanMessage(content=user_msg)
            ]
            
            # Generate answer
            response = await llm.ainvoke(messages)
            answer = response.content.strip()
            
            return answer
            
        except Exception as e:
            logger.error(f"Error generating answer: {e}", exc_info=True)
            # Fallback to basic formatting
            return self._format_results_as_fallback(results)
    
    def _format_results_summary(
        self,
        results: List[Dict[str, Any]],
        query_params
    ) -> str:
        """Format results into a summary string for LLM"""
        
        # Limit to first 50 results for LLM processing
        display_results = results[:50]
        
        # Convert to JSON string with nice formatting
        summary = json.dumps(display_results, indent=2, default=str)
        
        if len(results) > 50:
            summary += f"\n\n... and {len(results) - 50} more results"
        
        return summary
    
    def _format_results_as_fallback(self, results: List[Dict[str, Any]]) -> str:
        """Fallback formatting if LLM answer generation fails"""
        
        if not results:
            return "No results found."
        
        # Simple JSON formatting
        formatted = json.dumps(results[:50], indent=2, default=str)
        
        if len(results) > 50:
            return f"Found {len(results)} results (showing first 50):\n\n{formatted}"
        else:
            return f"Found {len(results)} results:\n\n{formatted}"
    
    def get_capabilities(self) -> List[AgentCapability]:
        """
        Get agent capabilities
        
        Returns:
            List of capabilities
        """
        return [
            AgentCapability.QUERY_DATABASE,
            AgentCapability.ANALYZE_DATA
        ]

