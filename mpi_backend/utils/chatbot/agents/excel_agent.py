"""
Excel Agent - Handles Excel/CSV file generation requests via chatbot
Generates downloadable exports based on natural language queries
"""

from typing import Dict, Any, List, Optional
import logging
import os
import json
import asyncio
from datetime import datetime
import pandas as pd
from mpi_backend.config import S3_PRESIGNED_URL_EXPIRY
from .base_agent import BaseAgent, AgentCapability, AgentPriority
from .intent_router import RequestIntent

logger = logging.getLogger(__name__)


class ExcelAgent(BaseAgent):
    """
    Agent for generating Excel/CSV files from data
    
    Handles natural language requests like:
    - "Export all invoices from BMW Plumbing Supplies"
    - "Generate a CSV of items from July 2024"
    - "Download all invoice items for customer job ABC123 as Excel"
    
    Now uses dbt mart tables for optimized data retrieval:
    - analytics.mart__invoice_items (pre-cleaned, normalized data)
    - Faster queries with pre-computed numeric columns
    """
    
    def __init__(self):
        """Initialize Excel Agent"""
        super().__init__(
            agent_name="excel_agent",
            priority=AgentPriority.MEDIUM
        )
        self._llm_instance = None
        self._mart_executor = None  # Use mart executor for optimized queries
        self._prompt_loader = None
    
    def _get_llm_instance(self):
        """Lazy load the LLM instance"""
        if self._llm_instance is None:
            
            # Try Gemini first
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                api_key = os.getenv("GOOGLE_CHATBOT_API_KEY")
                if api_key:
                    self._llm_instance = ChatGoogleGenerativeAI(
                        model="gemini-2.5-flash",
                        google_api_key=api_key,
                        temperature=0,
                        convert_system_message_to_human=True
                    )
                    logger.info("Excel Agent using Gemini 2.5 Flash")
                    return self._llm_instance
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini: {e}", exc_info=True)
            
            # Fallback to OpenAI
            try:
                from langchain_openai import ChatOpenAI
                openai_key = os.getenv("OPENAI_API_KEY")
                if openai_key:
                    self._llm_instance = ChatOpenAI(
                        model="gpt-4o-mini",
                        api_key=openai_key,
                        temperature=0,
                        max_tokens=4000
                    )
                    logger.info("Excel Agent using OpenAI GPT-4o mini")
                    return self._llm_instance
            except Exception as e:
                logger.exception("Failed to initialize OpenAI")
            
            raise ValueError("No LLM available for Excel Agent")
        
        return self._llm_instance
    
    def _get_mart_executor(self):
        """Lazy load the Mart executor instance for exports"""
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
        """Check if this is an Excel/CSV generation request"""
        intent = request.get("intent", "")
        
        excel_intents = [
            RequestIntent.GENERATE_EXCEL.value,
            RequestIntent.EXPORT_DATA.value,
        ]
        
        return intent in excel_intents
    
    async def process(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process Excel/CSV generation request
        
        Flow:
        1. Parse user's natural language request to understand what data to export
        2. Query database for that data
        3. Generate Excel or CSV file
        4. Upload to S3 storage
        5. Return download link
        
        Args:
            request: Request dictionary with question, session_id, context
            
        Returns:
            Response with download URL and file info
        """
        try:
            question = request["question"]
            
            logger.info(f"Excel Agent processing: {question[:100]}...")
            
            # Step 1: Parse the request to extract query parameters and format preference
            export_params = await self._parse_export_request(question)
            
            if not export_params["success"]:
                return {
                    "success": False,
                    "data": None,
                    "error": export_params["error"],
                    "metadata": {
                        "agent": self.agent_name,
                        "status": "parse_failed"
                    }
                }
            
            # Step 2: Query the database for invoice items
            query_result = await self._query_data_for_export(export_params)
            
            if not query_result["success"]:
                return {
                    "success": False,
                    "data": None,
                    "error": query_result["error"],
                    "metadata": {
                        "agent": self.agent_name,
                        "status": "query_failed"
                    }
                }
            
            # Step 3: Generate file and upload to S3
            file_result = await self._generate_and_upload_file(
                query_result["data"],
                export_params
            )
            
            if not file_result["success"]:
                return {
                    "success": False,
                    "data": None,
                    "error": file_result["error"],
                    "metadata": {
                        "agent": self.agent_name,
                        "status": "file_generation_failed"
                    }
                }
            
            # Step 4: Generate natural language response
            answer = self._generate_response_message(
                export_params,
                query_result,
                file_result
            )
            
            return {
                "success": True,
                "data": {
                    "answer": answer,
                    "download_url": file_result["download_url"],
                    "filename": file_result["filename"],
                    "record_count": query_result["count"],
                    "file_format": export_params["format"],
                    "intent": "export_data"
                },
                "error": None,
                "metadata": {
                    "agent": self.agent_name,
                    "status": "completed",
                    "query_params": export_params.get("query_params"),
                    "processing_time": file_result.get("processing_time")
                }
            }
            
        except Exception as e:
            logger.error(f"Excel Agent error: {e}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"Export generation failed: {str(e)}",
                "metadata": {"agent": self.agent_name}
            }
    
    async def _parse_export_request(self, question: str) -> Dict[str, Any]:
        """
        Parse natural language export request to extract:
        - What data to export (filters, date ranges, suppliers, etc.)
        - Desired format (CSV or Excel)
        - Columns to include (if specified)
        
        Args:
            question: User's natural language question
            
        Returns:
            Dictionary with parsed parameters
        """
        try:
            from datetime import datetime
            
            # Get LLM
            llm = self._get_llm_instance()
            
            # Get current date context
            current_date = datetime.now()
            date_context = f"\n\n**CURRENT DATE CONTEXT:**\n"
            date_context += f"- Today's Date: {current_date.strftime('%Y-%m-%d')} ({current_date.strftime('%B %d, %Y')})\n"
            date_context += f"- Current Year: {current_date.year}\n"
            date_context += f"- Current Month: {current_date.strftime('%B %Y')}\n"
            date_context += f"- Day of Week: {current_date.strftime('%A')}\n\n"
            date_context += "Use this date to interpret relative dates like 'today', 'this month', 'last year', 'yesterday', etc.\n"
            
            # Create parsing prompt - using mart-optimized schema
            from langchain_core.messages import SystemMessage, HumanMessage
            
            system_prompt = """You are an export request parser. Extract export parameters from user requests.

Your task: Parse the user's natural language export request and return structured JSON parameters for querying the optimized mart tables.

**CRITICAL: Use mart table schema (flat structure, no relationship paths)**
- Table names: Use "invoice_items_mart" for invoice item exports
- Operators: Use text format (e.g., "gte" NOT ">=", "lte" NOT "<=", "ilike" for text search)
- Limit: Maximum 1000 (NOT 5000)
- Use "vendor" field directly (NOT "invoice.supplier_fk.supplier_name")

Return JSON with this structure:
{
  "format": "csv" or "xlsx" (default: xlsx),
  "query_params": {
    "table": "invoice_items_mart",
    "filters": [
      {"field": "vendor", "operator": "ilike", "value": "BMW"},
      {"field": "date", "operator": "gte", "value": "2024-07-01"}
    ],
    "columns": ["item", "description", "qty", "cost", "amount", "date", "vendor"],
    "limit": 1000
  }
}

Guidelines:
1. Format: Look for keywords "CSV" or "Excel/xlsx". Default to xlsx if not specified.
2. Table: ALWAYS use "invoice_items_mart" for invoice item exports
3. Filters: Extract any conditions (vendor, date range, customer_job, item, etc.)
4. Columns: If user specifies specific fields, list them. Otherwise, omit (use defaults).
5. Limit: ALWAYS use 1000 or less (schema maximum)

**Valid Operators** (use these exact values):
- "eq": Equals (exact match)
- "ne": Not equals
- "gte": Greater than or equal (use for dates "from", "after")
- "lte": Less than or equal (use for dates "to", "before", "until")
- "ilike": Case-insensitive text search (PREFERRED for text fields)
- "contains": Contains substring
- "in": In list of values

Date handling:
- "from July" → {"field": "date", "operator": "gte", "value": "2024-07-01"}
- "until October" → {"field": "date", "operator": "lte", "value": "2024-10-31"}
- "in September" → Two filters with "gte" and "lte"

**Mart table fields (flat structure - NO relationship paths needed):**
- vendor (String): Supplier name - use "ilike" operator
- date (Date): Invoice date - use "gte"/"lte" operators  
- customer_job (String): Customer job (pre-normalized) - use "ilike" operator
- item (String): Item code - use "ilike" operator
- description (String): Item description - use "ilike" operator
- amount (Float): Total amount - ALREADY NUMERIC
- cost (Float): Unit cost - ALREADY NUMERIC
- qty (Float): Quantity - ALREADY NUMERIC
- po_number (String): PO number - use "ilike" operator
- bill (String): Bill reference - use "ilike" operator
- sheet_name (String): Material category (pre-normalized)
- mpi_item (String): MPI item code - use "eq" operator with exact values
- mpi_description (String): MPI description - use "eq" operator with exact values
- buyer (String): Buyer name

**Important Notes**:
- Use "vendor" field directly for supplier searches (NO relationship paths!)
- Numeric fields are already Float/Integer - no casting needed
- Data is already filtered for active records
- NEVER use ">=" or "<=" operators - use "gte" and "lte" instead
- Limit must be 1000 or less

**ITEM/DESCRIPTION SEARCH RULES (CRITICAL):**
When searching for items by code or description, search ALL 4 fields using "or_filters":
- mpi_item (standardized MPI item code)
- mpi_description (standardized MPI description)
- item (original vendor item code)
- description (original vendor description)

**SPECIAL CASE - "No Match" Items:**
When user asks for "No Match" items, "unmatched items", "items without MPI code", or "unmapped items":
- Use the literal string value "No Match" for ALL 4 fields with OR logic
- "No Match" is a specific status value stored in the database, NOT an empty string!

Examples:

User: "Export all invoices from BMW Plumbing Supplies as CSV"
Response:
{
  "format": "csv",
  "query_params": {
    "table": "invoice_items_mart",
    "filters": [{"field": "vendor", "operator": "ilike", "value": "BMW Plumbing Supplies"}],
    "limit": 1000
  }
}

User: "Generate Excel file of items from July 2024"
Response:
{
  "format": "xlsx",
  "query_params": {
    "table": "invoice_items_mart",
    "filters": [
      {"field": "date", "operator": "gte", "value": "2024-07-01"},
      {"field": "date", "operator": "lte", "value": "2024-07-31"}
    ],
    "limit": 1000
  }
}

User: "Download all items for customer job ABC123"
Response:
{
  "format": "xlsx",
  "query_params": {
    "table": "invoice_items_mart",
    "filters": [{"field": "customer_job", "operator": "ilike", "value": "ABC123"}],
    "limit": 1000
  }
}

User: "I want to download CSV for all invoices for BMW Plumbing Supplies in Oct 2025"
Response:
{
  "format": "csv",
  "query_params": {
    "table": "invoice_items_mart",
    "filters": [
      {"field": "vendor", "operator": "ilike", "value": "BMW Plumbing Supplies"},
      {"field": "date", "operator": "gte", "value": "2025-10-01"},
      {"field": "date", "operator": "lte", "value": "2025-10-31"}
    ],
    "limit": 1000
  }
}

User: "Give me Excel for all No Match invoice items" or "Export unmatched items"
Response:
{
  "format": "xlsx",
  "query_params": {
    "table": "invoice_items_mart",
    "filters": [],
    "or_filters": [
      [{"field": "mpi_item", "operator": "eq", "value": "No Match"}],
      [{"field": "mpi_description", "operator": "eq", "value": "No Match"}],
      [{"field": "item", "operator": "eq", "value": "No Match"}],
      [{"field": "description", "operator": "eq", "value": "No Match"}]
    ],
    "limit": 1000
  }
}

User: "Download CSV of all items without MPI code"
Response:
{
  "format": "csv",
  "query_params": {
    "table": "invoice_items_mart",
    "filters": [],
    "or_filters": [
      [{"field": "mpi_item", "operator": "eq", "value": "No Match"}],
      [{"field": "mpi_description", "operator": "eq", "value": "No Match"}],
      [{"field": "item", "operator": "eq", "value": "No Match"}],
      [{"field": "description", "operator": "eq", "value": "No Match"}]
    ],
    "limit": 1000
  }
}

User: "Export items with code 'BALL VALVE'"
Response:
{
  "format": "xlsx",
  "query_params": {
    "table": "invoice_items_mart",
    "filters": [],
    "or_filters": [
      [{"field": "mpi_item", "operator": "eq", "value": "BALL VALVE"}],
      [{"field": "mpi_description", "operator": "eq", "value": "BALL VALVE"}],
      [{"field": "item", "operator": "eq", "value": "BALL VALVE"}],
      [{"field": "description", "operator": "eq", "value": "BALL VALVE"}]
    ],
    "limit": 1000
  }
}
"""
            
            # Add date context to the prompt
            system_prompt_with_context = system_prompt + date_context
            
            user_msg = f"Export request: {question}"
            
            messages = [
                SystemMessage(content=system_prompt_with_context),
                HumanMessage(content=user_msg)
            ]
            
            # Generate JSON
            response = await llm.ainvoke(messages)
            json_str = response.content.strip()
            
            # Clean up response (remove markdown code blocks if present)
            import re
            json_str = re.sub(r'```json\s*', '', json_str)
            json_str = re.sub(r'```\s*$', '', json_str)
            json_str = json_str.strip()
            
            # Parse JSON
            params = json.loads(json_str)
            
            logger.info(f"Parsed export params: format={params.get('format')}, "
                       f"filters={len(params.get('query_params', {}).get('filters', []))}")
            
            return {
                "success": True,
                "format": params.get("format", "xlsx"),
                "query_params": params.get("query_params", {}),
                "columns": params.get("query_params", {}).get("columns"),
                "error": None
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM: {e}")
            logger.error(f"LLM response: {json_str[:500]}")
            return {
                "success": False,
                "error": "Could not understand export request. Please be more specific about what data you want to export."
            }
        except Exception as e:
            logger.error(f"Error parsing export request: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Failed to parse export request: {str(e)}"
            }
    
    async def _query_data_for_export(self, export_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query database for data to export using dbt mart tables.
        
        Uses mart__invoice_items for optimized data retrieval:
        - Pre-cleaned, normalized data
        - Numeric columns already cast
        - Faster query performance
        
        Args:
            export_params: Parsed export parameters
            
        Returns:
            Query results with invoice item IDs
        """
        try:
            from mpi_backend.utils.chatbot.query_schema import QueryParameters
            
            query_params_dict = export_params["query_params"]
            
            # Create QueryParameters object
            query_params = QueryParameters(**query_params_dict)
            
            logger.info(f"Executing export query: table={query_params.table}, "
                       f"filters={len(query_params.filters)}")
            
            # Execute query using mart executor
            mart_executor = self._get_mart_executor()
            if not mart_executor.is_mart_available():
                return {
                    "success": False,
                    "error": "Mart tables are not available. Please ensure dbt has been run to create the analytics tables."
                }
            
            logger.info("Using mart executor for export query")
            query_result = await asyncio.to_thread(
                mart_executor.execute_query,
                query_params
            )
            query_source = "mart"
            
            if not query_result.success:
                return {
                    "success": False,
                    "error": query_result.error
                }
            
            # Extract IDs from results
            if not query_result.data:
                return {
                    "success": False,
                    "error": "No data found matching your criteria. Please adjust your filters."
                }
            
            # Get IDs from query results
            ids = [item.get("id") for item in query_result.data if item.get("id")]
            
            if not ids:
                return {
                    "success": False,
                    "error": "No invoice items found matching your criteria."
                }
            
            logger.info(f"Found {len(ids)} invoice items for export from {query_source}")
            
            return {
                "success": True,
                "data": ids,
                "count": len(ids),
                "raw_results": query_result.data[:10],  # Keep first 10 for preview
                "source": query_source
            }
            
        except Exception as e:
            logger.error(f"Error querying data for export: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Database query failed: {str(e)}"
            }
    
    async def _generate_and_upload_file(
        self,
        item_ids: List[int],
        export_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate Excel/CSV file and upload to S3
        
        Args:
            item_ids: List of invoice item IDs to export
            export_params: Export parameters (format, columns, etc.)
            
        Returns:
            Dictionary with download URL and file info
        """
        try:
            import time
            start_time = time.time()
            
            from mpi_backend.database import get_db
            from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
            from mpi_backend.utils.s3_utils import upload_export_and_get_url
            
            # Get database session
            db = next(get_db())
            
            try:
                # Get data as DataFrame using existing optimized utilities
                file_format = export_params.get("format", "xlsx")
                columns = export_params.get("columns")
                
                # Use optimized export based on data size
                if len(item_ids) > 1000:
                    from mpi_backend.utils.export_utils import convert_items_to_dataframe_batch
                    items_df = convert_items_to_dataframe_batch(
                        db_session=db,
                        ids=item_ids,
                        columns=columns,
                        order_by=None,
                        use_suffix=True,
                        batch_size=500
                    )
                elif len(item_ids) > 50:
                    from mpi_backend.utils.export_utils import convert_items_to_dataframe_optimized
                    items_df = convert_items_to_dataframe_optimized(
                        db_session=db,
                        ids=item_ids,
                        columns=columns,
                        order_by=None,
                        use_suffix=True
                    )
                else:
                    from mpi_backend.utils.export_utils import convert_items_to_dataframe
                    from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
                    controller = InvoiceItemController(db)
                    items = controller.get_invoice_items_by_ids(item_ids)
                    items_df = convert_items_to_dataframe(items)
                
                if items_df.empty:
                    return {
                        "success": False,
                        "error": "No data available for export after filtering."
                    }
                
                # Apply column selection if specified
                if columns and not items_df.empty:
                    available_columns = [col for col in columns if col in items_df.columns]
                    if available_columns:
                        items_df = items_df[available_columns]
                else:
                    # Use default columns
                    default_columns = ["Item", "Description", "Qty", "Cost", "Amount", 
                                      "Date", "Ref NO", "PO #", "Customer Job", "Bill", 
                                      "Vendor", "Class", "Memo"]
                    available_columns = [col for col in default_columns if col in items_df.columns]
                    items_df = items_df[available_columns]
                
                # Prepare file paths
                upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                
                if file_format == "csv":
                    filename = f'chatbot_export_{timestamp}.csv'
                    file_path = f'{upload_folder}{filename}'
                    
                    if not os.path.exists(upload_folder):
                        os.makedirs(upload_folder)
                    
                    # Save as CSV
                    items_df.to_csv(file_path, index=False)
                    logger.info(f"Generated CSV file: {filename}")
                    
                else:  # xlsx
                    filename = f'chatbot_export_{timestamp}.xlsx'
                    file_path = f'{upload_folder}{filename}'
                    
                    if not os.path.exists(upload_folder):
                        os.makedirs(upload_folder)
                    
                    # Save as Excel using fast method
                    if len(items_df) > 100:
                        from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data_fast
                        save_final_data_fast(items_df, file_path)
                    else:
                        from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data
                        save_final_data(final_df=items_df, supplier='', output_path=file_path)
                    
                    logger.info(f"Generated Excel file: {filename}")
                
                download_url = upload_export_and_get_url(file_path)
                processing_time = time.time() - start_time
                logger.info(f"Export completed in {processing_time:.2f} seconds for {len(items_df)} items")
                
                return {
                    "success": True,
                    "download_url": download_url,
                    "filename": filename,
                    "record_count": len(items_df),
                    "processing_time": f"{processing_time:.2f}s"
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error generating export file: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"File generation failed: {str(e)}"
            }
    
    def _generate_response_message(
        self,
        export_params: Dict[str, Any],
        query_result: Dict[str, Any],
        file_result: Dict[str, Any]
    ) -> str:
        """
        Generate natural language response message
        
        Args:
            export_params: Export parameters
            query_result: Query results
            file_result: File generation results
            
        Returns:
            Natural language response with download link
        """
        file_format = export_params.get("format", "xlsx").upper()
        record_count = file_result.get("record_count", 0)
        filename = file_result.get("filename", "export file")
        download_url = file_result.get("download_url", "")
        processing_time = file_result.get("processing_time", "")
        expiry_hours = max(1, round(S3_PRESIGNED_URL_EXPIRY / 3600))
        
        # Build response message
        message = f"""✅ **Export Complete!**

I've generated your {file_format} file with **{record_count:,} invoice items**.

📥 **Download your file:**
[{filename}]({download_url})

⏱️ Processing time: {processing_time}

**Note:** The download link will expire in {expiry_hours} hours for security.
"""
        
        # Add filter info if applicable
        filters = export_params.get("query_params", {}).get("filters", [])
        if filters:
            filter_desc = []
            for f in filters:
                field = f.get("field", "")
                value = f.get("value", "")
                if field and value:
                    filter_desc.append(f"{field}: {value}")
            
            if filter_desc:
                message += f"\n**Applied filters:** {', '.join(filter_desc)}"
        
        return message
    
    def get_capabilities(self) -> List[AgentCapability]:
        """Get agent capabilities"""
        return [AgentCapability.GENERATE_EXCEL]
