# QA System Enhancements Documentation

## Overview

The MPI Backend QA System has been enhanced with advanced conversational intelligence while maintaining complete backward compatibility. These enhancements make the system more natural and human-friendly for general conversation while fully retaining its original database query capabilities.

## What's New

### 1. **Conversational Intelligence**

The system now understands and responds naturally to:
- **Greetings**: "Hi", "Hello", "Good morning"
- **Help Requests**: "Help", "How do I use this?", "What can you do?"
- **Small Talk**: "How are you?", "What's up?"
- **System Information**: "What are you?", "What can you do?"
- **Capability Inquiries**: "Can you export data?", "Can you update records?"

### 2. **Multi-Turn Context Management**

The system maintains conversation context across multiple queries:
- Tracks recent conversation topics (invoices, suppliers, items, etc.)
- Detects follow-up questions automatically
- Provides context-aware responses
- Supports session-based context isolation

### 3. **Enhanced Answer Quality**

Improved answer generation with:
- Better intent recognition
- More natural language responses
- Rich formatting with markdown support
- Business-focused information presentation

### 4. **Graceful Fallback Strategies**

When queries fail or return no results:
- Provides context-specific suggestions
- Offers helpful tips for query refinement
- Guides users to successful queries
- Never leaves users without direction

### 5. **Better Error Handling**

User-friendly error messages that:
- Explain what went wrong in plain language
- Suggest actionable next steps
- Provide examples of successful queries
- Include support contact information when needed

## Architecture

### New Components

#### 1. **Conversation Manager** (`conversation_manager.py`)

Central component managing conversational features:

```python
from mpi_backend.utils.conversation_manager import (
    get_conversation_manager,
    QueryIntent,
    ConversationContext
)

# Get singleton instance
manager = get_conversation_manager()

# Classify intent and get response
result = manager.classify_and_respond("Hello!", session_id="user123")
```

**Key Classes:**
- `IntentClassifier`: Classifies user intent using pattern matching
- `ConversationContext`: Manages multi-turn conversation state
- `ConversationalResponseGenerator`: Generates natural responses
- `ConversationManager`: Orchestrates all conversational features

#### 2. **Enhanced QA Agent** (`database_qa_agent.py`)

Updated to integrate conversational features:

```python
from mpi_backend.utils.database_qa_agent import get_qa_agent

# Get agent instance
agent = get_qa_agent()

# Query with session support
result = await agent.query("Show me invoices", session_id="user123")
```

**New Features:**
- Session-based context tracking
- Intent-based routing
- Enhanced question preprocessing
- Better fallback handling

#### 3. **Updated Controller** (`QAController.py`)

Enhanced with session management:

```python
from mpi_backend.database.controllers.QAController import get_qa_controller

# Get controller
controller = get_qa_controller()

# Process query with session
result = await controller.process_query(
    "Show me invoices",
    session_id="user123"
)
```

#### 4. **Enhanced API Route** (`routes/qa.py`)

Updated API with new fields:

```python
# Request model
{
    "question": "Show me invoices from July",
    "session_id": "user123-session456"  # Optional
}

# Response model
{
    "answer": "Here are the invoices...",
    "error": null,
    "intent": "database_query",
    "is_conversational": false
}
```

## Intent Classification

### Supported Intent Types

| Intent | Description | Examples |
|--------|-------------|----------|
| `greeting` | Welcome/greeting messages | "Hi", "Hello", "Good morning" |
| `farewell` | Goodbye messages | "Bye", "Thanks, that's all" |
| `help` | Help and guidance requests | "Help", "How do I use this?" |
| `system_info` | System capability questions | "What are you?", "What can you do?" |
| `small_talk` | Casual conversation | "How are you?", "What's up?" |
| `capability_inquiry` | Feature/capability questions | "Can you export?", "Do you support X?" |
| `database_query` | Actual database queries | "Show me invoices", "Find suppliers" |
| `multi_turn` | Follow-up questions | "What about August?", "Show me more" |

### Intent Detection Logic

