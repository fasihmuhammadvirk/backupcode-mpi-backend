"""
Conversation Manager for Enhanced QA System
Handles intent classification, context management, and conversational responses
"""

import logging
import re
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
from mpi_backend.utils.chatbot.prompts import get_prompt_loader

logger = logging.getLogger(__name__)


class QueryIntent(Enum):
    """Classification of query intents"""
    GREETING = "greeting"
    FAREWELL = "farewell"
    HELP = "help"
    SYSTEM_INFO = "system_info"
    CAPABILITY_INQUIRY = "capability_inquiry"
    DATABASE_QUERY = "database_query"
    SMALL_TALK = "small_talk"
    CLARIFICATION = "clarification"
    MULTI_TURN = "multi_turn"
    ACTION_REQUEST_VAGUE = "action_request_vague"  # Vague action requests needing clarification


class ConversationContext:
    """Manages conversation context across multiple turns"""
    
    def __init__(self, max_history: int = 5):
        self.history: List[Dict[str, Any]] = []
        self.max_history = max_history
        self.session_start = datetime.now()
        self.last_query_intent = None
        self.last_sql_query = None
        self.last_topic = None
    
    def add_turn(self, question: str, intent: QueryIntent, response: str, 
                 sql_query: Optional[str] = None):
        """Add a conversation turn to history"""
        turn = {
            "timestamp": datetime.now(),
            "question": question,
            "intent": intent,
            "response": response,
            "sql_query": sql_query,
            "topic": self._extract_topic(question)
        }
        
        self.history.append(turn)
        self.last_query_intent = intent
        self.last_sql_query = sql_query
        self.last_topic = turn["topic"]
        
        # Maintain max history limit
        if len(self.history) > self.max_history:
            self.history.pop(0)
    
    def _extract_topic(self, question: str) -> Optional[str]:
        """Extract main topic from question"""
        question_lower = question.lower()
        
        # Database entity topics (order matters - more specific first)
        if any(word in question_lower for word in ['customer job', 'customer_job', 'project']):
            return "customer_jobs"
        elif any(word in question_lower for word in ['invoice', 'invoices']):
            return "invoices"
        elif any(word in question_lower for word in ['supplier', 'suppliers', 'vendor']):
            return "suppliers"
        elif any(word in question_lower for word in ['export', 'quickbooks', 'accounting']):
            return "export"
        elif any(word in question_lower for word in ['item', 'items', 'product']):
            return "items"
        elif any(word in question_lower for word in ['customer', 'job']):
            return "customer_jobs"
        
        return None
    
    def get_context_summary(self) -> str:
        """Get a summary of recent conversation context"""
        if not self.history:
            return ""
        
        context_parts = []
        
        # Recent topics
        recent_topics = [turn.get("topic") for turn in self.history if turn.get("topic")]
        if recent_topics:
            context_parts.append(f"Recent topics: {', '.join(set(recent_topics))}")
        
        # Last database query
        if self.last_sql_query:
            context_parts.append("Previous database query context available")
        
        return " | ".join(context_parts) if context_parts else ""
    
    def is_follow_up(self, question: str) -> bool:
        """Determine if current question is a follow-up to previous conversation"""
        if not self.history:
            return False
        
        question_lower = question.lower()
        
        # Check for follow-up indicators
        follow_up_patterns = [
            r'\b(what about|how about|and|also|more|show me)\b',
            r'\b(that|those|these|them|it)\b',
            r'\b(same|similar|related)\b',
        ]
        
        for pattern in follow_up_patterns:
            if re.search(pattern, question_lower):
                return True
        
        return False
    
    def clear(self):
        """Clear conversation context"""
        self.history.clear()
        self.last_query_intent = None
        self.last_sql_query = None
        self.last_topic = None
    
    def get_formatted_history(self, max_turns: int = 5) -> str:
        """
        Get formatted conversation history for LLM context
        
        Args:
            max_turns: Maximum number of recent turns to include
            
        Returns:
            Formatted string of conversation history
        """
        if not self.history:
            return ""
        
        # Get recent turns
        recent_turns = self.history[-max_turns:]
        
        formatted_parts = ["=== CONVERSATION HISTORY ==="]
        for i, turn in enumerate(recent_turns, 1):
            timestamp = turn.get("timestamp", "")
            if timestamp:
                time_str = timestamp.strftime("%H:%M")
            else:
                time_str = ""
            
            question = turn.get("question", "")
            response = turn.get("response", "")
            topic = turn.get("topic", "")
            
            # Truncate long responses for context
            if len(response) > 200:
                response = response[:200] + "..."
            
            formatted_parts.append(f"\n[Turn {i}]{' (' + time_str + ')' if time_str else ''}")
            formatted_parts.append(f"User: {question}")
            formatted_parts.append(f"Assistant: {response}")
            if topic:
                formatted_parts.append(f"Topic: {topic}")
        
        formatted_parts.append("\n=== END HISTORY ===\n")
        
        return "\n".join(formatted_parts)


