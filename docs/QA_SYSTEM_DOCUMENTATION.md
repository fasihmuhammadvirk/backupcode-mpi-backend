# MPI Backend Natural Language Q/A System

## Overview

The MPI Backend now includes a powerful Natural Language Q/A system that allows users to ask questions about the database in plain English and receive intelligent, structured answers. This system is powered by Google Gemini AI and integrates seamlessly with the existing FastAPI architecture.

## Features

- **Natural Language Processing**: Ask questions in plain English
- **SQL Generation**: Automatically converts questions to SQL queries
- **Safety First**: Only SELECT queries allowed, comprehensive input validation
- **Intelligent Responses**: Context-aware answers with business insights
- **Debug Mode**: Detailed debugging information for troubleshooting
- **Comprehensive Testing**: Full test suite for reliability

## Architecture

### Components

1. **QA Agent** (`utils/qa_agent.py`)
   - Core AI logic using Google Gemini LLM
   - SQL query generation and safety validation
   - Result processing and natural language response generation

2. **QA Controller** (`database/controllers/QAController.py`)
   - Business logic layer
   - Input validation and error handling
   - Orchestrates QA flow

3. **QA Routes** (`api/routes/qa.py`)
   - REST API endpoints
   - Request/response models
   - API documentation

4. **Tests** (`tests/test_qa.py`)
   - Comprehensive test coverage
   - Safety validation tests
   - Integration tests

## API Endpoints

### Core Endpoints

#### `POST /qa/query`
Process a natural language question and return an answer.

**Request:**
```json
{
  "question": "Show me all invoices from BMW Plumbing Supplies in July 2024"
}
```

**Response:**
```json
{
  "answer": "I found 23 invoices from BMW Plumbing Supplies in July 2024...",
  "sql_query": "SELECT * FROM invoices i JOIN suppliers s ON i.supplier_id = s.id WHERE s.supplier_name = 'BMW Plumbing Supplies' AND EXTRACT(month FROM i.date) = 7 AND EXTRACT(year FROM i.date) = 2024",
  "raw_results": "Found 23 results: [...]",
  "error": null
}
```

#### `POST /qa/debug-query`
Same as above but includes detailed debugging information.

**Additional Response Fields:**
```json
{
  "debug_info": {
    "table_info": "Database schema information...",
    "safety_check": "PASSED",
    "question_analysis": "Processed question: '...'",
    "sql_generation": "Successfully generated SQL query",
    "query_execution": "Successfully executed query",
    "answer_generation": "Successfully generated natural language answer"
  }
}
```

### Utility Endpoints

#### `GET /qa/system-info`
Get information about the Q/A system status and capabilities.

#### `GET /qa/health`
Simple health check for the Q/A system.

#### `GET /qa/examples`
Get example queries and usage tips.

## Setup Instructions

### 1. Install Dependencies

The required dependencies have been added to `requirements.txt`:
```
langchain==0.1.0
langchain-google-genai==1.0.1
langchain-community==0.0.13
google-generativeai==0.3.2
```

Install them with:
```bash
pip install -r requirements.txt
```

### 2. Environment Configuration

Add the following environment variable to your `.env` file:

```bash
# Google Gemini API Key for Natural Language Processing
GOOGLE_CHATBOT_API_KEY=your_google_gemini_api_key_here
```

**Getting a Google Gemini API Key:**
1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Sign in with your Google account
3. Create a new API key
4. Copy the key to your `.env` file

### 3. Database Schema

The system works with your existing database models:
- `invoices` - Invoice records
- `invoice_items` - Individual line items
- `suppliers` - Supplier information
- `supplier_item_mappings` - Item mappings
- `customer_job_mappings` - Customer job mappings
- `item_classifications` - Item classifications
- `unmapped_items` - Unmapped items

### 4. Start the Application

The Q/A routes are automatically registered when you start the FastAPI application:

```bash
python -m mpi_backend.main
```

## Usage Examples

### Basic Questions

1. **Count Queries:**
   - "How many invoices do we have?"
   - "How many suppliers are in the system?"
   - "Count all active invoice items"

2. **Supplier Queries:**
   - "Show me all invoices from BMW Plumbing Supplies"
   - "What suppliers have invoices this month?"
   - "Find all items from World Wide Plumbing"

