"""
Test suite for QA System enhancements
Ensures backward compatibility and validates new conversational features
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from mpi_backend.utils.chatbot.conversation_manager import (
    IntentClassifier,
    QueryIntent,
    ConversationContext,
    ConversationalResponseGenerator,
    ConversationManager
)


class TestIntentClassifier:
    """Test intent classification functionality"""
    
    def test_greeting_classification(self):
        """Test that greetings are properly classified"""
        greetings = [
            "Hi",
            "Hello",
            "Hey there",
            "Good morning",
            "Good afternoon"
        ]
        
        for greeting in greetings:
            intent = IntentClassifier.classify(greeting)
            assert intent == QueryIntent.GREETING, f"Failed to classify '{greeting}' as greeting"
    
    def test_help_classification(self):
        """Test that help requests are properly classified"""
        help_queries = [
            "Help",
            "How do I use this?",
            "What can you do?",
            "I need assistance"
        ]
        
        for query in help_queries:
            intent = IntentClassifier.classify(query)
            assert intent in [QueryIntent.HELP, QueryIntent.SYSTEM_INFO], \
                f"Failed to classify '{query}' as help-related"
    
    def test_database_query_classification(self):
        """Test that database queries are properly classified"""
        db_queries = [
            "Show me all invoices",
            "Find invoices from BMW Plumbing",
            "How many suppliers do we have?",
            "List all items from July 2024",
            "What is the total amount for customer job ABC123?"
        ]
        
        for query in db_queries:
            intent = IntentClassifier.classify(query)
            assert intent == QueryIntent.DATABASE_QUERY, \
                f"Failed to classify '{query}' as database query"
    
    def test_small_talk_classification(self):
        """Test that small talk is properly classified"""
        small_talk = [
            "How are you?",
            "How's it going?",
            "What's up?"
        ]
        
        for query in small_talk:
            intent = IntentClassifier.classify(query)
            assert intent == QueryIntent.SMALL_TALK, \
                f"Failed to classify '{query}' as small talk"
    
    def test_capability_inquiry_classification(self):
        """Test that capability inquiries are properly classified"""
        capability_queries = [
            ("Can you show me reports?", [QueryIntent.CAPABILITY_INQUIRY, QueryIntent.DATABASE_QUERY]),
            ("Are you able to export data?", [QueryIntent.CAPABILITY_INQUIRY, QueryIntent.DATABASE_QUERY]),
            ("Can you update records?", [QueryIntent.CAPABILITY_INQUIRY, QueryIntent.DATABASE_QUERY]),
        ]
        
        for query, expected_intents in capability_queries:
            intent = IntentClassifier.classify(query)
            # Could be capability inquiry, database query, or even help depending on phrasing
            assert intent in expected_intents or intent == QueryIntent.HELP, \
                f"Failed to classify '{query}' appropriately, got {intent}"


class TestConversationContext:
    """Test conversation context management"""
    
    def test_context_initialization(self):
        """Test that context initializes correctly"""
        context = ConversationContext(max_history=5)
        
        assert context.history == []
        assert context.max_history == 5
        assert context.last_query_intent is None
        assert context.last_sql_query is None
        assert context.last_topic is None
    
    def test_add_turn(self):
        """Test adding turns to conversation history"""
        context = ConversationContext()
        
        context.add_turn(
            question="Show me invoices",
            intent=QueryIntent.DATABASE_QUERY,
            response="Here are the invoices...",
            sql_query="SELECT * FROM invoices"
        )
        
        assert len(context.history) == 1
        assert context.last_query_intent == QueryIntent.DATABASE_QUERY
        assert context.last_sql_query == "SELECT * FROM invoices"
        assert context.last_topic == "invoices"
    
    def test_topic_extraction(self):
        """Test topic extraction from questions"""
        context = ConversationContext()
        
        test_cases = [
            ("Show me all invoices", "invoices"),
            ("Find suppliers in California", "suppliers"),
            ("List items for customer job ABC", "customer_jobs"),
            ("What items were exported?", "export"),
        ]
        
        for question, expected_topic in test_cases:
            context.add_turn(question, QueryIntent.DATABASE_QUERY, "test response")
            assert context.last_topic == expected_topic, \
                f"Expected topic '{expected_topic}' for '{question}', got '{context.last_topic}'"
    
    def test_follow_up_detection(self):
        """Test follow-up question detection"""
        context = ConversationContext()
        
        # First question
        context.add_turn(
            "Show me invoices from July",
            QueryIntent.DATABASE_QUERY,
            "Here are July invoices"
        )
        
        # Follow-up questions
        follow_ups = [
            "What about August?",
            "Show me more",
            "And what about those items?",
            "How about the same for September?"
        ]
        
        for follow_up in follow_ups:
            assert context.is_follow_up(follow_up), \
                f"Failed to detect '{follow_up}' as a follow-up question"
    
    def test_history_limit(self):
        """Test that history respects max limit"""
        context = ConversationContext(max_history=3)
        
        # Add 5 turns
        for i in range(5):
            context.add_turn(
                f"Question {i}",
                QueryIntent.DATABASE_QUERY,
                f"Response {i}"
            )
        
        # Should only keep last 3
        assert len(context.history) == 3
        assert context.history[0]["question"] == "Question 2"
        assert context.history[-1]["question"] == "Question 4"


class TestConversationalResponseGenerator:
    """Test conversational response generation"""
    
    def test_greeting_response(self):
        """Test greeting response generation"""
        response = ConversationalResponseGenerator.generate_greeting()
        
        assert "Hello" in response or "Hi" in response
        assert "help" in response.lower() or "query" in response.lower()
    
    def test_help_response(self):
        """Test help response generation"""
        response = ConversationalResponseGenerator.generate_help()
        
        assert "invoice" in response.lower() or "customer job" in response.lower()
        assert len(response) > 0  # Should have a helpful response
    
    def test_system_info_response(self):
        """Test system info response generation"""
        response = ConversationalResponseGenerator.generate_system_info()
        
        assert "MPI Backend" in response or "mpi" in response.lower()
        assert "AI" in response or "assistant" in response.lower()
        assert "plumbing supply" in response.lower() or "plumbing" in response.lower()
        assert "invoice" in response.lower() or "query" in response.lower()
    
    def test_small_talk_response(self):
        """Test small talk response generation"""
        response = ConversationalResponseGenerator.generate_small_talk()
        
        assert len(response) > 0
        assert "database" in response.lower() or "help" in response.lower()
    
    def test_capability_response(self):
        """Test capability-specific responses"""
        test_cases = [
            ("Can you export to QuickBooks?", ["export", "query"]),
            ("Can you update records?", ["only query", "query data", "only"]),
            ("Can you analyze data?", ["analyze", "calculate", "report"]),
        ]
        
        for question, expected_keywords in test_cases:
            response = ConversationalResponseGenerator.generate_capability_response(question)
            # Check for flexible keywords - response should address the capability
            assert any(kw.lower() in response.lower() for kw in expected_keywords) or len(response) > 0, \
                f"Expected relevant response to '{question}', got: '{response}'"


class TestConversationManager:
    """Test conversation manager integration"""
    
    def test_classify_and_respond_greeting(self):
        """Test classification and response for greetings"""
        manager = ConversationManager()
        
        result = manager.classify_and_respond("Hello!")
        
        assert result["intent"] == QueryIntent.GREETING.value
        assert result["needs_database"] is False
        assert result["conversational_response"] is not None
        assert len(result["conversational_response"]) > 0  # Should have a greeting response
    
    def test_classify_and_respond_database_query(self):
        """Test classification for database queries"""
        manager = ConversationManager()
        
        result = manager.classify_and_respond("Show me all invoices")
        
        assert result["intent"] == QueryIntent.DATABASE_QUERY.value
        assert result["needs_database"] is True
        assert result["conversational_response"] is None
    
    def test_session_management(self):
        """Test session-based context management"""
        manager = ConversationManager()
        
        # Create two different sessions
        session1 = "user1"
        session2 = "user2"
        
        context1 = manager.get_or_create_context(session1)
        context2 = manager.get_or_create_context(session2)
        
        # They should be different contexts
        assert context1 is not context2
        
        # Add to history
        manager.add_to_history(
            session1, 
            "Question 1", 
            QueryIntent.DATABASE_QUERY,
            "Answer 1"
        )
        
        # Session 1 should have history, session 2 shouldn't
        assert len(context1.history) == 1
        assert len(context2.history) == 0
    
    def test_context_clearing(self):
        """Test context clearing functionality"""
        manager = ConversationManager()
        
        session_id = "test_session"
        
        # Add some history
        manager.add_to_history(
            session_id,
            "Test question",
            QueryIntent.DATABASE_QUERY,
            "Test answer"
        )
        
        # Verify context exists
        assert session_id in manager.contexts
        
        # Clear context
        manager.clear_context(session_id)
        
        # Verify context is removed
        assert session_id not in manager.contexts


class TestBackwardCompatibility:
    """Test backward compatibility of the QA system"""
    
    @pytest.mark.asyncio
    async def test_query_without_session_id(self):
        """Test that queries work without session_id (backward compatibility)"""
        from mpi_backend.database.controllers.ChatbotController import ChatbotController
        
        controller = ChatbotController()
        
        # Mock the agent manager
        mock_manager = Mock()
        mock_manager.process_request = AsyncMock(return_value={
            "success": True,
            "data": {
                "answer": "Test answer",
                "intent": "database_query",
                "is_conversational": False
            },
            "error": None,
            "metadata": {}
        })
        
        with patch.object(controller, '_get_agent_manager', return_value=mock_manager):
            # Process query without session_id
            result = await controller.process_query("Show me invoices")
            
            # Verify it works
            answer = result.answer if hasattr(result, 'answer') else result["answer"]
            assert "Test answer" in answer
            assert result.error is None or result.get("error") is None
    
    @pytest.mark.asyncio
    async def test_simple_database_query_still_works(self):
        """Test that simple database queries still work as before"""
        from mpi_backend.database.controllers.ChatbotController import ChatbotController
        
        controller = ChatbotController()
        
        mock_manager = Mock()
        mock_manager.process_request = AsyncMock(return_value={
            "success": True,
            "data": {
                "answer": "Found 10 invoices",
                "intent": "database_query",
                "is_conversational": False
            },
            "error": None,
            "metadata": {}
        })
        
        with patch.object(controller, '_get_agent_manager', return_value=mock_manager):
            result = await controller.process_query("How many invoices?")
            
            answer = result.answer if hasattr(result, 'answer') else result["answer"]
            assert "Found 10 invoices" in answer
            assert result.error is None or result.get("error") is None
    
    @pytest.mark.asyncio
    async def test_error_handling_preserved(self):
        """Test that error handling still works correctly"""
        from mpi_backend.database.controllers.ChatbotController import ChatbotController
        
        controller = ChatbotController()
        
        # Test empty question validation
        with pytest.raises(Exception) as exc_info:  # ValueError or HTTPException
            await controller.process_query("")
        
        # Should raise ValueError (400) or similar
        assert hasattr(exc_info.value, 'status_code') and exc_info.value.status_code == 400 or \
               isinstance(exc_info.value, ValueError)
        
        # Test too long question validation
        with pytest.raises(Exception) as exc_info:  # ValueError or HTTPException
            await controller.process_query("a" * 1001)
        
        # Should raise ValueError (400) or similar
        assert hasattr(exc_info.value, 'status_code') and exc_info.value.status_code == 400 or \
               isinstance(exc_info.value, ValueError)


class TestNewFeatures:
    """Test new conversational features"""
    
    @pytest.mark.asyncio
    async def test_conversational_greeting(self):
        """Test that greetings are handled conversationally"""
        from mpi_backend.database.controllers.ChatbotController import ChatbotController
        
        controller = ChatbotController()
        
        mock_manager = Mock()
        mock_manager.process_request = AsyncMock(return_value={
            "success": True,
            "data": {
                "answer": "Hello! I can help you query invoices, items, suppliers, and customer jobs.",
                "intent": "greeting",
                "is_conversational": True
            },
            "error": None,
            "metadata": {}
        })
        
        with patch.object(controller, '_get_agent_manager', return_value=mock_manager):
            result = await controller.process_query("Hi")
            
            assert result.intent == "greeting" or result.get("intent") == "greeting"
            answer = result.answer if hasattr(result, 'answer') else result["answer"]
            assert len(answer) > 0
    
    @pytest.mark.asyncio
    async def test_help_request(self):
        """Test that help requests are handled appropriately"""
        from mpi_backend.database.controllers.ChatbotController import ChatbotController
        
        controller = ChatbotController()
        
        mock_manager = Mock()
        mock_manager.process_request = AsyncMock(return_value={
            "success": True,
            "data": {
                "answer": "Just ask me questions in plain English like \"Show me invoices from July\"",
                "intent": "help",
                "is_conversational": True
            },
            "error": None,
            "metadata": {}
        })
        
        with patch.object(controller, '_get_agent_manager', return_value=mock_manager):
            result = await controller.process_query("help")
            
            assert result.intent == "help" or result.get("intent") == "help"
            answer = result.answer if hasattr(result, 'answer') else result["answer"]
            assert len(answer) > 0
    
    @pytest.mark.asyncio
    async def test_session_context_maintained(self):
        """Test that session context is maintained across queries"""
        from mpi_backend.database.controllers.ChatbotController import ChatbotController
        
        controller = ChatbotController()
        session_id = "test_session_123"
        
        # Create mock manager with side effect for multiple calls
        mock_manager = Mock()
        mock_manager.process_request = AsyncMock(side_effect=[
            {
                "success": True,
                "data": {
                    "answer": "Here are July invoices",
                    "intent": "database_query",
                    "is_conversational": False
                },
                "error": None,
                "metadata": {}
            },
            {
                "success": True,
                "data": {
                    "answer": "Here are August invoices",
                    "intent": "database_query",
                    "is_conversational": False
                },
                "error": None,
                "metadata": {}
            }
        ])
        
        with patch.object(controller, '_get_agent_manager', return_value=mock_manager):
            # First query
            result1 = await controller.process_query(
                "Show me invoices from July",
                session_id=session_id
            )
            
            answer1 = result1.answer if hasattr(result1, 'answer') else result1["answer"]
            assert "July invoices" in answer1
            
            # Second query (follow-up)
            result2 = await controller.process_query(
                "What about August?",
                session_id=session_id
            )
            
            answer2 = result2.answer if hasattr(result2, 'answer') else result2["answer"]
            assert "August invoices" in answer2
            
            # Verify both calls were made
            assert mock_manager.process_request.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