class IntentClassifier:
    """Classifies user query intent using pattern matching and heuristics"""
    
    # Greeting patterns
    GREETING_PATTERNS = [
        r'\b(hi|hello|hey|greetings|good morning|good afternoon|good evening)\b',
    ]
    
    # Farewell patterns
    FAREWELL_PATTERNS = [
        r'\b(bye|goodbye|see you|farewell|take care|thanks|thank you)\b.*\b(bye|all|done)\b',
        r'\b(that\'s all|that is all|no more|nothing else)\b',
    ]
    
    # Help patterns
    HELP_PATTERNS = [
        r'\b(help|assist|guide|support|tutorial)\b',
        r'\bwhat can (you|i)\b',
        r'\bhow (does|do) (this|it|you) work\b',
        r'\bhow (do|can) i use\b',
        r'\bi need (help|assistance|support)\b',
    ]
    
    # System info patterns
    SYSTEM_INFO_PATTERNS = [
        r'\b(what are you|who are you|what is your (name|role|purpose))\b',
        r'\b(what (do|can) you do|capabilities|features)\b',
        r'\babout (you|yourself|this system)\b',
        r'\b(what is|what\'s) (mpi|this system|the system|mpi backend)\b',
        r'\b(explain|describe) (mpi|the system|this system|mpi backend)\b',
        r'\b(system|application) (overview|info|information)\b',
        r'\b(what can|what does) (mpi|this system|the system|mpi backend) (do|handle)\b',
        r'\b(capabilities|features) (of|for) (mpi|the system|mpi backend)\b',
        r'\b(tell me about|tell me) (mpi|the system|this system|mpi backend)\b',
        r'\b(overview|introduction) (of|to) (mpi|the system|mpi backend)\b',
        r'\b(what is mpi backend|what\'s mpi backend)\b',
    ]
    
    # Capability inquiry patterns
    CAPABILITY_PATTERNS = [
        r'\bcan you\b',
        r'\bare you able to\b',
        r'\bdo you (have|support|know)\b',
        r'\bis it possible\b',
    ]
    
    # Small talk patterns
    SMALL_TALK_PATTERNS = [
        r'\bhow are you\b',
        r'\bhow\'s it going\b',
        r'\bwhat\'s up\b',
    ]
    
    # Database query indicators
    DATABASE_QUERY_INDICATORS = [
        r'\b(show|list|find|get|retrieve|display|count|total|sum)\b',
        r'\b(how many|how much)\b',
        r'\b(invoice|supplier|item|customer|job|export|statement)\b',
        r'\b(where|when|which|what|who)\b.*\b(invoice|supplier|item|customer)\b',
        r'\b(from|in|during|between)\b.*\d{4}',  # Date references
    ]
    
    # Vague action request patterns (requests that need clarification before execution)
    VAGUE_ACTION_PATTERNS = [
        # Export requests without specifics
        r'^export\s*(the\s*)?(data|it|this|them|everything)?\.?$',
        r'^(can you\s+)?(export|download|save)\s*(the\s*)?(data|it|this)?(\s+for me)?\.?$',
        r'^(give|get|show)\s*(me\s+)?(the\s+)?data\.?$',
        r'^download\s*(the\s*)?(data|everything)?\.?$',
        # Very generic show/list requests without filters
        r'^show\s*(me\s+)?(the\s+)?(data|everything|all)\.?$',
        r'^list\s*(the\s+)?(data|everything|all)\.?$',
        r'^get\s*(me\s+)?(the\s+)?(data|everything|all)\.?$',
        # Export to CSV/Excel without specifics
        r'^export\s*(the\s*)?(data\s+)?(to|in|as)\s+(csv|excel|spreadsheet)\.?$',
        r'^(can you\s+)?export\s*(it|data|this)?\s*(to|in|as)?\s*(csv|excel)?\s*(for me)?\.?$',
    ]
    
    # Specific filter indicators (if present, query is NOT vague)
    SPECIFIC_FILTER_INDICATORS = [
        r'\b(from|for|in|during|between|since|after|before)\s+\w+',  # Date/time specifiers
        r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\b',
        r'\b\d{4}\b',  # Year
        r'\b(supplier|vendor)\s+\w+',  # Specific supplier
        r'\b(customer|job)\s+\w+',  # Specific customer/job
        r'\b(invoice|ref)\s*(#|no|number)?\s*\w+',  # Specific invoice/ref
        r'\b(processed|pending|exported|failed)\b',  # Status filters
        r'\b(last|this|past)\s+(week|month|year|quarter)\b',  # Relative time
        r'\b(top|first|latest|recent|oldest)\s+\d+\b',  # Specific counts
    ]
    
    @classmethod
    def classify(cls, question: str, context: Optional[ConversationContext] = None) -> QueryIntent:
        """
        Classify the intent of a user question
        
        Args:
            question (str): User's question
            context (Optional[ConversationContext]): Conversation context
            
        Returns:
            QueryIntent: Classified intent
        """
        question_lower = question.lower().strip()
        
        # Check for greetings first (highest priority for initial contact)
        if cls._matches_patterns(question_lower, cls.GREETING_PATTERNS):
            # If it's just a greeting with no follow-up question
            if len(question_lower.split()) <= 5 and not cls._matches_patterns(
                question_lower, cls.DATABASE_QUERY_INDICATORS
            ):
                return QueryIntent.GREETING
        
        # Check for farewells
        if cls._matches_patterns(question_lower, cls.FAREWELL_PATTERNS):
            return QueryIntent.FAREWELL
        
        # Check for help requests
        if cls._matches_patterns(question_lower, cls.HELP_PATTERNS):
            return QueryIntent.HELP
        
        # Check for system info requests
        if cls._matches_patterns(question_lower, cls.SYSTEM_INFO_PATTERNS):
            return QueryIntent.SYSTEM_INFO
        
        # Check for small talk
        if cls._matches_patterns(question_lower, cls.SMALL_TALK_PATTERNS):
            return QueryIntent.SMALL_TALK
        
        # Check for capability inquiries
        if cls._matches_patterns(question_lower, cls.CAPABILITY_PATTERNS):
            # If it also mentions database entities, it's likely a database query
            if cls._matches_patterns(question_lower, cls.DATABASE_QUERY_INDICATORS):
                return QueryIntent.DATABASE_QUERY
            return QueryIntent.CAPABILITY_INQUIRY
        
        # Check for vague action requests that need clarification
        if cls._is_vague_action_request(question_lower):
            return QueryIntent.ACTION_REQUEST_VAGUE
        
        # Check for database queries
        if cls._matches_patterns(question_lower, cls.DATABASE_QUERY_INDICATORS):
            return QueryIntent.DATABASE_QUERY
        
        # Check if it's a follow-up question (multi-turn)
        if context and context.is_follow_up(question):
            return QueryIntent.MULTI_TURN
        
        # Default to database query if unclear
        # (conservative approach - better to attempt DB query than reject valid question)
        return QueryIntent.DATABASE_QUERY
    
    @classmethod
    def _is_vague_action_request(cls, question: str) -> bool:
        """
        Check if the question is a vague action request that needs clarification
        
        A vague request is one that asks for an action (export, download, show all)
        but doesn't provide specific filters (date, supplier, customer, etc.)
        
        Args:
            question: Lowercased question text
            
        Returns:
            True if the request is vague and needs clarification
        """
        # First check if it matches vague action patterns
        is_action_request = cls._matches_patterns(question, cls.VAGUE_ACTION_PATTERNS)
        
        if not is_action_request:
            # Also check for slightly longer vague requests
            action_keywords = ['export', 'download', 'get data', 'show data', 'give me data', 
                             'extract', 'pull data', 'fetch data', 'dump', 'show everything',
                             'export csv', 'export excel', 'data export', 'export to']
            if any(keyword in question for keyword in action_keywords):
                is_action_request = True
        
        if not is_action_request:
            return False
        
        # Check if it has specific filters - if so, it's NOT vague
        has_specific_filters = cls._matches_patterns(question, cls.SPECIFIC_FILTER_INDICATORS)
        
        # Additional specific indicators check
        specific_words = ['specific', 'particular', 'named', 'called']
        for word in specific_words:
            if word in question:
                has_specific_filters = True
                break
        
        # It's vague if it's an action request WITHOUT specific filters
        return not has_specific_filters
    
    @staticmethod
    def _matches_patterns(text: str, patterns: List[str]) -> bool:
        """Check if text matches any of the given patterns"""
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False