3. **Date-based Queries:**
   - "Show invoices from July 2024"
   - "What items were added last week?"
   - "Find all invoices from the past 30 days"

4. **Financial Queries:**
   - "What is the total amount of all invoice items?"
   - "Show me the most expensive items"
   - "What's the average cost of items from Pyramid Plumbing?"

5. **Customer Job Queries:**
   - "Show all items for customer job ABC123"
   - "What customer jobs start with 'PROJ'?"
   - "Find unmapped items for specific customers"

### Advanced Queries

1. **Complex Filters:**
   - "Find all pipe fittings over $50 from BMW Plumbing in July"
   - "Show invoice items with quantity greater than 10 and cost less than $100"

2. **Aggregations:**
   - "What are the top 5 most expensive invoice items?"
   - "Group invoice totals by supplier for this month"
   - "Average item cost by supplier"

3. **Pattern Matching:**
   - "Find all items with 'pipe' in the description"
   - "Show suppliers whose names contain 'Plumbing'"

## Safety Features

### Query Safety
- **Read-Only**: Only SELECT queries are allowed
- **SQL Injection Protection**: Input sanitization and validation
- **Result Limiting**: Results capped at 50 rows for performance
- **Timeout Protection**: Long-running queries are terminated

### Input Validation
- Question length limits (3-1000 characters)
- Type validation (must be string)
- Content validation (must be meaningful question)

### Error Handling
- Graceful error responses
- Detailed error logging
- Fallback responses for failed queries

## System Prompt

The system uses a comprehensive prompt that provides context about:
- Database schema and relationships
- Business rules (soft-delete patterns, data types)
- Response formatting guidelines
- Safety considerations

## Troubleshooting

### Common Issues

1. **"GOOGLE_CHATBOT_API_KEY not found"**
   - Ensure the environment variable is set in `.env`
   - Verify the API key is valid

2. **"Import errors for langchain modules"**
   - Install the required dependencies: `pip install -r requirements.txt`

3. **"Database connection issues"**
   - Verify your existing database configuration is correct
   - The Q/A system uses the same database connection as the rest of the app

4. **"Query returns no results"**
   - Check the question phrasing
   - Verify data exists for the query criteria
   - Use debug mode for detailed analysis

### Debug Mode

Use the `/qa/debug-query` endpoint to get detailed information about:
- How the question was interpreted
- Generated SQL query
- Safety check results
- Query execution details
- Error diagnostics

### Logs

The system logs detailed information to help with troubleshooting:
- Question processing steps
- Generated SQL queries
- Error details
- Performance metrics

## Performance Considerations

- **Result Limiting**: Automatic limiting to 50 rows prevents large result sets
- **Query Optimization**: LLM generates optimized SQL queries
- **Caching**: LLM responses can be cached for repeated questions
- **Connection Pooling**: Uses existing database connection pool

## Security Considerations

- **Read-Only Access**: No write operations allowed
- **Input Sanitization**: All inputs are validated and sanitized
- **API Key Security**: Gemini API key should be kept secure
- **Query Monitoring**: All queries are logged for audit purposes

## Future Enhancements

Potential improvements for future versions:
1. **Query Caching**: Cache common query results
2. **Advanced Analytics**: More sophisticated business intelligence
3. **Multi-language Support**: Support for languages other than English
4. **Custom Models**: Training on domain-specific terminology
5. **Real-time Updates**: Live data refresh capabilities

## Testing

Run the comprehensive test suite:

```bash
# Run Q/A system tests
python -m pytest mpi_backend/tests/test_qa.py -v

# Run all tests including Q/A
python -m pytest mpi_backend/tests/ -v
```

Test coverage includes:
- Query processing and safety validation
- Controller logic and error handling
- API endpoint functionality
- Safety and security features

## Support

For technical support with the Q/A system:
1. Check the logs for detailed error information
2. Use debug mode for troubleshooting query issues
3. Verify environment configuration
4. Review the test suite for expected behavior patterns

## Contributing

When contributing to the Q/A system:
1. Maintain comprehensive test coverage
2. Follow the existing code style and patterns
3. Update documentation for new features
4. Ensure all safety checks remain in place