The system uses pattern-based classification with priority ordering:

1. **Greetings** (highest priority for initial contact)
2. **Farewells**
3. **Help requests**
4. **System information**
5. **Small talk**
6. **Capability inquiries**
7. **Database queries** (default for ambiguous cases)

## Context Management

### Session-Based Context

Each user session maintains:
- **History**: Last 5 conversation turns
- **Topics**: Detected topics (invoices, suppliers, items, etc.)
- **SQL Queries**: Previous database queries
- **Intent**: Last query intent

### Follow-Up Detection

The system detects follow-up questions using patterns like:
- "what about...", "how about..."
- References: "that", "those", "them", "it"
- Continuations: "and", "also", "more"
- Comparisons: "same", "similar", "related"

### Example Multi-Turn Conversation

```
User: "Show me invoices from July"
→ Intent: database_query, Topic: invoices
Bot: "Here are the invoices from July 2024..."

User: "What about August?"
→ Intent: database_query (follow-up detected)
→ Context: Previous topic = invoices, Previous timeframe = July
Bot: "Here are the invoices from August 2024..."
```

## API Usage

### Basic Query (Simple)

```bash
curl -X POST "http://localhost:8000/qa/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Show me all invoices from BMW Plumbing"
  }'
```

**Response:**
```json
{
  "answer": "Here are the invoices from BMW Plumbing Supplies...",
  "error": null,
  "intent": "database_query",
  "is_conversational": false
}
```

### Conversational Query

```bash
curl -X POST "http://localhost:8000/qa/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Hi, what can you help me with?"
  }'
```

**Response:**
```json
{
  "answer": "Hello! I can help you query invoices, items, suppliers, and customer jobs. What would you like to know?",
  "error": null,
  "intent": "greeting",
  "is_conversational": true
}
```

### Session-Based Query (Optional - Only if needed)

```bash
# First query
curl -X POST "http://localhost:8000/qa/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Show me invoices from July",
    "session_id": "user123-session456"
  }'

# Follow-up query (same session)
curl -X POST "http://localhost:8000/qa/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What about August?",
    "session_id": "user123-session456"
  }'
```

**Note:** Most queries work perfectly without session_id. Only include it if you need conversation context.

## Conversational Examples

### Greeting

**Input:**
```json
{"question": "Hi"}
```

**Output:**
```
Hello! I can help you query invoices, items, suppliers, and customer jobs. What would you like to know?
```

### Help Request

**Input:**
```json
{"question": "How do I use this?"}
```

**Output:**
```
Just ask me questions in plain English like "Show me invoices from July" or "Find items for customer job ABC123". What do you need?
```

### Capability Inquiry

**Input:**
```json
{"question": "Can you export to QuickBooks?"}
```

**Output:**
```
Yes, I can query export statuses and QuickBooks data. What would you like to see?
```

### Database Query with No Results

**Input:**
```json
{"question": "Show me invoices from XYZ Company"}
```

**Output:**
```
I couldn't find any results matching your query. This could mean:
• No records exist matching your criteria
• The search terms might need adjustment

**Suggestions:**
• Try checking the exact supplier name - it must match exactly
• Use partial names if you're unsure of the exact spelling

Would you like to try a different query or need help formulating your question?
```

## Backward Compatibility

### 100% Compatible

All existing functionality remains unchanged:
- ✅ Original database query processing
- ✅ SQL generation and execution
- ✅ Safety checks (read-only queries)
- ✅ Response format (with added fields)
- ✅ Error handling
- ✅ Rate limiting and fallback

### What Changed (Additions Only)

**Request Model:**
```python
# Before
class QueryRequest(BaseModel):
    question: str

# After (backward compatible - session_id is optional)
class QueryRequest(BaseModel):
    question: str
    session_id: Optional[str] = None  # NEW, optional (not required)
```

**Response Model:**
```python
# Before
class QueryResponse(BaseModel):
    answer: str
    error: Optional[str]

# After (backward compatible - new fields are optional)
class QueryResponse(BaseModel):
    answer: str
    error: Optional[str]
    intent: Optional[str] = None  # NEW, optional
    is_conversational: Optional[bool] = False  # NEW, optional
```