class ConversationalResponseGenerator:
    """Generates conversational responses for non-database queries"""
    
    @staticmethod
    def generate_greeting() -> str:
        """Generate a greeting response"""
        return get_prompt_loader().get_conversational_response('greeting')
    
    @staticmethod
    def generate_farewell() -> str:
        """Generate a farewell response"""
        return get_prompt_loader().get_conversational_response('farewell')
    
    @staticmethod
    def generate_help() -> str:
        """Generate a help response"""
        return get_prompt_loader().get_conversational_response('help')
    
    @staticmethod
    def generate_system_info() -> str:
        """Generate comprehensive system information response"""
        return get_prompt_loader().get_conversational_response('system_info')
    
    @staticmethod
    def generate_small_talk() -> str:
        """Generate small talk response"""
        return get_prompt_loader().get_conversational_response('small_talk')
    
    @staticmethod
    def generate_capability_response(question: str) -> str:
        """Generate response for capability inquiries"""
        question_lower = question.lower()
        
        prompt_loader = get_prompt_loader()
        
        # Specific capability checks
        if 'export' in question_lower or 'quickbooks' in question_lower:
            return prompt_loader.get_conversational_response('capability_export')
        
        elif 'update' in question_lower or 'modify' in question_lower or 'delete' in question_lower:
            return prompt_loader.get_conversational_response('capability_update')
        
        elif 'report' in question_lower or 'analyze' in question_lower:
            return prompt_loader.get_conversational_response('capability_report')
        
        else:
            return prompt_loader.get_conversational_response('capability_default')
    
    @staticmethod
    def generate_clarification_request(context: Optional[ConversationContext] = None) -> str:
        """Generate a clarification request"""
        prompt_loader = get_prompt_loader()
        
        if context and context.last_topic:
            topic_hints = {
                "invoices": "clarification_invoices",
                "suppliers": "clarification_suppliers",
                "items": "clarification_items",
                "customer_jobs": "clarification_customer_jobs",
            }
            
            hint_key = topic_hints.get(context.last_topic)
            if hint_key:
                return prompt_loader.get_conversational_response(hint_key)
        
        return prompt_loader.get_conversational_response('clarification_default')
    
    @staticmethod
    def generate_vague_action_clarification(question: str, context: Optional[ConversationContext] = None) -> str:
        """
        Generate a clarification response for vague action requests
        
        This method creates a conversational response asking the user for more 
        specific details before executing a vague action like "export data".
        
        Args:
            question: The original user question
            context: Optional conversation context
            
        Returns:
            A friendly clarification request asking for more details
        """
        prompt_loader = get_prompt_loader()
        question_lower = question.lower()
        
        # Check what type of action is being requested
        if any(word in question_lower for word in ['export', 'download', 'csv', 'excel', 'spreadsheet']):
            return prompt_loader.get_conversational_response('clarification_export')
        
        elif 'data' in question_lower or 'everything' in question_lower or 'all' in question_lower:
            return prompt_loader.get_conversational_response('clarification_data_request')
        
        # Default clarification
        return prompt_loader.get_conversational_response('clarification_action_default')


