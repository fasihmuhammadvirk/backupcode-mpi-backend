"""
Natural Language Q/A Agent using Google Gemini and LangChain
for querying the MPI Backend PostgreSQL database.
"""

import os
import logging
import re
import asyncio
from typing import Dict, Any, List, Optional
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

logger = logging.getLogger(__name__)


class QAAgent:
    """Natural Language Query Agent for MPI Backend Database"""

    def __init__(self):
        """Initialize the QA Agent with Google Gemini and database connection"""
        self.engine = engine
        self.primary_llm = None
        self.fallback_llm = None
        self.sql_database = None
        self.sql_chain = None
        self.answer_chain = None
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
        return {
            "invoices": """
Table: invoices
Columns: id (UUID), date (DATE), filename (VARCHAR), supplier_id (INTEGER), status (VARCHAR), is_exported (VARCHAR), storage_path (VARCHAR)

Key Business Info:
- Contains invoice header information
- Links to suppliers via supplier_id
- Has many invoice_items via invoices.id = invoice_items.invoice_id
- status: PROCESSED, PENDING, etc.
- is_exported: Pending, Exported, etc.

CRITICAL: For user queries about invoices, ALWAYS join with invoice_items to get ref_no and customer_job
because users need this info to identify and understand invoices.

Example intelligent query for "show invoices":
SELECT DISTINCT i.date, s.supplier_name, i.status, i.is_exported, 
       STRING_AGG(DISTINCT ii.ref_no, ', ') as ref_nos,
       STRING_AGG(DISTINCT ii.customer_job, ', ') as customer_jobs
FROM invoices i 
JOIN suppliers s ON i.supplier_id = s.id 
JOIN invoice_items ii ON i.id = ii.invoice_id 
WHERE ii.is_active IS NOT FALSE
GROUP BY i.id, i.date, s.supplier_name, i.status, i.is_exported
ORDER BY i.date DESC;
            """,
            "invoice_items": """
Table: invoice_items
Columns: id, ref_no (VARCHAR), customer_job (VARCHAR), item (VARCHAR), description (VARCHAR), 
         qty (INTEGER), cost (FLOAT), amount (VARCHAR), date (DATE), vendor (VARCHAR), 
         export_status (VARCHAR), invoice_id (UUID), is_active (BOOLEAN)

Key Business Info:
- Contains individual line items from invoices
- ref_no: Critical for identifying specific invoices/items
- customer_job: Critical for project tracking
- Links to invoices via invoice_id
- is_active: TRUE/NULL = active, FALSE = deleted (always filter for active)

Business Rules:
- ALWAYS filter: WHERE is_active IS NOT FALSE (to exclude deleted items)
- For financial calculations, amount field contains strings with commas
            """,
            "suppliers": """
Table: suppliers
Columns: id (INTEGER), supplier_name (VARCHAR)

Key Business Info:
- Contains supplier company information
- Links to invoices via suppliers.id = invoices.supplier_id
- Use supplier_name for user-readable output, never show IDs
            """
        }

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
                """You are an expert data analyst for MPI Backend,
a plumbing supply management system.

Based on the following SQL query and its results, provide a clear,
comprehensive, and user-friendly answer.

**Database Structure & Relationships:**

**INVOICES Table:**
- id: Unique invoice identifier (UUID)
- date: Invoice date
- filename: Invoice filename (DO NOT SHOW - not useful for business users)
- supplier_id: Links to suppliers table
- status: Invoice status (PROCESSED, PENDING, etc.)
- is_exported: Export status (Pending, Exported, etc.)
- storage_path: File location (DO NOT SHOW - internal system path)

**INVOICE_ITEMS Table:**
- id: Unique item identifier
- ref_no: Reference number (CRITICAL for invoice identification)
- po_number: Purchase order number
- customer_job: Customer job name (CRITICAL for project tracking)
- item: Item name/description
- description: Detailed item description
- qty: Quantity
- cost: Unit cost
- amount: Total amount
- date: Item date
- vendor: Vendor name
- class_: Item classification
- account: Account mapping
- memo: Memo/notes
- buyer: Buyer name
- date_added: When item was added to system
- export_status: Export status
- mpi_item: MPI item code
- mpi_description: MPI item description
- is_active: Active status (TRUE/NULL = active)
- invoice_id: Links to invoices table

**SUPPLIERS Table:**
- id: Supplier identifier
- supplier_name: Supplier company name

**TABLE RELATIONSHIPS:**
- invoices.supplier_id → suppliers.id
- invoice_items.invoice_id → invoices.id

**CRITICAL INTELLIGENCE RULES:**

1. **For Invoice Queries:** ALWAYS join with invoice_items to get ref_no and customer_job because:
   - Users need ref_no to identify specific invoices
   - Users need customer_job to understand what project the invoice is for
   - Filenames are not useful for business users

2. **Always Use Joins When Needed:**
   - Invoice queries should join: invoices → suppliers (for supplier_name) → invoice_items (for ref_no, customer_job)
   - Item queries should join: invoice_items → invoices (for date, status) → suppliers (for supplier_name)

3. **Business-First Information:**
   - NEVER show filenames, storage_paths, or UUIDs
   - ALWAYS show ref_no, customer_job, supplier_name, date, status
   - Format dates properly
   - Group related information logically

4. **Smart Aggregation:**
   - For invoices with multiple items: show invoice info + list of ref_nos and customer_jobs
   - For single invoice: show all relevant details
   - For counts: provide meaningful breakdowns

**User Question:** {question}

**SQL Query Executed:**
```sql
{query}
```

**Query Results:**
{result}

**INTELLIGENT RESPONSE GUIDELINES:**

**For ALL Invoice Queries (even simple "show invoices"):**
- ALWAYS include: Date, Supplier Name, Status, Ref No(s), Customer Job(s)
- NEVER include: Filename, Storage Path, UUIDs
- If one invoice has multiple items: Group by invoice and show all ref_nos and customer_jobs for that invoice
- Format: "Invoice from [Supplier] on [Date] with Ref No(s): [list] for Customer Job(s): [list] - Status: [status]"

**For Item Queries:**
- ALWAYS include: Ref No, Item Description, Qty, Cost, Amount, Customer Job, Supplier, Date
- Group by logical relationships
- Show totals when relevant

**For All Queries:**
- Be business-focused: Users need to identify and understand records
- Use natural grouping: Group related information together
- Format dates clearly: "July 22, 2019" not "2019-07-22"
- Format amounts: "$1,234.56" not "1234.56"
- Be specific about counts and totals
- Explain business significance when helpful

**Security Rules:**
- NEVER show database IDs, UUIDs, or internal identifiers
- NEVER show storage paths or file locations
- NEVER reveal technical implementation details
- Focus on business-relevant information only

**Response Format:**
- Use clear headings and bullet points
- Include relevant totals and summaries
- Explain what the data means in business terms
- Be specific about time periods and criteria
- Use professional, conversational tone

Provide a comprehensive, business-focused response that gives users
the information they need to make decisions.
"""
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

    async def query(self, question: str) -> Dict[str, Any]:
        """
        Process a natural language question and return structured response

        Args:
            question (str): Natural language question about the database

        Returns:
            Dict containing answer, sql_query, raw_results, and any errors
        """
        try:
            logger.info(f"Processing question: {question}")

            # Generate SQL query with fallback
            async def generate_sql(llm):
                # Create a new SQL chain with the specified LLM
                sql_chain = create_sql_query_chain(
                    llm=llm,
                    db=self.sql_database
                )
                return await sql_chain.ainvoke({"question": question})

            sql_result, gemini_rate_limited = await self._execute_with_fallback(generate_sql)
            sql_query = sql_result
            logger.info(f"Generated SQL: {sql_query}")

            # Safety check
            if not self._is_safe_query(sql_query):
                return {
                    "answer": ("⚠️ Warning: Only SELECT queries are allowed. "
                               "Write operations are blocked for safety.")
                }

            # Execute query and get raw results
            raw_results = self._execute_sql_query(sql_query)

            # Sanitize results to remove sensitive information
            sanitized_results = self._sanitize_results(str(raw_results))

            # Generate natural language answer with fallback
            async def generate_answer(llm):
                # Create answer generation chain with the specified LLM
                answer_prompt = PromptTemplate.from_template(
                    """You are an expert data analyst for MPI Backend,
a plumbing supply management system.

Based on the following SQL query and its results, provide a clear,
comprehensive, and user-friendly answer.

**Database Structure & Key Fields:**

**INVOICES Table:**
- id: Unique invoice identifier
- date: Invoice date
- filename: Invoice filename
- supplier_id: Links to suppliers table
- status: Invoice status (PROCESSED, PENDING, etc.)
- is_exported: Export status (Pending, Exported, etc.)
- storage_path: File location (DO NOT SHOW)

**Note:** Ref No and Customer Job are stored in the INVOICE_ITEMS table, not the INVOICES table.

**INVOICE_ITEMS Table:**
- id: Unique item identifier
- ref_no: Reference number (important for tracking)
- po_number: Purchase order number
- customer_job: Customer job name
- item: Item name/description
- description: Detailed item description
- qty: Quantity
- cost: Unit cost
- amount: Total amount
- date: Item date
- vendor: Vendor name
- class_: Item classification
- account: Account mapping
- memo: Memo/notes
- buyer: Buyer name
- date_added: When item was added to system
- export_status: Export status
- mpi_item: MPI item code
- mpi_description: MPI item description
- is_active: Active status (TRUE/NULL = active)

**SUPPLIERS Table:**
- id: Supplier identifier
- supplier_name: Supplier company name

**Important Business Rules:**
- Only show active items (is_active = TRUE or NULL)
- Ref No is the primary reference for tracking
- Customer Job shows which project the item belongs to
- Export status shows if items have been exported to accounting
- MPI items are standardized product codes
- Date Added shows when items were entered into the system

**User Question:** {question}

**SQL Query Executed:**
```sql
{query}
```

**Query Results:**
{result}

**INTELLIGENT RESPONSE GUIDELINES:**

**For ALL Invoice Queries (even simple "show invoices"):**
- ALWAYS include: Date, Supplier Name, Status, Ref No(s), Customer Job(s)
- NEVER include: Filename, Storage Path, UUIDs
- If one invoice has multiple items: Group by invoice and show all ref_nos and customer_jobs for that invoice
- Format: "Invoice from [Supplier] on [Date] with Ref No(s): [list] for Customer Job(s): [list] - Status: [status]"

**For Item Queries:**
- ALWAYS include: Ref No, Item Description, Qty, Cost, Amount, Customer Job, Supplier, Date
- Group by logical relationships
- Show totals when relevant

**For All Queries:**
- Be business-focused: Users need to identify and understand records
- Use natural grouping: Group related information together
- Format dates clearly: "July 22, 2019" not "2019-07-22"
- Format amounts: "$1,234.56" not "1234.56"
- Be specific about counts and totals
- Explain business significance when helpful

**Security Rules:**
- NEVER show database IDs, UUIDs, or internal identifiers
- NEVER show storage paths or file locations
- NEVER reveal technical implementation details
- Focus on business-relevant information only

**Response Format:**
- Use clear headings and bullet points
- Include relevant totals and summaries
- Explain what the data means in business terms
- Be specific about time periods and criteria
- Use professional, conversational tone

Provide a comprehensive, business-focused response that gives users
the information they need to make decisions.
"""
                )

                answer_chain = (
                    RunnablePassthrough.assign(query=lambda x: sql_query)
                    | RunnablePassthrough.assign(
                        result=lambda x: raw_results
                    )
                    | answer_prompt
                    | llm
                    | StrOutputParser()
                )

                return await answer_chain.ainvoke({"question": question})

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
            
            # Return only the answer
            return {
                "answer": answer
            }

        except Exception as e:
            logger.error(f"Error processing question: {e}")

            # If it's a rate limit error, provide a helpful message
            if self._is_rate_limit_error(e):
                return {
                    "answer": ("⚠️ Rate limit exceeded! I'm currently experiencing high demand. "
                               "Please try again in a few minutes. If this persists, contact support.")
                }
            else:
                return {
                    "answer": (f"I encountered an error while processing "
                               f"your question: {str(e)}")
                }


# Global instance
_qa_agent = None


def get_qa_agent() -> QAAgent:
    """Get or create QA Agent instance (singleton pattern)"""
    global _qa_agent
    if _qa_agent is None:
        _qa_agent = QAAgent()
    return _qa_agent