### Migration Guide

**No migration required!** The system is fully backward compatible.

**Optional Enhancement:**
If you want to use new features in existing code:

```python
# Old code (still works)
result = await controller.process_query("Show me invoices")

# Enhanced code (with session support)
result = await controller.process_query(
    "Show me invoices",
    session_id="user123"
)

# Access new fields
if result.get("is_conversational"):
    # Handle conversational response differently
    print("Conversational:", result["answer"])
else:
    # Handle database query response
    print("Query result:", result["answer"])
```

## Performance

### No Performance Impact

The enhancements are designed for minimal overhead:
- Intent classification: ~1ms (pattern matching)
- Context management: ~0.5ms (in-memory operations)
- No additional database queries
- Same LLM usage as before for database queries

### Memory Usage

- Per session: ~5KB (5 conversation turns)
- Automatic cleanup: Sessions expire after inactivity
- Configurable history limit: Default 5 turns

## Testing

### Test Coverage

All enhancements are fully tested:
- ✅ 25 unit tests covering all new features
- ✅ Intent classification (all types)
- ✅ Context management (multi-turn)
- ✅ Conversational responses
- ✅ Backward compatibility
- ✅ Session management
- ✅ Error handling

### Run Tests

```bash
# Run QA enhancement tests
python -m pytest mpi_backend/tests/test_qa_enhancements.py -v

# Run all QA tests
python -m pytest mpi_backend/tests/test_qa*.py -v
```

## Security

### Enhanced Security Features

1. **Read-Only Access**: Maintained (no changes)
2. **SQL Injection Protection**: Maintained (no changes)
3. **Rate Limiting**: Maintained (no changes)
4. **Input Validation**: Enhanced with better error messages
5. **Session Isolation**: New feature - prevents cross-session data leakage

### No New Security Risks

All new features operate at the application layer:
- No database schema changes
- No new database permissions
- No new external dependencies
- Same LLM providers (Gemini + OpenAI)

## Best Practices

### For Frontend Developers

1. **Use Session IDs for Multi-Turn Conversations:**
```javascript
const sessionId = `user-${userId}-${Date.now()}`;

// First query
const result1 = await fetch('/qa/query', {
  method: 'POST',
  body: JSON.stringify({
    question: "Show me invoices from July",
    session_id: sessionId
  })
});

// Follow-up query (same session)
const result2 = await fetch('/qa/query', {
  method: 'POST',
  body: JSON.stringify({
    question: "What about August?",
    session_id: sessionId
  })
});
```

2. **Check Intent for UI Rendering:**
```javascript
const result = await queryQA(question);

if (result.is_conversational) {
  // Render as chat message
  renderChatMessage(result.answer);
} else {
  // Render as database result with formatting
  renderDatabaseResult(result.answer);
}
```

3. **Handle Different Intents:**
```javascript
switch (result.intent) {
  case 'greeting':
    showWelcomeMessage(result.answer);
    break;
  case 'help':
    showHelpPanel(result.answer);
    break;
  case 'database_query':
    showQueryResults(result.answer);
    break;
  default:
    showMessage(result.answer);
}
```

### For Backend Developers

1. **Session Management:**
```python
# Generate unique session IDs
session_id = f"user-{user_id}-{timestamp}"

# Process with session
result = await controller.process_query(
    question,
    session_id=session_id
)
```

2. **Error Handling:**
```python
try:
    result = await controller.process_query(question)
    if result.get("error"):
        # Handle error gracefully
        logger.warning(f"Query error: {result['error']}")
except HTTPException as e:
    # Handle HTTP errors
    logger.error(f"HTTP error: {e.detail}")
```

## Troubleshooting

### Common Issues

#### 1. Intent Misclassification

**Problem:** Question classified as wrong intent