class ConversationManager:
    """Main conversation management class"""
    
    def __init__(self):
        self.contexts: Dict[str, ConversationContext] = {}
        self.intent_classifier = IntentClassifier()
    
    def get_or_create_context(self, session_id: str = "default") -> ConversationContext:
        """Get or create conversation context for a session"""
        if session_id not in self.contexts:
            self.contexts[session_id] = ConversationContext()
        return self.contexts[session_id]
    
    def clear_context(self, session_id: str = "default"):
        """Clear conversation context for a session"""
        if session_id in self.contexts:
            del self.contexts[session_id]
    
    def classify_and_respond(
        self,
        question: str,
        session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Classify intent and generate appropriate response
        
        Args:
            question (str): User's question
            session_id (str): Session identifier
            
        Returns:
            Dict with intent, needs_database, response (if conversational), 
            conversation_history (formatted string)
        """
        context = self.get_or_create_context(session_id)
        intent = self.intent_classifier.classify(question, context)
        
        logger.info(f"Classified intent: {intent.value} for question: {question[:50]}...")
        
        # Determine if database query is needed
        # Multi-turn queries and specific database queries need database access
        needs_database = intent in [QueryIntent.DATABASE_QUERY, QueryIntent.MULTI_TURN]
        
        # Generate conversational response if not a database query
        conversational_response = None
        if not needs_database:
            if intent == QueryIntent.GREETING:
                conversational_response = ConversationalResponseGenerator.generate_greeting()
            elif intent == QueryIntent.FAREWELL:
                conversational_response = ConversationalResponseGenerator.generate_farewell()
            elif intent == QueryIntent.HELP:
                conversational_response = ConversationalResponseGenerator.generate_help()
            elif intent == QueryIntent.SYSTEM_INFO:
                conversational_response = ConversationalResponseGenerator.generate_system_info()
            elif intent == QueryIntent.SMALL_TALK:
                conversational_response = ConversationalResponseGenerator.generate_small_talk()
            elif intent == QueryIntent.CAPABILITY_INQUIRY:
                conversational_response = ConversationalResponseGenerator.generate_capability_response(question)
            elif intent == QueryIntent.CLARIFICATION:
                conversational_response = ConversationalResponseGenerator.generate_clarification_request(context)
            elif intent == QueryIntent.ACTION_REQUEST_VAGUE:
                # Vague action requests need clarification before execution
                conversational_response = ConversationalResponseGenerator.generate_vague_action_clarification(
                    question, context
                )
        
        # Get formatted conversation history for LLM context
        conversation_history = context.get_formatted_history()
        
        return {
            "intent": intent.value,
            "needs_database": needs_database,
            "conversational_response": conversational_response,
            "context": context,
            "conversation_history": conversation_history
        }
    
    def add_to_history(
        self,
        session_id: str,
        question: str,
        intent: QueryIntent,
        response: str,
        sql_query: Optional[str] = None
    ):
        """Add interaction to conversation history"""
        context = self.get_or_create_context(session_id)
        context.add_turn(question, intent, response, sql_query)


# Global conversation manager instance
_conversation_manager = None


def get_conversation_manager() -> ConversationManager:
    """Get or create ConversationManager instance (singleton pattern)"""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
    return _conversation_manager

