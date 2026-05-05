"""
Intent Router
Classifies user requests and routes to appropriate agents
"""

import re
from enum import Enum
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class RequestIntent(Enum):
    """Request intent types for routing"""
    # Query intents
    QUERY_DATABASE = "query_database"
    SEARCH_DATA = "search_data"
    
    # File generation intents
    GENERATE_EXCEL = "generate_excel"
    GENERATE_PDF = "generate_pdf"
    EXPORT_DATA = "export_data"
    
    # Communication intents
    SEND_EMAIL = "send_email"
    SEND_NOTIFICATION = "send_notification"
    
    # Report intents
    GENERATE_REPORT = "generate_report"
    ANALYZE_TRENDS = "analyze_trends"
    
    # Management intents
    UPDATE_DATA = "update_data"
    DELETE_DATA = "delete_data"
    CREATE_RECORD = "create_record"
    
    # Conversational intents
    GREETING = "greeting"
    HELP = "help"
    SMALL_TALK = "small_talk"
    
    # Unknown
    UNKNOWN = "unknown"


class IntentRouter:
    """
    Routes requests to appropriate agents based on intent classification
    """
    
    # Intent detection patterns
    INTENT_PATTERNS = {
        RequestIntent.GENERATE_EXCEL: [
            # Excel patterns
            r'\b(generate|create|make|export)\b.*\b(excel|spreadsheet|xlsx|csv)\b',
            r'\bexcel\b.*\b(file|export|download)\b',
            r'\bdownload\b.*\b(excel|spreadsheet|xlsx)\b',
            r'\bexport to (excel|xlsx)\b',
            r'\b(get|give me)\b.*\b(excel|xlsx)\b',
            r'\bexcel\b',
            r'\bxlsx\b',
            # CSV patterns (explicit)
            r'\bcsv\b',  # Any mention of CSV
            r'\b(generate|create|make|export)\b.*\bcsv\b',
            r'\bcsv\b.*\b(file|export|download)\b',
            r'\bdownload\b.*\bcsv\b',
            r'\b(want|need)\b.*\bcsv\b',
            r'\bexport to csv\b',
            r'\bexport\b.*\bas\b.*\bcsv\b',
            r'\b(get|give me)\b.*\bcsv\b',
            r'\bcsv\b.*\bfor\b',
            r'\bdownload\b.*\b(file|data|invoices?|items?)\b',
        ],
        RequestIntent.EXPORT_DATA: [
            r'\bexport\b.*\b(data|invoices?|items?|records?)\b',
            r'\bdownload\b.*\b(data|invoices?|items?|records?)\b',
            r'\b(get|give me)\b.*\b(download|export)\b',
            r'\bexport\b.*\bto\b.*\b(file|csv|excel)\b',
        ],
        RequestIntent.GENERATE_PDF: [
            r'\b(generate|create|make)\b.*\bpdf\b',
            r'\bpdf\b.*\b(file|export|download)\b',
        ],
        RequestIntent.SEND_EMAIL: [
            r'\b(send|email|mail)\b.*\b(to|invoice|report)\b',
            r'\bemail\b.*\b(me|this|that)\b',
            r'\bsend (me|this|that|it)\b',
            r'\b(create|generate|make|write|provide)\b.*\bemail\b.*\b(supplier|suppliers)\b.*\b(increase|increased|price|prices)\b',
            r'\b(create|generate|make|write|provide)\b.*\bemail\b.*\b(price|prices)\b.*\b(increase|increased)\b',
            r'\b(create|generate|make|write|provide)\b.*\bemail\b.*\b(price|prices)\b.*\b(increase|increased)\b.*\b(in|for|of)\b',
            r'\bemail\b.*\b(supplier|suppliers)\b.*\b(increase|increased|price|prices)\b',
            r'\bemail\b.*\b(price|prices)\b.*\b(increase|increased)\b.*\b(supplier|suppliers)\b',
            r'\b(create|generate|make|write|provide)\b.*\bemail\b.*\b(price|prices)\b.*\b(increase|increased)\b.*\b(january|february|march|april|may|june|july|august|september|october|november|december)\b',
            r'\b(provide|give|get)\b.*\bemail\b.*\b(price|prices)\b.*\b(increase|increased)\b',
            r'\bemail\b.*\bfor\b.*\b(price|prices)\b.*\b(increase|increased)\b',
        ],
        RequestIntent.GENERATE_REPORT: [
            r'\b(generate|create|build)\b.*\breport\b',
            r'\b(monthly|weekly|annual|quarterly)\b.*\breport\b',
            r'\breport\b.*\b(for|on|about)\b',
        ],
        RequestIntent.UPDATE_DATA: [
            r'\b(update|modify|change|edit)\b',
            r'\bset\b.*\bto\b',
        ],
        RequestIntent.DELETE_DATA: [
            r'\b(delete|remove|drop)\b',
        ],
        RequestIntent.CREATE_RECORD: [
            r'\b(create|add|insert|new)\b.*\b(invoice|supplier|item)\b',
        ],
        RequestIntent.GREETING: [
            r'\b(hi|hello|hey|greetings)\b',
        ],
        RequestIntent.HELP: [
            r'\b(help|assist|support)\b',
            r'\bhow (do|can) i\b',
        ],
        RequestIntent.QUERY_DATABASE: [
            r'\b(show|list|find|get|retrieve|display|count|total)\b',
            r'\b(how many|how much)\b',
            r'\b(what|which|where|when)\b.*\b(invoice|supplier|item|customer)\b',
        ],
    }
    
    @classmethod
    def classify_intent(cls, question: str, context: Optional[Dict[str, Any]] = None) -> RequestIntent:
        """
        Classify the intent of a user question
        
        Args:
            question: User's question
            context: Optional context from previous interactions
            
        Returns:
            RequestIntent enum
        """
        question_lower = question.lower().strip()
        
        # Check patterns in priority order
        # SEND_EMAIL should be checked early, especially for price increase emails
        priority_order = [
            RequestIntent.GENERATE_EXCEL,  # Excel/CSV export (highest priority for exports)
            RequestIntent.EXPORT_DATA,     # Generic export requests
            RequestIntent.GENERATE_PDF,
            RequestIntent.SEND_EMAIL,  # Check email intents before database queries
            RequestIntent.GENERATE_REPORT,
            RequestIntent.UPDATE_DATA,
            RequestIntent.DELETE_DATA,
            RequestIntent.CREATE_RECORD,
            RequestIntent.GREETING,
            RequestIntent.HELP,
            RequestIntent.QUERY_DATABASE,  # Database queries are the default fallback
        ]
        
        for intent in priority_order:
            if intent in cls.INTENT_PATTERNS:
                patterns = cls.INTENT_PATTERNS[intent]
                if cls._matches_patterns(question_lower, patterns):
                    logger.info(f"Classified intent: {intent.value} for question: {question[:50]}...")
                    return intent
        
        # Default to query database for most questions
        logger.info(f"Defaulting to QUERY_DATABASE intent for: {question[:50]}...")
        return RequestIntent.QUERY_DATABASE
    
    @staticmethod
    def _matches_patterns(text: str, patterns: list) -> bool:
        """Check if text matches any pattern"""
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    @classmethod
    def get_agent_capability(cls, intent: RequestIntent) -> str:
        """
        Map intent to agent capability
        
        Args:
            intent: Classified request intent
            
        Returns:
            Agent capability string
        """
        from .base_agent import AgentCapability
        
        mapping = {
            RequestIntent.QUERY_DATABASE: AgentCapability.QUERY_DATABASE,
            RequestIntent.SEARCH_DATA: AgentCapability.QUERY_DATABASE,
            RequestIntent.GENERATE_EXCEL: AgentCapability.GENERATE_EXCEL,
            RequestIntent.GENERATE_PDF: AgentCapability.GENERATE_REPORT,
            RequestIntent.EXPORT_DATA: AgentCapability.GENERATE_EXCEL,
            RequestIntent.SEND_EMAIL: AgentCapability.SEND_EMAIL,
            RequestIntent.GENERATE_REPORT: AgentCapability.GENERATE_REPORT,
            RequestIntent.ANALYZE_TRENDS: AgentCapability.ANALYZE_DATA,
        }
        
        return mapping.get(intent, AgentCapability.QUERY_DATABASE)
    
    @classmethod
    def create_request(
        cls,
        question: str,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        message_history: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Create a standardized request object
        
        Args:
            question: User's question
            session_id: Optional session identifier
            context: Optional additional context
            message_history: Optional list of previous messages for conversation context
            
        Returns:
            Standardized request dictionary
        """
        intent = cls.classify_intent(question, context)
        
        return {
            "question": question,
            "intent": intent.value,
            "session_id": session_id or "default",
            "context": context or {},
            "capability_required": cls.get_agent_capability(intent).value,
            "message_history": message_history or []
        }