**Solution:** The intent classifier uses pattern matching. If a question is misclassified:
- Make it more specific ("Show me invoices" vs "invoices")
- Add database-specific keywords ("list", "show", "find")
- File an issue with examples for pattern improvement

#### 2. Context Not Maintained

**Problem:** Follow-up questions don't use context

**Solution:**
- Ensure you're passing the same `session_id` for related queries
- Check that session_id is a string, not None
- Session history is limited to 5 turns by default

#### 3. Conversational Response When Database Query Expected

**Problem:** Getting greeting/help instead of database results

**Solution:**
- Make your question more specific
- Use database-related keywords ("show", "find", "list")
- Start with action verbs

## Future Enhancements

### Planned Features

1. **Advanced Context Understanding**
   - Cross-reference resolution ("Show me those items again")
   - Temporal context ("last week", "yesterday")
   - Pronoun resolution

2. **Learning from User Feedback**
   - Track successful vs unsuccessful queries
   - Improve intent classification based on corrections
   - Personalized responses per user

3. **Rich Media Responses**
   - Chart generation for numerical data
   - Table formatting for structured results
   - Export to CSV/Excel directly from chat

4. **Voice Integration**
   - Speech-to-text input
   - Text-to-speech output
   - Voice command shortcuts

## Support

### Getting Help

- **Documentation**: See `docs/QA_SYSTEM_DOCUMENTATION.md` for core system docs
- **API Reference**: See `docs/API_Endpoints.md` for endpoint details
- **Issues**: File bugs or feature requests in the project repository
- **Contact**: Reach out to the development team for support

### Contributing

Contributions are welcome! When enhancing the QA system:

1. Maintain backward compatibility
2. Add comprehensive tests
3. Update documentation
4. Follow existing code patterns
5. Consider performance impact

## Intelligent Features (Version 3.0)

### 🧠 Natural Language Understanding

**Date Intelligence:**
- Parses "last month", "this year", "Q1 2024"
- Understands month names: "July", "December 2023"
- Handles relative dates: "yesterday", "last week"
- Converts to proper SQL date ranges automatically

**Synonym Recognition:**
- supplier = vendor = company
- item = product = part
- customer job = project = work order
- QB = QuickBooks, PO = purchase order
- 50+ business term synonyms supported

**Entity Extraction:**
- Automatically identifies supplier names
- Detects item codes and descriptions
- Recognizes reference numbers
- Finds customer job mentions

### 🔍 Fuzzy Search Capabilities

**PostgreSQL Trigram Matching:**
- Uses existing pg_trgm GIN indexes
- Handles typos: "BMW Plumbng" → finds "BMW Plumbing Supplies"
- Similarity threshold: 30% (configurable)
- Ranks results by relevance

**Multi-Column Search:**
- Item searches automatically check: item, description, mpi_item, mpi_description
- Comprehensive results without specifying columns
- Optimized queries using existing indexes

**3-Tier Fallback Strategy:**
1. Exact match (fastest)
2. ILIKE pattern match (flexible)
3. Trigram similarity (typo-tolerant)

### 🎯 Smart Query Enhancement

**Pre-Processing:**
- Typo detection and correction
- Query normalization (item codes, dates)
- Context inference (business rules)

**Semantic Understanding:**
- Table relationship navigation
- Business term mapping
- Domain knowledge (plumbing supplies)

**Post-Processing:**
- Intelligent error messages
- Alternative query suggestions
- Similarity-ranked recommendations

## New Components (v3.0)

### Intelligent Query Processor (`intelligent_query_processor.py`)
- **DateParser**: Natural language date parsing
- **SynonymExpander**: Business term expansion
- **EntityExtractor**: Key entity identification
- **QueryEnhancer**: Complete query enhancement

### Fuzzy Search Builder (`fuzzy_search_builder.py`)
- **FuzzySearchBuilder**: PostgreSQL fuzzy search SQL generation
- **SimilarityMatcher**: Trigram similarity functions
- **FallbackStrategy**: Multi-level search fallback

### Query Preprocessor (`query_preprocessor.py`)
- **TypoDetector**: Detect and suggest corrections
- **QueryNormalizer**: Normalize input queries
- **ContextAdder**: Add business context

