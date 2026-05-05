"""
Natural Language Chatbot Engine using Google Gemini and LangChain
for querying the MPI Backend PostgreSQL database.

Enhanced with conversational intelligence and multi-turn context support.
"""

import os
import logging
import re
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import text, inspect
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain.chains import create_sql_query_chain
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from google.api_core.exceptions import ResourceExhausted
from openai import RateLimitError

from mpi_backend.database import engine
from mpi_backend.utils.chatbot.conversation_manager import (
    get_conversation_manager, QueryIntent
)
from mpi_backend.utils.chatbot.prompts import get_prompt_loader
from mpi_backend.utils.chatbot.intelligent_query_processor import get_query_enhancer
from mpi_backend.utils.chatbot.query_preprocessor import get_query_preprocessor
from mpi_backend.utils.chatbot.semantic_enhancer import get_semantic_enhancer
from mpi_backend.utils.chatbot.fuzzy_search_builder import (
    get_fuzzy_search_builder, get_fallback_strategy
)

logger = logging.getLogger(__name__)


class ChatbotEngine:
    """Natural Language Chatbot Engine for MPI Backend Database"""

    def __init__(self):
        """Initialize the Chatbot Engine with Google Gemini and database connection"""
        self.engine = engine
        self.primary_llm = None
        self.fallback_llm = None
        self.sql_database = None
        self.sql_chain = None
        self.answer_chain = None
        self.conversation_manager = get_conversation_manager()
        self.prompt_loader = get_prompt_loader()
        
        # Initialize intelligent query processing components
        self.query_enhancer = get_query_enhancer()
        self.query_preprocessor = get_query_preprocessor()
        self.semantic_enhancer = get_semantic_enhancer()
        self.fuzzy_search_builder = get_fuzzy_search_builder()
        self.fallback_strategy = get_fallback_strategy()
        
        self._setup_llms()
        self._setup_database()
        self._setup_chains()

    def _setup_llms(self):
        """Setup primary and fallback LLMs"""
        # Setup primary LLM (Gemini 2.5 Flash)
        try:
            api_key = os.getenv("GOOGLE_CHATBOT_API_KEY")
            if not api_key:
                raise ValueError(
                    "GOOGLE_CHATBOT_API_KEY not found in environment "
                    "variables"
                )

            # Initialize Google Gemini 2.5 Flash
            self.primary_llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                google_api_key=api_key,
                temperature=0,  # Deterministic responses
                convert_system_message_to_human=True
            )
            logger.info("Google Gemini 2.5 Flash LLM initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Google Gemini LLM: {e}")
            self.primary_llm = None

        # Setup fallback LLM (OpenAI GPT-4o mini)
        try:
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                self.fallback_llm = ChatOpenAI(
                    model="gpt-4o-mini",
                    api_key=openai_key,
                    temperature=0,
                    max_tokens=4000
                )
                logger.info("OpenAI GPT-4o mini fallback LLM initialized")
            else:
                logger.warning("OPENAI_API_KEY not found - no fallback LLM")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI fallback LLM: {e}")
            self.fallback_llm = None

        if not self.primary_llm and not self.fallback_llm:
            raise ValueError(
                "No LLM available - both primary and fallback failed"
            )

    def _setup_database(self):
        """Setup SQLAlchemy database connection for LangChain"""
        try:
            # Create LangChain SQL Database instance with enhanced context
            self.sql_database = SQLDatabase(
                engine=self.engine,
                include_tables=self._get_table_names(),
                sample_rows_in_table_info=3,
                custom_table_info=self._get_enhanced_table_info()
            )
            logger.info("Database connection setup successfully")
        except Exception as e:
            logger.error(f"Failed to setup database connection: {e}")
            raise

    def _get_table_names(self) -> List[str]:
        """Get list of table names from the database models"""
        try:
            inspector = inspect(self.engine)
            tables = inspector.get_table_names()
            logger.info(f"Found tables: {tables}")
            return tables
        except Exception as e:
            logger.error(f"Failed to get table names: {e}")
            return []
    
    def _get_enhanced_table_info(self) -> Dict[str, str]:
        """Get enhanced table information with relationships and business context"""
        return self.prompt_loader.get_table_info()

    def _setup_chains(self):
        """Setup LangChain chains for SQL generation and answer formatting"""
        try:
            # Use primary LLM for chain setup
            current_llm = self.primary_llm or self.fallback_llm

            # Create SQL query generation chain
            self.sql_chain = create_sql_query_chain(
                llm=current_llm,
                db=self.sql_database
            )

            # Create answer generation chain
            answer_prompt = PromptTemplate.from_template(
                self.prompt_loader.get_sql_generation_prompt()
            )

            self.answer_chain = (
                RunnablePassthrough.assign(query=self.sql_chain)
                | RunnablePassthrough.assign(
                    result=lambda x: self._execute_sql_query(x["query"])
                )
                | answer_prompt
                | current_llm
                | StrOutputParser()
            )

            logger.info("LangChain chains setup successfully")
        except Exception as e:
            logger.error(f"Failed to setup LangChain chains: {e}")
            raise

    def _is_safe_query(self, sql_query: str) -> bool:
        """Check if the SQL query is safe (only SELECT statements)"""
        # Clean the query - remove markdown formatting
        clean_query = sql_query.strip()

        # Remove markdown code blocks
        clean_query = re.sub(r'```sql\s*', '', clean_query, flags=re.IGNORECASE)
        clean_query = re.sub(r'```\s*$', '', clean_query, flags=re.IGNORECASE)
        
        # Remove SQLQuery prefix
        clean_query = re.sub(r'SQLQuery:\s*', '', clean_query, flags=re.IGNORECASE)

        # Convert to uppercase for checking
        clean_query = clean_query.upper()

        # Remove comments
        clean_query = re.sub(r'--.*$', '', clean_query, flags=re.MULTILINE)
        clean_query = re.sub(r'/\*.*?\*/', '', clean_query, flags=re.DOTALL)

        # Check for dangerous operations
        dangerous_keywords = [
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER',
            'TRUNCATE', 'GRANT', 'REVOKE', 'EXECUTE', 'EXEC'
        ]

        for keyword in dangerous_keywords:
            if keyword in clean_query:
                return False

        # Must start with SELECT
        if not clean_query.startswith('SELECT'):
            return False

        return True

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if the error is a rate limit error"""
        if isinstance(error, ResourceExhausted):
            return True
        if isinstance(error, RateLimitError):
            return True
        if (hasattr(error, 'message') and
                'quota' in str(error.message).lower()):
            return True
        if ('rate limit' in str(error).lower() or
                'quota' in str(error).lower()):
            return True
        return False

    def _get_available_llm(self) -> Optional[Any]:
        """Get the first available LLM (primary or fallback)"""
        if self.primary_llm:
            return self.primary_llm
        if self.fallback_llm:
            return self.fallback_llm
        return None

    async def _execute_with_fallback(self, operation, *args, **kwargs):
        """Execute operation with primary LLM, fallback if rate limited"""
        max_retries = 2
        retry_delay = 1
        gemini_rate_limited = False

        for attempt in range(max_retries):
            try:
                # Try primary LLM first
                if self.primary_llm and attempt == 0:
                    logger.info("Attempting with primary LLM (Gemini 2.5 Flash)")
                    result = await operation(self.primary_llm, *args, **kwargs)
                    return result, gemini_rate_limited

                # Try fallback LLM
                elif self.fallback_llm:
                    logger.info("Attempting with fallback LLM (OpenAI GPT-4o mini)")
                    result = await operation(self.fallback_llm, *args, **kwargs)
                    return result, gemini_rate_limited

                else:
                    raise Exception("No LLM available")

            except Exception as e:
                if self._is_rate_limit_error(e):
                    logger.warning(
                        f"Rate limit hit on attempt {attempt + 1}: {e}"
                    )
                    
                    # Track if Gemini was rate limited
                    if attempt == 0 and self.primary_llm:
                        gemini_rate_limited = True
                        logger.warning("Gemini 2.5 Flash rate limit exceeded, trying fallback...")
                    
                    if attempt < max_retries - 1:
                        # Exponential backoff
                        await asyncio.sleep(retry_delay * (2 ** attempt))
                        continue
                    else:
                        logger.error("All LLMs hit rate limits")
                        raise Exception(
                            f"Rate limit exceeded on all available LLMs: {e}"
                        )
                else:
                    logger.error(f"Non-rate-limit error: {e}")
                    raise e

        raise Exception("Max retries exceeded")

    def _sanitize_results(self, results: str) -> str:
        """Remove sensitive information from query results"""
        import re

        # Remove UUIDs and IDs
        results = re.sub(
            r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
            '[ID_HIDDEN]', results, flags=re.IGNORECASE
        )

        # Remove storage paths
        results = re.sub(
            r'mpi_backend/storage/[^\\s]+', '[PATH_HIDDEN]', results
        )

        # Remove any remaining file paths
        results = re.sub(
            r'/[^\\s]+\\.(pdf|PDF|xlsx|XLSX|xls|XLS)',
            '[FILE_HIDDEN]', results
        )

        # Remove any remaining IDs or sensitive patterns
        results = re.sub(
            r'id\s*:\s*[^\\s,]+', 'id: [HIDDEN]', results,
            flags=re.IGNORECASE
        )
        results = re.sub(
            r'supplier_id\s*:\s*[0-9]+', 'supplier_id: [HIDDEN]', results
        )
        results = re.sub(
            r'invoice_id\s*:\s*[^\\s,]+', 'invoice_id: [HIDDEN]', results
        )

        return results

    def _ensure_markdown_formatting(self, answer: str, question: str, results: str) -> str:
        """Return answer directly without extra formatting"""
        return answer
    
    def _enhance_question_intelligently(
        self, question: str
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Enhance question with intelligent processing
        
        Args:
            question: Original user question
            
        Returns:
            Tuple of (enhanced_question, enhancement_metadata)
        """
        try:
            # Step 1: Enhance with query processor (dates, synonyms, entities)
            enhancement_data = self.query_enhancer.enhance(question)
            
            # Step 2: Pre-process (typo detection, normalization)
            preprocessing_data = self.query_preprocessor.preprocess(
                question,
                enhancement_data
            )
            
            # Step 3: Add semantic understanding
            semantic_data = self.semantic_enhancer.enhance_with_semantics(
                preprocessing_data['normalized_question'],
                enhancement_data.get('entities')
            )
            
            # Build enhanced question with all intelligence
            base_question = preprocessing_data['normalized_question']
            
            # Add context from all enhancements
            context_parts = []
            
            if enhancement_data.get('enhancement_notes'):
                context_parts.append(enhancement_data['enhancement_notes'])
            
            if preprocessing_data.get('context_hints'):
                context_parts.append(
                    "CONTEXT HINTS:\n" + "\n".join([
                        f"• {hint}" for hint in preprocessing_data['context_hints']
                    ])
                )
            
            if preprocessing_data.get('business_rules'):
                context_parts.append(
                    "BUSINESS RULES:\n" + "\n".join([
                        f"• {rule}" for rule in preprocessing_data['business_rules']
                    ])
                )
            
            # Combine everything
            if context_parts:
                enhanced_question = (
                    f"{base_question}\n\n"
                    f"--- INTELLIGENT CONTEXT ---\n"
                    f"{chr(10).join(context_parts)}"
                )
            else:
                enhanced_question = base_question
            
            # Compile metadata
            metadata = {
                'enhancement_data': enhancement_data,
                'preprocessing_data': preprocessing_data,
                'semantic_data': semantic_data,
                'has_enhancements': (
                    enhancement_data.get('has_enhancements', False) or
                    preprocessing_data.get('has_context', False)
                ),
                'typos_found': preprocessing_data.get('typos_detected', {})
            }
            
            logger.info(
                f"Question enhancement complete. "
                f"Enhancements: {metadata['has_enhancements']}, "
                f"Typos: {len(metadata['typos_found'].get('common_typos', []))}"
            )
            
            return enhanced_question, metadata
            
        except Exception as e:
            logger.error(f"Error enhancing question: {e}")
            # Return original question if enhancement fails
            return question, {'has_enhancements': False, 'error': str(e)}
    
    def _generate_no_results_fallback(self, question: str, intent: str) -> str:
        """Generate helpful fallback message when no results are found"""
        question_lower = question.lower()
        
        # Provide context-specific suggestions
        suggestions = []
        
        if 'supplier' in question_lower:
            suggestions.append("• Try checking the exact supplier name - it must match exactly")
            suggestions.append("• Use partial names if you're unsure of the exact spelling")
        
        if 'invoice' in question_lower:
            suggestions.append("• Verify the date range or reference number")
            suggestions.append("• Check if the invoice has been processed (status = PROCESSED)")
        
        if 'customer' in question_lower or 'job' in question_lower:
            suggestions.append("• Double-check the customer job name spelling")
            suggestions.append("• Customer jobs are stored in the invoice_items table")
        
        if any(month in question_lower for month in ['january', 'february', 'march', 'april', 
                                                       'may', 'june', 'july', 'august', 
                                                       'september', 'october', 'november', 'december']):
            suggestions.append("• Ensure the date format and year are correct")
            suggestions.append("• Check if data exists for that time period")
        
        # Return a simple, concise message
        if suggestions:
            return f"No results found. {suggestions[0].replace('• ', '')}"
        else:
            return "No results found. Try being more specific or check your search terms."

    def _execute_sql_query(self, sql_query: str) -> str:
        """Execute SQL query safely and return formatted results"""
        try:
            # Clean the SQL query - remove all markdown formatting
            clean_sql = sql_query.strip()
            clean_sql = re.sub(r'```sql\s*', '', clean_sql, flags=re.IGNORECASE)
            clean_sql = re.sub(
                r'```.*$', '', clean_sql,
                flags=re.IGNORECASE | re.DOTALL
            )
            clean_sql = re.sub(
                r'SQLQuery:\s*', '', clean_sql, flags=re.IGNORECASE
            )
            clean_sql = re.sub(
                r'SQLResult:.*$', '', clean_sql,
                flags=re.IGNORECASE | re.DOTALL
            )
            clean_sql = re.sub(
                r'Answer:.*$', '', clean_sql,
                flags=re.IGNORECASE | re.DOTALL
            )
            clean_sql = clean_sql.strip()

            # Safety check
            if not self._is_safe_query(sql_query):
                return ("⚠️ Warning: Only SELECT queries are allowed. "
                        "Write operations are blocked for safety.")

            # Execute query
            with self.engine.connect() as connection:
                result = connection.execute(text(clean_sql))
                rows = result.fetchall()

                if not rows:
                    return "No results found."

                # Format results
                columns = list(result.keys())
                formatted_results = []

                for row in rows:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        value = row[i]
                        # Handle amount fields that might contain commas
                        if col in ['amount', 'cost'] and isinstance(value, str):
                            # Remove commas and try to convert to float
                            try:
                                clean_value = value.replace(',', '')
                                if clean_value.replace('.', '').isdigit():
                                    row_dict[col] = float(clean_value)
                                else:
                                    row_dict[col] = value
                            except (ValueError, AttributeError):
                                row_dict[col] = value
                        else:
                            row_dict[col] = value
                    formatted_results.append(row_dict)

                # Limit results for readability (max 50 rows)
                if len(formatted_results) > 50:
                    return (f"Found {len(formatted_results)} results "
                            f"(showing first 50):\n"
                            f"{str(formatted_results[:50])}")
                else:
                    return (f"Found {len(formatted_results)} results:\n"
                            f"{str(formatted_results)}")
        except Exception as e:
            logger.error(f"Error executing SQL query: {e}")
            return f"Error executing query: {str(e)}"

    async def query(self, question: str, session_id: str = "default") -> Dict[str, Any]:
        """
        Process a natural language question and return structured response
        Enhanced with conversational intelligence and context management

        Args:
            question (str): Natural language question about the database
            session_id (str): Session identifier for context tracking

        Returns:
            Dict containing answer, sql_query, raw_results, and any errors
        """
        try:
            logger.info(f"Processing question: {question}")
            
            # Step 1: Classify intent and check if conversational response is needed
            classification = self.conversation_manager.classify_and_respond(
                question, session_id
            )
            
            intent = classification["intent"]
            needs_database = classification["needs_database"]
            conversational_response = classification.get("conversational_response")
            context = classification.get("context")
            conversation_history = classification.get("conversation_history", "")
            
            # Step 2: Handle conversational queries (no database needed)
            if not needs_database and conversational_response:
                logger.info(f"Returning conversational response for intent: {intent}")
                
                # Add to conversation history
                self.conversation_manager.add_to_history(
                    session_id, question, QueryIntent(intent), 
                    conversational_response
                )
                
                return {
                    "answer": conversational_response,
                    "sql_query": None,
                    "raw_results": None,
                    "error": None,
                    "intent": intent,
                    "is_conversational": True
                }
            
            # Step 3: Process database query with context awareness
            logger.info(f"Processing database query with intent: {intent}")

            # Use original question - keep it simple like before
            enhanced_question = question
            
            # Optionally try intelligent enhancement (but don't let it break queries)
            try:
                _, enhancement_metadata = self._enhance_question_intelligently(question)
                # Only add minimal context hints if we detect specific patterns
                if enhancement_metadata.get('has_enhancements'):
                    logger.info(f"Enhancement metadata available: {enhancement_metadata.get('has_enhancements')}")
                    # Don't modify the question - just log the metadata
            except Exception as e:
                logger.warning(f"Enhancement failed (non-critical): {e}")
                enhancement_metadata = {'has_enhancements': False}
            
            # Add multi-turn context if available
            if context and context.is_follow_up(question):
                context_summary = context.get_context_summary()
                if context_summary:
                    enhanced_question = f"{question}\n\nContext: {context_summary}"
                    logger.info(f"Added conversation context: {context_summary[:50]}...")
            
            # Add full conversation history for better context understanding
            if conversation_history:
                enhanced_question = f"{enhanced_question}\n\n{conversation_history}"
                logger.info("Added full conversation history to query context")

            # Generate SQL query with fallback
            async def generate_sql(llm):
                # Create a new SQL chain with the specified LLM
                sql_chain = create_sql_query_chain(
                    llm=llm,
                    db=self.sql_database
                )
                return await sql_chain.ainvoke({"question": enhanced_question})

            sql_result, gemini_rate_limited = await self._execute_with_fallback(generate_sql)
            sql_query = sql_result
            logger.info(f"Generated SQL: {sql_query}")

            # Safety check
            if not self._is_safe_query(sql_query):
                safe_answer = (
                    "⚠️ I can only perform read-only queries (SELECT statements) to protect your data. "
                    "I detected a potentially unsafe operation in your request.\n\n"
                    "If you need to modify data, please use the appropriate API endpoints or "
                    "contact your system administrator."
                )
                return {
                    "answer": safe_answer,
                    "sql_query": sql_query,
                    "raw_results": [],
                    "error": "Unsafe query detected",
                    "intent": intent,
                    "is_conversational": False
                }

            # Execute query and get raw results
            raw_results = self._execute_sql_query(sql_query)

            # Sanitize results to remove sensitive information
            sanitized_results = self._sanitize_results(str(raw_results))
            
            # Check for empty results and provide helpful fallback
            if "No results found" in raw_results or not raw_results:
                logger.info("No results found for query")
                fallback_answer = self._generate_no_results_fallback(question, intent)
                
                # Add to conversation history
                self.conversation_manager.add_to_history(
                    session_id, question, QueryIntent(intent), 
                    fallback_answer, sql_query
                )
                
                return {
                    "answer": fallback_answer,
                    "sql_query": sql_query,
                    "raw_results": raw_results,
                    "error": None,
                    "intent": intent,
                    "is_conversational": False
                }

            # Generate natural language answer with fallback
            # Capture conversation_history with safe fallback for template
            history_for_prompt = conversation_history if conversation_history else "No previous conversation."
            
            async def generate_answer(llm, history=history_for_prompt):
                # Create answer generation chain with the specified LLM
                answer_prompt = PromptTemplate.from_template(
                    self.prompt_loader.get_answer_formatting_prompt('standard')
                )

                answer_chain = (
                    RunnablePassthrough.assign(query=lambda x: sql_query)
                    | RunnablePassthrough.assign(result=lambda x: raw_results)
                    | RunnablePassthrough.assign(conversation_history=lambda x: history)
                    | answer_prompt
                    | llm
                    | StrOutputParser()
                )

                answer = await answer_chain.ainvoke({"question": question})
                
                # Ensure markdown formatting is applied
                answer = self._ensure_markdown_formatting(answer, question, raw_results)
                
                return answer

            answer_result, gemini_rate_limited_answer = await self._execute_with_fallback(generate_answer)
            answer = answer_result

            # Check if Gemini was rate limited
            gemini_rate_limited = gemini_rate_limited or gemini_rate_limited_answer
            
            # If Gemini was rate limited, add a note to the answer
            if gemini_rate_limited:
                answer = (
                    "⚠️ Note: Gemini 2.5 Flash rate limit exceeded, "
                    "using fallback model for this response.\n\n" + answer
                )
                logger.info("Response generated using fallback due to Gemini rate limits")
            
            # Add to conversation history
            self.conversation_manager.add_to_history(
                session_id, question, QueryIntent(intent), 
                answer, sql_query
            )
            
            # Return structured response
            return {
                "answer": answer,
                "sql_query": sql_query,
                "raw_results": f"Found {len(raw_results) if isinstance(raw_results, list) else 1} results",
                "error": None,
                "intent": intent,
                "is_conversational": False
            }

        except Exception as e:
            logger.error(f"Error processing question: {e}")

            # If it's a rate limit error, provide a helpful message
            if self._is_rate_limit_error(e):
                return {
                    "answer": "Rate limit exceeded. Please wait a minute and try again.",
                    "sql_query": None,
                    "raw_results": None,
                    "error": str(e),
                    "intent": "error",
                    "is_conversational": True
                }
            else:
                # Generate user-friendly error message
                error_message = (
                    "I encountered an issue while processing your question. "
                    "Here's what happened:\n\n"
                    f"**Error:** {str(e)}\n\n"
                    "**What you can try:**\n"
                    "• Rephrase your question in a different way\n"
                    "• Make sure your question relates to invoices, suppliers, or items\n"
                    "• Ask for help by typing 'help' to see example questions\n\n"
                    "If this error persists, please contact support with the details above."
                )
                
                return {
                    "answer": error_message,
                    "sql_query": None,
                    "raw_results": None,
                    "error": str(e),
                    "intent": "error",
                    "is_conversational": True
                }

    async def debug_query(self, question: str) -> Dict[str, Any]:
        """
        Process a natural language question and return debug information
        
        Args:
            question (str): Natural language question about the database
            
        Returns:
            Dict containing answer, sql_query, raw_results, debug_info, and any errors
        """
        try:
            logger.info(f"Processing debug question: {question}")
            
            # Generate SQL query with fallback
            async def generate_sql(llm):
                sql_chain = create_sql_query_chain(
                    llm=llm,
                    db=self.sql_database
                )
                return await sql_chain.ainvoke({"question": question})
            
            sql_result, gemini_rate_limited = await self._execute_with_fallback(generate_sql)
            sql_query = sql_result
            logger.info(f"Generated SQL: {sql_query}")
            
            # Safety check
            safety_check = "PASSED" if self._is_safe_query(sql_query) else "FAILED"
            
            # Get table info for debugging
            table_info = self._get_enhanced_table_info()
            
            # Execute query and get raw results (only if safe)
            if safety_check == "PASSED":
                raw_results = self._execute_sql_query(sql_query)
                sanitized_results = self._sanitize_results(str(raw_results))
                
                # Generate natural language answer with fallback
                async def generate_answer(llm):
                    answer_prompt = PromptTemplate.from_template(
                        self.prompt_loader.get_answer_formatting_prompt('debug')
                    )
                    
                    answer_chain = (
                        RunnablePassthrough.assign(query=lambda x: sql_query)
                        | RunnablePassthrough.assign(result=lambda x: raw_results)
                        | answer_prompt
                        | llm
                        | StrOutputParser()
                    )
                    
                    return await answer_chain.ainvoke({"question": question})
                
                answer_result, gemini_rate_limited_answer = await self._execute_with_fallback(generate_answer)
                answer = answer_result
                
                if gemini_rate_limited or gemini_rate_limited_answer:
                    answer = "⚠️ Note: Gemini 2.5 Flash rate limit exceeded, using fallback model.\n\n" + answer
                
                return {
                    "answer": answer,
                    "sql_query": sql_query,
                    "raw_results": f"Found {len(raw_results) if isinstance(raw_results, list) else 1} results",
                    "debug_info": {
                        "table_info": table_info,
                        "safety_check": safety_check,
                        "gemini_rate_limited": gemini_rate_limited or gemini_rate_limited_answer
                    },
                    "error": None
                }
            else:
                return {
                    "answer": "⚠️ Warning: Only SELECT queries are allowed. Write operations are blocked for safety.",
                    "sql_query": sql_query,
                    "raw_results": [],
                    "debug_info": {
                        "table_info": table_info,
                        "safety_check": safety_check,
                        "gemini_rate_limited": False
                    },
                    "error": "Unsafe query detected"
                }
                
        except Exception as e:
            logger.error(f"Error processing debug question: {e}")
            return {
                "answer": f"I encountered an error while processing your question: {str(e)}",
                "sql_query": None,
                "raw_results": None,
                "debug_info": {
                    "table_info": {},
                    "safety_check": "ERROR",
                    "gemini_rate_limited": False
                },
                "error": str(e)
            }


# Global instance
_chatbot_engine = None


def get_chatbot_engine() -> ChatbotEngine:
    """Get or create Chatbot Engine instance (singleton pattern)"""
    global _chatbot_engine
    if _chatbot_engine is None:
        _chatbot_engine = ChatbotEngine()
    return _chatbot_engine