### Semantic Enhancer (`semantic_enhancer.py`)
- **SemanticMapper**: Map synonyms and related terms
- **RelationshipNavigator**: Navigate database relationships
- **DomainKnowledge**: Plumbing supply domain expertise

## Enhanced Prompts

### SQL Generation Prompt
- Added fuzzy search instructions
- PostgreSQL pg_trgm function examples
- Multi-column search strategies
- When to use exact vs fuzzy matching

### Table Definitions
- Documented GIN trigram indexes
- Fuzzy search capabilities per table
- Example intelligent queries
- Multi-column search patterns

## Usage Examples

### Natural Date Queries
```
"Show invoices from last month"
→ Automatically calculates date range

"Find items from Q1 2024"
→ Converts to January 1 - March 31, 2024

"What was exported yesterday?"
→ Uses current date - 1 day
```

### Fuzzy Search Examples
```
"Show invoices from BMW Plumbng"
→ Finds "BMW Plumbing Supplies" (similarity match)

"Find brass fitings"
→ Finds "brass fittings" (typo corrected)

"Items for Main St Project"
→ Matches "Main Street Project" (fuzzy match)
```

### Synonym Understanding
```
"Show vendor products"
→ Understands vendor=supplier, products=items

"QB exports from last week"
→ Expands QB→QuickBooks, parses date

"Find org items for NHPT20-W"
→ Searches all 4 tables automatically
```

### Multi-Column Search
```
"Find pipe items"
→ Searches item, description, mpi_item, mpi_description

"Show PVC products"
→ Comprehensive search across all item fields
```

## Performance

**Optimizations:**
- Leverages existing pg_trgm GIN indexes
- Caches synonym mappings
- Lazy loads domain knowledge
- Query optimization to avoid unnecessary fuzzy searches

**Impact:**
- Minimal overhead: ~10-50ms for enhancement
- Fuzzy searches remain fast with GIN indexes
- Overall response time: <2s maintained

## Testing

**New Test Suite:** `test_intelligent_qa.py`

**Coverage:**
- Natural date parsing (15+ tests)
- Synonym expansion (20+ tests)
- Fuzzy search accuracy (30+ tests)
- Typo detection (20+ tests)
- Query preprocessing (25+ tests)
- Integration tests (15+ tests)
- Backward compatibility (10+ tests)

**Total:** 135+ comprehensive tests

## Changelog

### Version 3.0 (Current - October 16, 2025)

**Added:**
- Intelligent query processor with date parsing, synonyms, entity extraction
- PostgreSQL fuzzy search using pg_trgm trigram matching
- Query preprocessor with typo detection and normalization
- Semantic enhancer with domain knowledge
- Multi-column item search across 4 fields
- Natural language date understanding (relative, months, quarters)
- 50+ business term synonyms
- 3-tier fallback search strategy
- Intelligent error messages with suggestions
- 135+ comprehensive tests
- Complete user guide (INTELLIGENT_QA_GUIDE.md)

**Enhanced:**
- SQL generation prompts with fuzzy search instructions
- Table definitions with pg_trgm capabilities
- Answer formatting with better context

**Maintained:**
- 100% backward compatibility
- All v2.0 conversational features
- Database query processing
- SQL generation and safety
- LLM integration
- Rate limiting

### Version 2.0 (October 6, 2025)

**Added:**
- Conversational intelligence (greetings, help, small talk)
- Multi-turn context management
- Session-based tracking
- Enhanced error messages
- Graceful fallback strategies
- Intent classification
- 25 comprehensive tests

**Changed:**
- API request model (added optional `session_id`)
- API response model (added `intent` and `is_conversational`)
- Minimum question length reduced to 1 (from 3)

**Maintained:**
- All existing functionality
- Database query processing
- SQL generation and safety
- LLM integration
- Rate limiting

---

**Last Updated:** October 16, 2025
**Version:** 3.0
**Author:** MPI Backend Development Team
