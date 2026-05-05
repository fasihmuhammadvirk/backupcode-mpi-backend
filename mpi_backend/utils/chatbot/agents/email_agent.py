"""
Email Agent
Handles email generation requests, including supplier refund emails for price increases
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
import re
import json
from datetime import datetime, timedelta, date
from sqlalchemy import func
from .base_agent import BaseAgent, AgentCapability, AgentPriority
from .intent_router import RequestIntent

logger = logging.getLogger(__name__)


class EmailAgent(BaseAgent):
    """
    Agent for generating emails
    
    Handles:
    - Supplier refund emails for increased prices
    - Other email generation requests
    """
    
    def __init__(self):
        """Initialize Email Agent"""
        super().__init__(
            agent_name="email_agent",
            priority=AgentPriority.MEDIUM
        )
        self._llm_instance = None
    
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
                    logger.info("Email Agent using Gemini 2.5 Flash")
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
                        max_tokens=2000
                    )
                    logger.info("Email Agent using OpenAI GPT-4o mini")
                    return self._llm_instance
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI: {e}")
            
            raise ValueError("No LLM available for Email Agent")
        
        return self._llm_instance
    
    def can_handle(self, request: Dict[str, Any]) -> bool:
        """Check if this is an email sending request"""
        intent = request.get("intent", "")
        question = request.get("question", "").lower()
        
        email_intents = [
            RequestIntent.SEND_EMAIL.value,
            RequestIntent.SEND_NOTIFICATION.value,
        ]
        
        # Check for price increase email requests
        # Supplier keyword is optional - can filter by supplier name or date
        is_price_increase_email = (
            any(word in question for word in ['email', 'create', 'generate', 'make', 'write', 'provide', 'give', 'get']) and
            any(word in question for word in ['increase', 'increased', 'price', 'prices'])
        )
        
        return intent in email_intents or is_price_increase_email
    
    def _is_price_increase_request(self, question: str) -> bool:
        """Check if request is for price increase email generation"""
        question_lower = question.lower()
        has_email_keyword = any(word in question_lower for word in ['email', 'create', 'generate', 'make', 'write'])
        has_price_keyword = any(word in question_lower for word in ['increase', 'increased', 'price', 'prices'])
        
        # Can have supplier keyword OR just price increase (supplier is optional)
        has_supplier_keyword = any(word in question_lower for word in ['supplier', 'suppliers'])
        
        return has_email_keyword and has_price_keyword
    
    def _is_general_supplier_email_request(self, question: str) -> bool:
        """Check if request is for general supplier email generation (not price increases)"""
        question_lower = question.lower()
        has_email_keyword = any(word in question_lower for word in ['email', 'create', 'generate', 'make', 'write'])
        has_price_keyword = any(word in question_lower for word in ['increase', 'increased', 'price', 'prices'])
        
        # If it has email keywords but NOT price keywords, it's a general email request
        # Also check for month/date keywords which indicate a summary email
        has_date_keyword = any(word in question_lower for word in [
            'month', 'october', 'november', 'december', 'january', 'february',
            'march', 'april', 'may', 'june', 'july', 'august', 'september',
            'for the month', 'in the month', 'during', 'period'
        ])
        
        return has_email_keyword and not has_price_keyword and has_date_keyword
    
    async def _parse_filters_from_question(self, question: str) -> Dict[str, Any]:
        """
        Parse supplier name and date/month filters from question using LLM
        
        Args:
            question: User's question
            
        Returns:
            Dictionary with filters: supplier_name, start_date, end_date
        """
        try:
            # Get LLM
            llm = self._get_llm_instance()
            
            # Get current date context
            current_date = datetime.now()
            date_context = f"\n\n**CURRENT DATE CONTEXT:**\n"
            date_context += f"- Today's Date: {current_date.strftime('%Y-%m-%d')} ({current_date.strftime('%B %d, %Y')})\n"
            date_context += f"- Current Year: {current_date.year}\n"
            date_context += f"- Current Month: {current_date.strftime('%B %Y')}\n\n"
            date_context += "Use this date to interpret relative dates like 'this month', 'last month', etc.\n"
            
            # Create parsing prompt
            from langchain_core.messages import SystemMessage, HumanMessage
            
            system_prompt = """You are an email request parser. Extract filter parameters from user requests for generating price increase emails.

Your task: Parse the user's natural language email generation request and return structured JSON with supplier and date filters.

Return JSON with this structure:
{
  "supplier_names": ["BMW Plumbing Supplies", "World Wide Plumbing"] or [] if not specified (array for multiple suppliers),
  "supplier_name": "BMW Plumbing Supplies" or null (single supplier - for backward compatibility),
  "start_date": "2025-10-01" or null if not specified (YYYY-MM-DD format),
  "end_date": "2025-10-31" or null if not specified (YYYY-MM-DD format)
}

Guidelines:
1. Supplier Names: Extract supplier name(s) if mentioned. Can be single or multiple:
   - Single: "for BMW Plumbing Supplies" → supplier_name: "BMW Plumbing Supplies", supplier_names: ["BMW Plumbing Supplies"]
   - Multiple: "for BMW and World Wide Plumbing" → supplier_names: ["BMW", "World Wide Plumbing"]
   - Multiple: "for BMW Plumbing Supplies, World Wide Plumbing, and ABC Supplies" → supplier_names: ["BMW Plumbing Supplies", "World Wide Plumbing", "ABC Supplies"]
   - Multiple: "for BMW and World Wide" → supplier_names: ["BMW", "World Wide"]
   - "BMW Plumbing Supplies in October" → supplier_name: "BMW Plumbing Supplies", supplier_names: ["BMW Plumbing Supplies"]
   - If no supplier mentioned, set both to null/empty

2. Date Range: Extract date range if mentioned. Supports various formats:
   - Single month: "in October 2025" → start_date: "2025-10-01", end_date: "2025-10-31"
   - Single month: "in the month of October 2025" → start_date: "2025-10-01", end_date: "2025-10-31"
   - Date range: "between October 1 and October 31, 2025" → start_date: "2025-10-01", end_date: "2025-10-31"
   - Date range: "from October 1 to October 31, 2025" → start_date: "2025-10-01", end_date: "2025-10-31"
   - Date range: "between Oct 1, 2025 and Nov 15, 2025" → start_date: "2025-10-01", end_date: "2025-11-15"
   - Date range: "from 10/1/2025 to 10/31/2025" → start_date: "2025-10-01", end_date: "2025-10-31"
   - Year only: "in 2025" → start_date: "2025-01-01", end_date: "2025-12-31"
   - If no date mentioned, set both to null

3. Important Notes:
   - Supplier names should be extracted even if they appear at the end of the sentence
   - Handle variations: "for BMW", "BMW supplier", "for BMW Plumbing Supplies"
   - For multiple suppliers, look for: "and", ",", "or" as separators
   - Do NOT extract action words like "generate", "create", "email", "price", "increase" as supplier names
   - Month names can be full (October) or abbreviated (Oct)
   - Always return valid JSON, never null values for the JSON structure itself
   - If supplier_names array is provided, also set supplier_name to the first one for backward compatibility

Examples:

User: "Generate an email for price increase in the month of October 2025 for World Wide Plumbing"
Response:
{
  "supplier_name": "World Wide Plumbing",
  "supplier_names": ["World Wide Plumbing"],
  "start_date": "2025-10-01",
  "end_date": "2025-10-31"
}

User: "Create an email for price increase for BMW and World Wide Plumbing in October 2025"
Response:
{
  "supplier_name": "BMW",
  "supplier_names": ["BMW", "World Wide Plumbing"],
  "start_date": "2025-10-01",
  "end_date": "2025-10-31"
}

User: "Generate email for price increases between October 1 and November 15, 2025 for BMW Plumbing Supplies"
Response:
{
  "supplier_name": "BMW Plumbing Supplies",
  "supplier_names": ["BMW Plumbing Supplies"],
  "start_date": "2025-10-01",
  "end_date": "2025-11-15"
}

User: "Email for price increase from Oct 1 to Oct 31, 2025 for BMW and World Wide"
Response:
{
  "supplier_name": "BMW",
  "supplier_names": ["BMW", "World Wide"],
  "start_date": "2025-10-01",
  "end_date": "2025-10-31"
}

User: "Generate an email for price increase in November 2025"
Response:
{
  "supplier_name": null,
  "supplier_names": [],
  "start_date": "2025-11-01",
  "end_date": "2025-11-30"
}

User: "Generate an email for price increase for BMW Plumbing Supplies"
Response:
{
  "supplier_name": "BMW Plumbing Supplies",
  "supplier_names": ["BMW Plumbing Supplies"],
  "start_date": null,
  "end_date": null
}

User: "Create price increase email for BMW, World Wide Plumbing, and ABC Supplies between 10/1/2025 and 10/31/2025"
Response:
{
  "supplier_name": "BMW",
  "supplier_names": ["BMW", "World Wide Plumbing", "ABC Supplies"],
  "start_date": "2025-10-01",
  "end_date": "2025-10-31"
}
"""
            
            # Add date context to the prompt
            system_prompt_with_context = system_prompt + date_context
            
            user_msg = f"Email generation request: {question}"
            
            messages = [
                SystemMessage(content=system_prompt_with_context),
                HumanMessage(content=user_msg)
            ]
            
            # Generate JSON
            response = await llm.ainvoke(messages)
            json_str = json.loads(response.content.strip())
            
            # Check if LLM returned an error message instead of JSON
            if 'error' in json_str.lower() or 'cannot' in json_str.lower() or 'unable' in json_str.lower():
                logger.warning(f"LLM returned error message instead of JSON: {json_str[:200]}")
                # Fallback to empty filters - let the system try to process without filters
                return {}
            
            # Clean up response (remove markdown code blocks if present)
            json_str = re.sub(r'```json\s*', '', json_str)
            json_str = re.sub(r'```\s*$', '', json_str)
            json_str = json_str.strip()
            
            # Try to extract JSON from response if it's wrapped in text
            json_match = re.search(r'\{[^{}]*"supplier_name"[^{}]*\}', json_str, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            
            # Parse JSON
            try:
                params = json.loads(json_str)
            except json.JSONDecodeError:
                # If JSON parsing fails, try to extract just the JSON object
                json_match = re.search(r'\{.*\}', json_str, re.DOTALL)
                if json_match:
                    try:
                        params = json.loads(json_match.group(0))
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON even after extraction: {json_str[:500]}")
                        return {}
                else:
                    logger.error(f"No JSON found in LLM response: {json_str[:500]}")
                    return {}
            
            # Convert date strings to date objects
            filters = {}
            
            # Handle multiple suppliers (preferred) or single supplier (backward compatibility)
            supplier_names = params.get('supplier_names', [])
            if not supplier_names and params.get('supplier_name'):
                # Backward compatibility: convert single supplier_name to array
                supplier_name = params['supplier_name'].strip()
                if supplier_name and supplier_name.lower() != 'null':
                    supplier_names = [supplier_name]
            
            if supplier_names:
                # Clean and normalize supplier names
                cleaned_suppliers = []
                for supplier in supplier_names:
                    if isinstance(supplier, str):
                        supplier = supplier.strip()
                        if supplier and supplier.lower() != 'null':
                            cleaned_suppliers.append(supplier)
                
                if cleaned_suppliers:
                    filters['supplier_names'] = cleaned_suppliers
                    # Also set supplier_name for backward compatibility (first supplier)
                    filters['supplier_name'] = cleaned_suppliers[0]
            
            if params.get('start_date'):
                try:
                    filters['start_date'] = datetime.strptime(params['start_date'], '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid start_date format: {params['start_date']}")
            
            if params.get('end_date'):
                try:
                    filters['end_date'] = datetime.strptime(params['end_date'], '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid end_date format: {params['end_date']}")
            
            logger.info(f"Parsed filters from LLM: {filters}")
            
            return filters
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM: {e}")
            logger.error(f"LLM response: {json_str[:500]}")
            # Try fallback regex parsing if LLM fails
            logger.info("Attempting fallback regex parsing")
            return self._parse_filters_fallback(question)
        except Exception as e:
            logger.error(f"Error parsing email request with LLM: {e}", exc_info=True)
            # Try fallback regex parsing if LLM fails
            logger.info("Attempting fallback regex parsing due to exception")
            return self._parse_filters_fallback(question)
    
    def _parse_filters_fallback(self, question: str) -> Dict[str, Any]:
        """
        Fallback regex-based parsing if LLM fails
        Handles multiple suppliers and date ranges
        """
        filters = {}
        question_lower = question.lower()
        
        # Parse multiple suppliers (look for "and", ",", "or" as separators)
        supplier_patterns = [
            # Multiple suppliers with "and": "for BMW and World Wide"
            r'for\s+([A-Z][A-Za-z0-9\s&\.\-]+?)\s+and\s+([A-Z][A-Za-z0-9\s&\.\-]+?)(?:\s+and\s+([A-Z][A-Za-z0-9\s&\.\-]+?))?(?:\s|$)',
            # Multiple suppliers with comma: "for BMW, World Wide, ABC"
            r'for\s+([A-Z][A-Za-z0-9\s&\.\-]+?),\s*([A-Z][A-Za-z0-9\s&\.\-]+?)(?:,\s*([A-Z][A-Za-z0-9\s&\.\-]+?))?(?:\s|$)',
            # Single supplier
            r'for\s+([A-Z][A-Za-z0-9\s&\.\-]+?(?:\s+(?:Plumbing|Supply|Supplies|Inc|LLC|Corp))?)(?:\s|$)',
            r'for\s+([A-Z][A-Za-z0-9\s&\.\-]+?)(?:\s+supplier)',
            r'([A-Z][A-Za-z0-9\s&\.\-]+?)\s+supplier',
        ]
        
        suppliers_found = []
        for pattern in supplier_patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                # Extract all supplier groups
                for i in range(1, match.lastindex + 1):
                    supplier_name = match.group(i)
                    if supplier_name:
                        supplier_name = supplier_name.strip()
                        # Clean up
                        supplier_name = re.sub(r'\s+(supplier|in|for|of|the|and|or)\s*$', '', supplier_name, flags=re.IGNORECASE)
                        if supplier_name and len(supplier_name) > 2 and supplier_name[0].isupper():
                            # Avoid duplicates
                            if supplier_name not in suppliers_found:
                                suppliers_found.append(supplier_name)
                
                if suppliers_found:
                    break
        
        if suppliers_found:
            if len(suppliers_found) == 1:
                filters['supplier_name'] = suppliers_found[0]
                filters['supplier_names'] = suppliers_found
            else:
                filters['supplier_names'] = suppliers_found
                filters['supplier_name'] = suppliers_found[0]  # Backward compatibility
            logger.info(f"Fallback parsed supplier(s): {suppliers_found}")
        
        # Parse date range - handle "between X and Y" or "from X to Y"
        month_names = ['january', 'february', 'march', 'april', 'may', 'june',
                       'july', 'august', 'september', 'october', 'november', 'december']
        month_abbrevs = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
                         'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
        
        # Try date range pattern first: "between Oct 1 and Nov 15, 2025" or "from 10/1/2025 to 10/31/2025"
        date_range_patterns = [
            r'between\s+(\w+)\s+(\d+)[,\s]+(\d{4})\s+and\s+(\w+)\s+(\d+)[,\s]+(\d{4})',
            r'from\s+(\w+)\s+(\d+)[,\s]+(\d{4})\s+to\s+(\w+)\s+(\d+)[,\s]+(\d{4})',
            r'between\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+and\s+(\d{1,2})/(\d{1,2})/(\d{4})',
            r'from\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+to\s+(\d{1,2})/(\d{1,2})/(\d{4})',
        ]
        
        date_parsed = False
        for pattern in date_range_patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                try:
                    from datetime import date
                    if '/' in pattern:  # Date format: MM/DD/YYYY
                        start_month, start_day, start_year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        end_month, end_day, end_year = int(match.group(4)), int(match.group(5)), int(match.group(6))
                        filters['start_date'] = date(start_year, start_month, start_day)
                        filters['end_date'] = date(end_year, end_month, end_day)
                    else:  # Month name format
                        start_month_str = match.group(1).lower()
                        start_day = int(match.group(2))
                        start_year = int(match.group(3))
                        end_month_str = match.group(4).lower()
                        end_day = int(match.group(5))
                        end_year = int(match.group(6))
                        
                        start_month_idx = None
                        if start_month_str in month_names:
                            start_month_idx = month_names.index(start_month_str) + 1
                        elif start_month_str in month_abbrevs:
                            start_month_idx = month_abbrevs.index(start_month_str) + 1
                        
                        end_month_idx = None
                        if end_month_str in month_names:
                            end_month_idx = month_names.index(end_month_str) + 1
                        elif end_month_str in month_abbrevs:
                            end_month_idx = month_abbrevs.index(end_month_str) + 1
                        
                        if start_month_idx and end_month_idx:
                            filters['start_date'] = date(start_year, start_month_idx, start_day)
                            filters['end_date'] = date(end_year, end_month_idx, end_day)
                    
                    logger.info(f"Fallback parsed date range: {filters['start_date']} to {filters['end_date']}")
                    date_parsed = True
                    break
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse date range: {e}")
                    continue
        
        # If no date range found, try single month pattern
        if not date_parsed:
            date_pattern = r'(?:in|for|of|during)\s+(?:the\s+)?(?:month\s+)?(\w+)\s+(\d{4})'
            match = re.search(date_pattern, question, re.IGNORECASE)
            if match:
                month_str = match.group(1).lower()
                year_str = match.group(2)
                
                month_idx = None
                if month_str in month_names:
                    month_idx = month_names.index(month_str) + 1
                elif month_str in month_abbrevs:
                    month_idx = month_abbrevs.index(month_str) + 1
                
                if month_idx:
                    try:
                        year = int(year_str)
                        from datetime import date
                        start_date = date(year, month_idx, 1)
                        if month_idx == 12:
                            end_date = date(year + 1, 1, 1) - timedelta(days=1)
                        else:
                            end_date = date(year, month_idx + 1, 1) - timedelta(days=1)
                        
                        filters['start_date'] = start_date
                        filters['end_date'] = end_date
                        logger.info(f"Fallback parsed date: {start_date} to {end_date}")
                    except ValueError:
                        pass
        
        return filters
    
    def _find_closest_suppliers(self, requested_name: str, available_suppliers: List[str], max_results: int = 5) -> List[Tuple[str, float]]:
        """
        Find closest matching suppliers using simple string similarity
        
        Args:
            requested_name: The supplier name requested by user
            available_suppliers: List of all available supplier names
            max_results: Maximum number of suggestions to return
            
        Returns:
            List of tuples (supplier_name, similarity_score) sorted by score descending
        """
        requested_lower = requested_name.lower()
        scores = []
        
        for supplier in available_suppliers:
            if not supplier:
                continue
                
            supplier_lower = supplier.lower()
            
            # Calculate similarity score
            score = 0.0
            
            # Exact match
            if supplier_lower == requested_lower:
                score = 1.0
            # Contains match (requested in supplier or supplier in requested)
            elif requested_lower in supplier_lower or supplier_lower in requested_lower:
                # Longer the overlap, higher the score
                overlap = min(len(requested_lower), len(supplier_lower))
                total = max(len(requested_lower), len(supplier_lower))
                score = overlap / total * 0.8
            # Word-based matching
            else:
                requested_words = set(requested_lower.split())
                supplier_words = set(supplier_lower.split())
                if requested_words and supplier_words:
                    common_words = requested_words.intersection(supplier_words)
                    if common_words:
                        # Score based on common words
                        score = len(common_words) / max(len(requested_words), len(supplier_words)) * 0.6
            
            if score > 0:
                scores.append((supplier, score))
        
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        
        return scores[:max_results]
    
    def _format_price(self, price: Any) -> str:
        """Format price for email (remove decimals if whole number)"""
        # Handle None, NaN, or invalid values
        if price is None:
            return "N/A"
        
        try:
            # Convert to float if it's not already
            price_float = float(price)
            
            # Check for NaN or infinity
            import math
            if math.isnan(price_float) or math.isinf(price_float):
                return "N/A"
            
            # Format the price
            if price_float == int(price_float):
                return str(int(price_float))
            return f"{price_float:.2f}".rstrip('0').rstrip('.')
        except (ValueError, TypeError):
            return "N/A"
    
    def _validate_price_increase_item(self, item: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate a price increase item and return (is_valid, error_message)
        
        Args:
            item: Item dictionary with price increase data
            
        Returns:
            Tuple of (is_valid: bool, error_message: str)
        """
        errors = []
        
        # Check supplier name
        supplier_name = item.get('supplier_name') or item.get('vendor')
        if not supplier_name or not supplier_name.strip():
            errors.append("missing supplier name")
        
        # Check invoice number
        invoice_number = item.get('invoice_number') or item.get('ref_no')
        if not invoice_number or not str(invoice_number).strip():
            errors.append("missing invoice number")
        
        # Check item code
        item_code = item.get('item')
        if not item_code or not str(item_code).strip():
            errors.append("missing item code")
        
        # Check prices - at least one should be valid
        current_price = item.get('current_price')
        previous_price = item.get('previous_price')
        
        # Validate current_price
        current_valid = False
        if current_price is not None:
            try:
                import math
                current_float = float(current_price)
                if not (math.isnan(current_float) or math.isinf(current_float) or current_float < 0):
                    current_valid = True
            except (ValueError, TypeError):
                pass
        
        # Validate previous_price
        previous_valid = False
        if previous_price is not None:
            try:
                import math
                previous_float = float(previous_price)
                if not (math.isnan(previous_float) or math.isinf(previous_float) or previous_float < 0):
                    previous_valid = True
            except (ValueError, TypeError):
                pass
        
        # At least one price must be valid
        if not current_valid and not previous_valid:
            errors.append("missing or invalid prices")
        elif not current_valid:
            errors.append("missing or invalid current price")
        elif not previous_valid:
            errors.append("missing or invalid previous price")
        
        # Check if price difference makes sense (current should be higher for price increase)
        if current_valid and previous_valid:
            try:
                current_float = float(current_price)
                previous_float = float(previous_price)
                if current_float <= previous_float:
                    # This is not a price increase, but we'll still include it with a note
                    pass  # We'll handle this in the email generation
            except (ValueError, TypeError):
                pass
        
        if errors:
            return False, ", ".join(errors)
        return True, ""
    
    def _normalize_supplier_name(self, supplier_name: Any) -> str:
        """
        Normalize supplier name, handling None, empty strings, and invalid values
        
        Args:
            supplier_name: Supplier name (can be None, string, or other)
            
        Returns:
            Normalized supplier name or "Unknown Supplier"
        """
        if not supplier_name:
            return "Unknown Supplier"
        
        try:
            supplier_str = str(supplier_name).strip()
            if not supplier_str:
                return "Unknown Supplier"
            return supplier_str
        except Exception:
            return "Unknown Supplier"
    
    def _normalize_invoice_number(self, invoice_number: Any) -> str:
        """
        Normalize invoice number, handling None, empty strings, and invalid values
        
        Args:
            invoice_number: Invoice number (can be None, string, or other)
            
        Returns:
            Normalized invoice number or "Unknown"
        """
        if not invoice_number:
            return "Unknown"
        
        try:
            invoice_str = str(invoice_number).strip()
            if not invoice_str:
                return "Unknown"
            return invoice_str
        except Exception:
            return "Unknown"
    
    def _normalize_item_code(self, item_code: Any) -> str:
        """
        Normalize item code, handling None, empty strings, and invalid values
        
        Args:
            item_code: Item code (can be None, string, or other)
            
        Returns:
            Normalized item code or "N/A"
        """
        if not item_code:
            return "N/A"
        
        try:
            item_str = str(item_code).strip()
            if not item_str:
                return "N/A"
            # Remove suffix from item code (everything after dash)
            if '-' in item_str:
                item_str = item_str.split('-')[0]
            return item_str
        except Exception:
            return "N/A"
    
    def _wrap_text(self, text: str, max_width: int = 29) -> str:
        """
        Wrap text to fit within max_width characters per line
        
        Args:
            text: Text to wrap
            max_width: Maximum characters per line (default 29)
            
        Returns:
            Wrapped text with line breaks
        """
        if len(text) <= max_width:
            return text
        
        words = text.split()
        lines = []
        current_line = []
        current_length = 0
        
        for word in words:
            word_length = len(word)
            # Check if adding this word would exceed the limit
            # Account for space between words
            space_needed = 1 if current_line else 0
            if current_length + space_needed + word_length <= max_width:
                current_line.append(word)
                current_length += space_needed + word_length
            else:
                # Start a new line
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
                current_length = word_length
        
        # Add the last line
        if current_line:
            lines.append(" ".join(current_line))
        
        return "\n".join(lines)
    
    def _format_date_context(self, date_obj: Any) -> str:
        """Format date for context in email (e.g., 'Nov 24')"""
        if not date_obj:
            return ""
        
        try:
            if isinstance(date_obj, str):
                date_obj = datetime.fromisoformat(date_obj).date()
            elif hasattr(date_obj, 'date'):
                date_obj = date_obj.date()
            
            month_names = [
                'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
            ]
            
            month = month_names[date_obj.month - 1]
            year = str(date_obj.year)[-2:]  # Last 2 digits
            return f"{month} {year}"
        except Exception:
            return ""
    
    def _strip_markdown_from_email(self, email_content: str) -> str:
        """
        Strip markdown formatting from email content for plain text copying
        
        Args:
            email_content: Email content with markdown formatting
            
        Returns:
            Plain text email without markdown
        """
        if not email_content:
            return ""
        
        import re
        
        # Remove bold markdown (**text** or __text__)
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', email_content)
        text = re.sub(r'__(.+?)__', r'\1', text)
        
        # Remove italic markdown (*text* or _text_)
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'\1', text)
        text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'\1', text)
        
        # Remove headers (# Header)
        text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)
        
        # Remove links [text](url) -> text
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        
        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', '', text)
        
        # Remove inline code `code` -> code
        text = re.sub(r'`([^`]+)`', r'\1', text)
        
        # Remove horizontal rules
        text = re.sub(r'^---$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\*\*\*$', '', text, flags=re.MULTILINE)
        
        # Clean up extra whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()
    
    def _generate_supplier_email(
        self,
        supplier_name: str,
        items: List[Dict[str, Any]]
    ) -> str:
        """
        Generate email content for a supplier with price increases
        
        Args:
            supplier_name: Supplier name
            items: List of items with price increases
            
        Returns:
            Formatted email string
        """
        email_lines = ["Hi,", "", ""]
        intro_text = (
            "While relieving our invoices I noticed that we charged "
            "different prices from the past, see below."
        )
        # Wrap intro text to fit chatbot width
        wrapped_intro = self._wrap_text(intro_text, max_width=29)
        email_lines.extend(wrapped_intro.split("\n"))
        email_lines.append("")
        email_lines.append("**Price Increases:**")
        email_lines.append("")
        
        # Validate and filter items, track invalid ones
        valid_items = []
        invalid_items = []
        
        for item in items:
            is_valid, error_msg = self._validate_price_increase_item(item)
            if is_valid:
                valid_items.append(item)
            else:
                invalid_items.append((item, error_msg))
                logger.warning(
                    f"Skipping invalid price increase item: {error_msg}. "
                    f"Item: {item.get('item', 'N/A')}, "
                    f"Invoice: {item.get('invoice_number', 'N/A')}, "
                    f"Supplier: {item.get('supplier_name', 'N/A')}"
                )
        
        # If no valid items, return a message
        if not valid_items:
            email_lines.append("No valid price increase items found for this supplier.")
            email_lines.append("")
            if invalid_items:
                email_lines.append(f"Note: {len(invalid_items)} item(s) were skipped due to missing or invalid data.")
            email_lines.append("")
            email_lines.append("Thanks")
            return "\n".join(email_lines)
        
        # Group valid items by invoice number
        items_by_invoice = {}
        for item in valid_items:
            invoice_num = self._normalize_invoice_number(
                item.get('invoice_number') or item.get('ref_no')
            )
            if invoice_num not in items_by_invoice:
                items_by_invoice[invoice_num] = []
            items_by_invoice[invoice_num].append(item)
        
        # Counter for numbering items
        item_counter = 0
        
        # Generate lines for each invoice group
        invoice_list = list(items_by_invoice.items())
        for idx, (invoice_num, invoice_items) in enumerate(invoice_list):
            # Add spacing before each invoice group (except first)
            if idx > 0:
                email_lines.append("")
            
            # Generate lines for each item in this invoice
            for item in invoice_items:
                # Use normalized values with fallbacks
                item_code = self._normalize_item_code(item.get('item'))
                current_price = item.get('current_price')
                previous_price = item.get('previous_price')
                qty = item.get('quantity', 1)
                
                # Validate prices one more time before formatting
                try:
                    import math
                    current_valid = (
                        current_price is not None and
                        not math.isnan(float(current_price)) and
                        not math.isinf(float(current_price))
                    )
                    previous_valid = (
                        previous_price is not None and
                        not math.isnan(float(previous_price)) and
                        not math.isinf(float(previous_price))
                    )
                except (ValueError, TypeError):
                    current_valid = False
                    previous_valid = False
                
                # Format the line with fallbacks
                if not current_valid and not previous_valid:
                    # Both prices invalid - skip this item
                    logger.warning(f"Skipping item {item_code} - both prices invalid")
                    continue
                
                # Increment counter for valid items
                item_counter += 1
                
                if not current_valid:
                    # Only previous price valid
                    line = f"{item_counter}. On invoice {invoice_num} item {item_code} "
                    line += "we used to be charged "
                    line += f"{self._format_price(previous_price)} in the past, "
                    line += "now we were charged N/A (price data unavailable)"
                elif not previous_valid:
                    # Only current price valid
                    line = f"{item_counter}. On invoice {invoice_num} item {item_code} "
                    line += "we were charged "
                    line += f"{self._format_price(current_price)} "
                    line += "(previous price data unavailable)"
                else:
                    # Both prices valid - normal case
                    line = f"{item_counter}. On invoice {invoice_num} item {item_code} "
                    line += "we used to be charged "
                    line += f"{self._format_price(previous_price)} in the past, "
                    line += f"now we were charged {self._format_price(current_price)}"
                
                # Add quantity if > 1
                if qty and qty > 1:
                    line += f" (QTY was {qty})"
                
                # Wrap the line to fit chatbot width (29 characters)
                wrapped_line = self._wrap_text(line, max_width=29)
                email_lines.extend(wrapped_line.split("\n"))
                # Add blank line after each item for proper spacing
                email_lines.append("")
        
        # Add note about invalid items if any
        if invalid_items:
            email_lines.append("")
            email_lines.append(f"Note: {len(invalid_items)} item(s) were excluded due to missing or invalid data.")
        
        # Add two blank lines before Thanks
        email_lines.append("")
        email_lines.append("Thanks")
        
        # Join all lines into a single string with newlines
        # Ensure proper newline formatting
        email_content = "\n".join(email_lines)
        
        # Make sure the format is exact - no extra processing
        return email_content
    
    async def process(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process email generation request
        
        Handles:
        - Supplier refund emails for price increases
        - Other email generation requests
        
        Args:
            request: Request dictionary with question, session_id, context
            
        Returns:
            Response with generated email(s) or error
        """
        try:
            question = request["question"]
            context = request.get("context", {})
            
            logger.info(f"Email Agent processing: {question[:100]}...")
            
            # Check if this is a price increase email request
            if self._is_price_increase_request(question):
                return await self._process_price_increase_email(request)
            
            # Check if this is a general supplier email request
            if self._is_general_supplier_email_request(question):
                return await self._process_general_supplier_email(request)
            
            # Placeholder for other email types
            return {
                "success": False,
                "data": None,
                "error": "Email generation not yet implemented for this request type.",
                "metadata": {
                    "agent": self.agent_name,
                    "status": "not_implemented"
                }
            }
            
        except Exception as e:
            logger.error(f"Email Agent error: {e}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"Email generation failed: {str(e)}",
                "metadata": {"agent": self.agent_name}
            }
    
    async def _process_price_increase_email(
        self,
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process price increase email generation request
        
        Flow:
        1. Query invoice items with positive price differences
        2. Group by supplier
        3. Generate formatted emails
        
        Args:
            request: Request dictionary
            
        Returns:
            Response with generated emails
        """
        try:
            from mpi_backend.database import get_db
            from mpi_backend.database.controllers.InvoiceItems import (
                InvoiceItemController
            )
            
            # Get database session
            db = next(get_db())
            
            try:
                # Parse filters from question using LLM
                question = request.get("question", "")
                filters = await self._parse_filters_from_question(question)
                logger.info(f"Parsed filters from question '{question}': {filters}")
                
                # Safety check: Remove supplier_name if it looks like an action phrase
                if 'supplier_name' in filters:
                    supplier_name = filters['supplier_name'].lower()
                    excluded_phrases = [
                        'generate', 'create', 'make', 'write', 'email', 'price',
                        'increase', 'item', 'items'
                    ]
                    # If supplier name contains action words, it's probably not a supplier
                    if any(phrase in supplier_name for phrase in excluded_phrases):
                        logger.warning(
                            f"Removing invalid supplier name '{filters['supplier_name']}' "
                            f"- contains action words"
                        )
                        del filters['supplier_name']
                
                # Debug: Log date filters specifically
                if filters:
                    if 'start_date' in filters:
                        logger.info(f"Date filter - start_date: {filters['start_date']} (type: {type(filters['start_date'])})")
                    if 'end_date' in filters:
                        logger.info(f"Date filter - end_date: {filters['end_date']} (type: {type(filters['end_date'])})")
                    if 'supplier_name' in filters:
                        logger.info(f"Supplier filter: {filters['supplier_name']}")
                
                # Get price increase details with filters
                controller = InvoiceItemController(db)
                price_increases = controller.get_price_increase_details(filters=filters)
                logger.info(f"Found {len(price_increases)} items after filtering")
                
                # Debug: Log sample results if any
                if price_increases and len(price_increases) > 0:
                    sample = price_increases[0]
                    logger.info(
                        f"Sample result: item={sample.get('item')}, "
                        f"date={sample.get('date')}, "
                        f"supplier={sample.get('supplier_name')}, "
                        f"current={sample.get('current_price')}, "
                        f"previous={sample.get('previous_price')}, "
                        f"percentage={sample.get('percentage_increase')}"
                    )
                
                if not price_increases:
                    # If supplier filter was provided, check if supplier(s) exist
                    requested_suppliers = []
                    if filters and 'supplier_names' in filters:
                        requested_suppliers = filters['supplier_names']
                    elif filters and 'supplier_name' in filters:
                        requested_suppliers = [filters['supplier_name']]
                    
                    if requested_suppliers:
                        from mpi_backend.database.models.Suppliers import Supplier
                        all_suppliers = db.query(Supplier.supplier_name).distinct().all()
                        all_supplier_names = [s[0] for s in all_suppliers if s[0] and s[0].strip()]
                        
                        # Check which suppliers exist and which don't
                        existing_suppliers = []
                        missing_suppliers = []
                        
                        for requested_supplier in requested_suppliers:
                            requested_lower = requested_supplier.lower().strip()
                            supplier_exists = db.query(Supplier).filter(
                                func.lower(Supplier.supplier_name) == requested_lower
                            ).first()
                            
                            if supplier_exists:
                                existing_suppliers.append(supplier_exists.supplier_name)
                            else:
                                missing_suppliers.append(requested_supplier)
                        
                        # If some suppliers don't exist, provide suggestions
                        if missing_suppliers:
                            suggestions_text = ""
                            for missing_supplier in missing_suppliers:
                                suggestions = self._find_closest_suppliers(missing_supplier, all_supplier_names)
                                if suggestions:
                                    suggestions_text += f"\n\nFor '{missing_supplier}', did you mean:\n"
                                    for i, (supplier, score) in enumerate(suggestions[:3], 1):
                                        suggestions_text += f"  {i}. {supplier}\n"
                            
                            # Build date context
                            date_context = ""
                            if 'start_date' in filters:
                                month_name = filters['start_date'].strftime('%B %Y')
                                date_context = f" for {month_name}"
                            
                            supplier_list = ", ".join(missing_suppliers)
                            error_msg = f"Supplier(s) '{supplier_list}' do not exist{date_context}.{suggestions_text}\n\nPlease provide the correct supplier name(s) and try again."
                            return {
                                "success": False,
                                "data": {
                                    "answer": error_msg
                                },
                                "error": error_msg,
                                "metadata": {
                                    "agent": self.agent_name,
                                    "status": "supplier_not_found",
                                    "requested_suppliers": requested_suppliers,
                                    "missing_suppliers": missing_suppliers,
                                    "existing_suppliers": existing_suppliers
                                }
                            }
                        
                        # All suppliers exist but no price increases
                        if existing_suppliers:
                            date_context = ""
                            if 'start_date' in filters:
                                month_name = filters['start_date'].strftime('%B %Y')
                                date_context = f" in {month_name}"
                            
                            supplier_list = ", ".join(existing_suppliers)
                            error_msg = f"Supplier(s) '{supplier_list}' exist but have no price increases{date_context}. Please check the date range or try a different supplier."
                            return {
                                "success": False,
                                "data": {
                                    "answer": error_msg
                                },
                                "error": error_msg,
                                "metadata": {
                                    "agent": self.agent_name,
                                    "status": "no_increases_for_supplier",
                                    "requested_suppliers": requested_suppliers,
                                    "supplier_exists": True
                                }
                            }
                    
                    # No supplier filter or supplier exists but no increases
                    # Build message with filter context
                    filter_msg = "No increased prices detected"
                    if filters:
                        filter_parts = []
                        if 'supplier_names' in filters:
                            supplier_list = ", ".join(filters['supplier_names'])
                            filter_parts.append(f"for {supplier_list}")
                        elif 'supplier_name' in filters:
                            filter_parts.append(f"for {filters['supplier_name']}")
                        if 'start_date' in filters and 'end_date' in filters:
                            start_str = filters['start_date'].strftime('%B %d, %Y')
                            end_str = filters['end_date'].strftime('%B %d, %Y')
                            if start_str[:7] == end_str[:7]:  # Same month
                                month_name = filters['start_date'].strftime('%B %Y')
                                filter_parts.append(f"in {month_name}")
                            else:
                                filter_parts.append(f"between {start_str} and {end_str}")
                        elif 'start_date' in filters:
                            month_name = filters['start_date'].strftime('%B %Y')
                            filter_parts.append(f"in {month_name}")
                        if filter_parts:
                            filter_msg += " " + " ".join(filter_parts)
                    filter_msg += "."
                    
                    return {
                        "success": True,
                        "data": {
                            "answer": filter_msg,
                            "emails": [],
                            "count": 0
                        },
                        "error": None,
                        "metadata": {
                            "agent": self.agent_name,
                            "status": "no_increases",
                            "filters_applied": filters
                        }
                    }
                
                # Validate and filter items first
                valid_price_increases = []
                invalid_count = 0
                for item in price_increases:
                    is_valid, error_msg = self._validate_price_increase_item(item)
                    if is_valid:
                        valid_price_increases.append(item)
                    else:
                        invalid_count += 1
                        logger.warning(
                            f"Filtering out invalid price increase item: {error_msg}. "
                            f"Item: {item.get('item', 'N/A')}, "
                            f"Invoice: {item.get('invoice_number', 'N/A')}"
                        )
                
                if invalid_count > 0:
                    logger.info(f"Filtered out {invalid_count} invalid item(s) from price increases")
                
                # If no valid items after filtering, return appropriate message
                if not valid_price_increases:
                    requested_suppliers = []
                    if filters and 'supplier_names' in filters:
                        requested_suppliers = filters['supplier_names']
                    elif filters and 'supplier_name' in filters:
                        requested_suppliers = [filters['supplier_name']]
                    
                    if requested_suppliers:
                        supplier_list = ", ".join(requested_suppliers)
                        error_msg = (
                            f"No valid price increase items found for supplier(s) '{supplier_list}'. "
                            f"All {len(price_increases)} item(s) had missing or invalid data "
                            f"(e.g., missing prices, supplier names, or invoice numbers)."
                        )
                    else:
                        error_msg = (
                            f"No valid price increase items found. "
                            f"All {len(price_increases)} item(s) had missing or invalid data "
                            f"(e.g., missing prices, supplier names, or invoice numbers)."
                        )
                    
                    return {
                        "success": False,
                        "data": {
                            "answer": error_msg
                        },
                        "error": error_msg,
                        "metadata": {
                            "agent": self.agent_name,
                            "status": "no_valid_items",
                            "total_items": len(price_increases),
                            "invalid_items": invalid_count
                        }
                    }
                
                # Group by supplier (using normalized names)
                suppliers_items = {}
                for item in valid_price_increases:
                    # Normalize supplier name with fallback
                    supplier_name = self._normalize_supplier_name(
                        item.get('supplier_name') or item.get('vendor')
                    )
                    if supplier_name not in suppliers_items:
                        suppliers_items[supplier_name] = []
                    suppliers_items[supplier_name].append(item)
                
                # Keep original suppliers_items for additional matching attempts
                original_suppliers_items = suppliers_items.copy()
                
                # If supplier filter was applied, filter to only requested suppliers (case-insensitive)
                requested_suppliers = []
                unmatched_suppliers = []  # Initialize outside conditional for use in response formatting
                if filters and 'supplier_names' in filters:
                    requested_suppliers = filters['supplier_names']
                elif filters and 'supplier_name' in filters:
                    requested_suppliers = [filters['supplier_name']]
                
                if requested_suppliers:
                    # Normalize requested suppliers to lowercase for matching
                    requested_suppliers_lower = [s.lower().strip() for s in requested_suppliers]
                    
                    # Find matching suppliers from results (case-insensitive)
                    # Use a set to track which suppliers from results have been matched
                    matched_suppliers = {}
                    unmatched_suppliers = []  # Reset for this matching attempt
                    matched_result_suppliers = set()  # Track which result suppliers we've matched
                    
                    logger.info(f"Looking for suppliers: {requested_suppliers}")
                    logger.info(f"Available suppliers in results: {list(suppliers_items.keys())}")
                    
                    for requested_supplier in requested_suppliers:
                        requested_lower = requested_supplier.lower().strip()
                        found_match = False
                        best_match = None
                        best_match_score = 0
                        
                        # Try to find the best match for this requested supplier
                        for supplier_name in suppliers_items.keys():
                            # Skip if this supplier was already matched to another requested supplier
                            if supplier_name in matched_result_suppliers:
                                continue
                            
                            supplier_lower = supplier_name.lower().strip()
                            
                            # Calculate match score (higher is better)
                            match_score = 0
                            
                            # Exact match gets highest score
                            if supplier_lower == requested_lower:
                                match_score = 100
                            # Requested is contained in supplier name
                            elif requested_lower in supplier_lower:
                                match_score = 80 - len(supplier_lower) + len(requested_lower)  # Prefer shorter matches
                            # Supplier name is contained in requested
                            elif supplier_lower in requested_lower:
                                match_score = 70 - len(requested_lower) + len(supplier_lower)
                            # Word-based matching
                            else:
                                requested_words = set(requested_lower.split())
                                supplier_words = set(supplier_lower.split())
                                common_words = requested_words.intersection(supplier_words)
                                if common_words:
                                    # Score based on common words and their length
                                    match_score = sum(len(word) for word in common_words) * 10
                            
                            if match_score > best_match_score and match_score > 0:
                                best_match = supplier_name
                                best_match_score = match_score
                        
                        # Use the best match if found
                        if best_match and best_match_score > 0:
                            matched_suppliers[best_match] = suppliers_items[best_match]
                            matched_result_suppliers.add(best_match)
                            found_match = True
                            logger.info(f"Matched supplier: '{requested_supplier}' -> '{best_match}' (score: {best_match_score})")
                        else:
                            unmatched_suppliers.append(requested_supplier)
                            logger.warning(f"No match found for requested supplier: '{requested_supplier}'")
                    
                    # If we found matches, use only those
                    if matched_suppliers:
                        suppliers_items = matched_suppliers
                        logger.info(f"Filtered to {len(matched_suppliers)} supplier(s): {list(matched_suppliers.keys())}")
                        
                        # If some suppliers weren't found, try to find them in all available suppliers
                        if unmatched_suppliers:
                            logger.warning(f"Some suppliers not found in results: {unmatched_suppliers}")
                            # Log available suppliers for debugging
                            all_available = list(suppliers_items.keys())
                            logger.info(f"Available suppliers in results were: {all_available}")
                            
                            # Try to find unmatched suppliers in the database to get suggestions
                            from mpi_backend.database.models.Suppliers import Supplier
                            all_db_suppliers = db.query(Supplier.supplier_name).distinct().all()
                            all_db_supplier_names = [s[0] for s in all_db_suppliers if s[0] and s[0].strip()]
                            
                            # Check if unmatched suppliers exist in DB but just didn't have price increases
                            for unmatched in unmatched_suppliers:
                                unmatched_lower = unmatched.lower().strip()
                                db_match = None
                                for db_supplier in all_db_supplier_names:
                                    if unmatched_lower == db_supplier.lower().strip():
                                        db_match = db_supplier
                                        break
                                
                                if db_match:
                                    logger.info(f"Supplier '{unmatched}' exists in database but has no price increases in the date range")
                                else:
                                    logger.warning(f"Supplier '{unmatched}' not found in database")
                            
                            # If we have multiple requested suppliers but only found some, 
                            # still show all found suppliers (don't fail completely)
                            if len(requested_suppliers) > 1 and len(matched_suppliers) > 0:
                                logger.info(f"Continuing with {len(matched_suppliers)} found supplier(s) out of {len(requested_suppliers)} requested")
                                
                                # Also check if there are other suppliers in results that we didn't match
                                # This handles cases where supplier name in DB is slightly different
                                all_result_suppliers = set(original_suppliers_items.keys())
                                unmatched_result_suppliers = all_result_suppliers - set(matched_suppliers.keys())
                                
                                if unmatched_result_suppliers:
                                    logger.info(f"Found additional suppliers in results that weren't matched: {unmatched_result_suppliers}")
                                    # Try to match unmatched result suppliers to unmatched requested suppliers
                                    for result_supplier in unmatched_result_suppliers:
                                        result_lower = result_supplier.lower()
                                        for unmatched_requested in unmatched_suppliers:
                                            requested_lower = unmatched_requested.lower()
                                            # Check if they might be the same supplier with different naming
                                            if (requested_lower in result_lower or 
                                                result_lower in requested_lower or
                                                len(set(requested_lower.split()) & set(result_lower.split())) >= 2):
                                                # Likely the same supplier - include it
                                                matched_suppliers[result_supplier] = original_suppliers_items[result_supplier]
                                                logger.info(f"Matched additional supplier: '{unmatched_requested}' -> '{result_supplier}'")
                                                # Remove from unmatched list since we found it
                                                if unmatched_requested in unmatched_suppliers:
                                                    unmatched_suppliers.remove(unmatched_requested)
                                                break
                                
                                # Update suppliers_items with all matched suppliers
                                suppliers_items = matched_suppliers
                                logger.info(f"Final supplier list: {list(suppliers_items.keys())}")
                    else:
                        # No matches found - provide suggestions
                        suppliers_from_results = list(suppliers_items.keys())
                        from mpi_backend.database.models.Suppliers import Supplier
                        all_suppliers = db.query(Supplier.supplier_name).distinct().all()
                        all_supplier_names = [s[0] for s in all_suppliers if s[0] and s[0].strip()]
                        combined_suppliers = list(set(suppliers_from_results + all_supplier_names))
                        
                        # Build suggestions for all unmatched suppliers
                        suggestion_text = ""
                        for unmatched in unmatched_suppliers:
                            suggestions = self._find_closest_suppliers(unmatched, combined_suppliers)
                            if suggestions:
                                suggestion_text += f"\n\nFor '{unmatched}', did you mean:\n"
                                for i, (supplier, score) in enumerate(suggestions[:3], 1):
                                    has_increases = supplier in suppliers_from_results
                                    marker = " (has price increases)" if has_increases else ""
                                    suggestion_text += f"  {i}. {supplier}{marker}\n"
                        
                        # Build date context
                        date_context = ""
                        if filters and 'start_date' in filters:
                            month_name = filters['start_date'].strftime('%B %Y')
                            date_context = f" for {month_name}"
                        
                        supplier_list = ", ".join(unmatched_suppliers)
                        error_msg = f"Supplier(s) '{supplier_list}' not found{date_context}.{suggestion_text}\n\nPlease provide the correct supplier name(s) and try again."
                        return {
                            "success": False,
                            "data": {
                                "answer": error_msg
                            },
                            "error": error_msg,
                            "metadata": {
                                "agent": self.agent_name,
                                "status": "supplier_not_found",
                                "requested_suppliers": requested_suppliers,
                                "suggestions": [s[0] for s in suggestions[:5]] if suggestions else [],
                                "available_suppliers_with_increases": suppliers_from_results
                            }
                        }
                
                # Generate emails for each supplier
                emails = []
                total_valid_items = 0
                for supplier_name, items in suppliers_items.items():
                    email_content = self._generate_supplier_email(
                        supplier_name,
                        items
                    )
                    # Create plain text version (without markdown) for copying
                    plain_text_content = self._strip_markdown_from_email(email_content)
                    emails.append({
                        "supplier": supplier_name,
                        "content": email_content,  # Keep markdown for display
                        "plain_text": plain_text_content,  # Plain text for copying
                        "item_count": len(items)
                    })
                    total_valid_items += len(items)
                
                # Format response message
                # If specific supplier(s) were requested, check format
                requested_suppliers_count = len(requested_suppliers) if requested_suppliers else 0
                
                # Only use simplified format for single supplier with single email
                if requested_suppliers_count == 1 and len(emails) == 1:
                    # Simple format: just the email ready to paste (complete and ready)
                    email_content = emails[0]['content']
                    # Preserve ALL newlines exactly as generated - don't modify the content
                    answer = email_content
                    # Add a note about how many items if it's a long list
                    item_count = emails[0]['item_count']
                    if item_count > 20:
                        answer = f"{answer}\n\n(Note: This email includes {item_count} items with price increases)"
                else:
                    # Multiple suppliers or no filter - show clean, copy-friendly format
                    answer_parts = [
                        f"**Found {len(valid_price_increases)} valid items with price increases**"
                    ]
                    
                    # Add note about filtered items if any
                    if invalid_count > 0:
                        answer_parts.append(f"(Filtered out {invalid_count} item(s) with missing or invalid data)")
                    
                    # Add filter context if filters were applied
                    if filters:
                        filter_parts = []
                        if 'supplier_names' in filters:
                            supplier_list = ", ".join(filters['supplier_names'])
                            filter_parts.append(f"for **{supplier_list}**")
                        elif 'supplier_name' in filters:
                            filter_parts.append(f"for **{filters['supplier_name']}**")
                        if 'start_date' in filters and 'end_date' in filters:
                            start_str = filters['start_date'].strftime('%B %d, %Y')
                            end_str = filters['end_date'].strftime('%B %d, %Y')
                            if start_str[:7] == end_str[:7]:  # Same month
                                month_name = filters['start_date'].strftime('%B %Y')
                                filter_parts.append(f"in **{month_name}**")
                            else:
                                filter_parts.append(f"between **{start_str}** and **{end_str}**")
                        elif 'start_date' in filters:
                            month_name = filters['start_date'].strftime('%B %Y')
                            filter_parts.append(f"in **{month_name}**")
                        if filter_parts:
                            answer_parts.append(" ".join(filter_parts))
                    
                    answer_parts.extend([
                        "",
                        f"**Generated {len(emails)} email(s) for supplier(s):**"
                    ])
                    
                    for email_data in emails:
                        answer_parts.append(f"  • **{email_data['supplier']}** ({email_data['item_count']} items)")
                    
                    # If multiple suppliers were requested but some weren't found, add a note
                    if requested_suppliers_count > 1 and unmatched_suppliers:
                        found_supplier_names = [e['supplier'] for e in emails]
                        answer_parts.append("")
                        answer_parts.append(f"**Note:** Requested {len(requested_suppliers)} supplier(s), but only found price increases for {len(emails)} supplier(s).")
                        answer_parts.append(f"Found: {', '.join(found_supplier_names)}")
                        answer_parts.append(f"Not found in results: {', '.join(unmatched_suppliers)}")
                    
                    answer_parts.extend([
                        "",
                        "",
                        "**EMAILS READY TO COPY**",
                        "",
                        ""
                    ])
                    
                    # Format each email for easy copying
                    for i, email_data in enumerate(emails, 1):
                        answer_parts.extend([
                            f"**EMAIL {i}: {email_data['supplier']} ({email_data['item_count']} items)**",
                            "",
                            "",
                            email_data['content'],
                            "",
                            "",
                            ""
                        ])
                    
                    answer = "\n".join(answer_parts).strip()
                
                return {
                    "success": True,
                    "data": {
                        "answer": answer,
                        "emails": emails,
                        "count": len(valid_price_increases),
                        "supplier_count": len(emails),
                        "filtered_count": invalid_count
                    },
                    "error": None,
                    "metadata": {
                        "agent": self.agent_name,
                        "status": "completed",
                        "emails": emails,  # Include emails in metadata for frontend
                        "total_items": len(price_increases),
                        "valid_items": len(valid_price_increases),
                        "filtered_items": invalid_count
                    }
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(
                f"Error processing price increase email: {e}",
                exc_info=True
            )
            return {
                "success": False,
                "data": None,
                "error": f"Failed to generate price increase emails: {str(e)}",
                "metadata": {"agent": self.agent_name}
            }
    
    async def _process_general_supplier_email(
        self,
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process general supplier email generation request
        
        Generates an email summarizing invoices/items for a supplier in a specific month/period.
        
        Args:
            request: Request dictionary
            
        Returns:
            Response with generated email
        """
        try:
            from mpi_backend.database import get_db
            from mpi_backend.database.controllers.InvoiceItems import (
                InvoiceItemController
            )
            from mpi_backend.database.models.Suppliers import Supplier
            from sqlalchemy import func
            
            # Get database session
            db = next(get_db())
            
            try:
                # Parse filters from question using LLM
                question = request.get("question", "")
                filters = await self._parse_filters_from_question(question)
                logger.info(f"Parsed filters from question '{question}': {filters}")
                
                # Validate that we have supplier and date filters
                if not filters.get('supplier_name'):
                    return {
                        "success": False,
                        "data": None,
                        "error": "Please specify a supplier name. Example: 'Generate an email for World Wide Plumbing Supplies for October 2025'",
                        "metadata": {
                            "agent": self.agent_name,
                            "status": "missing_supplier"
                        }
                    }
                
                if not filters.get('start_date') or not filters.get('end_date'):
                    return {
                        "success": False,
                        "data": None,
                        "error": "Please specify a date range. Example: 'Generate an email for World Wide Plumbing Supplies for October 2025'",
                        "metadata": {
                            "agent": self.agent_name,
                            "status": "missing_date"
                        }
                    }
                
                supplier_name = filters['supplier_name']
                start_date = filters['start_date']
                end_date = filters['end_date']
                
                # Find supplier in database (case-insensitive)
                supplier = db.query(Supplier).filter(
                    func.lower(Supplier.supplier_name) == supplier_name.lower().strip()
                ).first()
                
                if not supplier:
                    # Try to find similar suppliers
                    all_suppliers = db.query(Supplier.supplier_name).distinct().all()
                    all_supplier_names = [s[0] for s in all_suppliers if s[0] and s[0].strip()]
                    
                    suggestions = self._find_closest_suppliers(supplier_name, all_supplier_names)
                    
                    suggestion_text = ""
                    if suggestions:
                        suggestion_text = f"\n\nDid you mean one of these suppliers?\n"
                        for i, (supp, score) in enumerate(suggestions[:5], 1):
                            suggestion_text += f"  {i}. {supp}\n"
                    
                    error_msg = f"Supplier '{supplier_name}' not found.{suggestion_text}\n\nPlease provide the correct supplier name and try again."
                    return {
                        "success": False,
                        "data": {
                            "answer": error_msg
                        },
                        "error": error_msg,
                        "metadata": {
                            "agent": self.agent_name,
                            "status": "supplier_not_found",
                            "requested_supplier": supplier_name,
                            "suggestions": [s[0] for s in suggestions[:5]] if suggestions else []
                        }
                    }
                
                # Query invoice items for this supplier and date range
                controller = InvoiceItemController(db)
                
                # Use the existing get_invoice_items_by_filters method
                # Note: This method expects vendor name, not supplier name
                # We need to check if vendor matches supplier name or use supplier_id
                supplier_id = supplier.id
                
                # Query invoice items by joining with invoices to get supplier_id
                from mpi_backend.database.models import InvoiceItem, Invoice
                
                query = db.query(InvoiceItem).join(
                    Invoice, InvoiceItem.invoice_id == Invoice.id
                ).filter(
                    Invoice.supplier_id == supplier_id,
                    InvoiceItem.date >= start_date,
                    InvoiceItem.date <= end_date,
                    InvoiceItem.is_active.isnot(False)
                ).order_by(InvoiceItem.date.desc(), InvoiceItem.ref_no)
                
                items = query.all()
                
                if not items:
                    month_name = start_date.strftime('%B %Y')
                    error_msg = f"No invoice items found for {supplier.supplier_name} in {month_name}."
                    return {
                        "success": True,
                        "data": {
                            "answer": error_msg,
                            "email": None
                        },
                        "error": None,
                        "metadata": {
                            "agent": self.agent_name,
                            "status": "no_items",
                            "supplier": supplier.supplier_name,
                            "date_range": f"{start_date} to {end_date}"
                        }
                    }
                
                # Generate email content
                email_content = self._generate_general_supplier_email(
                    supplier.supplier_name,
                    items,
                    start_date,
                    end_date
                )
                
                # Format response with bold heading
                month_name = start_date.strftime('%B %Y')
                answer = f"**Email for {supplier.supplier_name} - {month_name}:**\n\n{email_content}"
                
                # Create plain text version for copying
                plain_text_email = self._strip_markdown_from_email(email_content)
                
                return {
                    "success": True,
                    "data": {
                        "answer": answer,
                        "email": email_content,
                        "supplier": supplier.supplier_name,
                        "date_range": f"{start_date} to {end_date}",
                        "item_count": len(items)
                    },
                    "error": None,
                    "metadata": {
                        "agent": self.agent_name,
                        "status": "completed",
                        "emails": [{
                            "supplier": supplier.supplier_name,
                            "content": email_content,  # Keep markdown for display
                            "plain_text": plain_text_email,  # Plain text for copying
                            "item_count": len(items)
                        }]  # Include email in metadata for frontend
                    }
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(
                f"Error processing general supplier email: {e}",
                exc_info=True
            )
            return {
                "success": False,
                "data": None,
                "error": f"Failed to generate supplier email: {str(e)}",
                "metadata": {"agent": self.agent_name}
            }
    
    def _generate_general_supplier_email(
        self,
        supplier_name: str,
        items: List[Any],
        start_date: date,
        end_date: date
    ) -> str:
        """
        Generate email content for a supplier summarizing invoices/items for a period
        
        Args:
            supplier_name: Supplier name
            items: List of invoice items
            start_date: Start date of period
            end_date: End date of period
            
        Returns:
            Formatted email string
        """
        # Group items by invoice number
        items_by_invoice = {}
        total_amount = 0.0
        total_items = 0
        
        for item in items:
            invoice_num = item.ref_no or 'Unknown'
            if invoice_num not in items_by_invoice:
                items_by_invoice[invoice_num] = {
                    'date': item.date,
                    'items': [],
                    'total': 0.0
                }
            
            # Parse amount (stored as string in database)
            try:
                item_amount = float(item.amount) if item.amount else 0.0
            except (ValueError, TypeError):
                item_amount = 0.0
            items_by_invoice[invoice_num]['items'].append({
                'item': item.item or 'N/A',
                'description': item.description or '',
                'qty': item.qty or 1,
                'cost': item.cost or 0.0,
                'amount': item_amount
            })
            items_by_invoice[invoice_num]['total'] += item_amount
            total_amount += item_amount
            total_items += 1
        
        # Generate email content
        email_lines = []
        
        # Header
        month_name = start_date.strftime('%B %Y')
        email_lines.append(f"Hi,")
        email_lines.append("")
        email_lines.append(f"Please find below a summary of invoices from **{supplier_name}** for **{month_name}**:")
        email_lines.append("")
        email_lines.append("")
        
        # Summary with bold headings
        email_lines.append("**Summary:**")
        email_lines.append(f"**Total Invoices:** {len(items_by_invoice)}")
        email_lines.append(f"**Total Items:** {total_items}")
        email_lines.append(f"**Total Amount:** ${total_amount:,.2f}")
        email_lines.append("")
        email_lines.append("")
        
        # Invoice details
        email_lines.append("**Invoice Details:**")
        email_lines.append("")
        for invoice_num, invoice_data in sorted(items_by_invoice.items(), key=lambda x: x[1]['date'], reverse=True):
            invoice_date = invoice_data['date']
            invoice_items = invoice_data['items']
            invoice_total = invoice_data['total']
            
            email_lines.append(f"**Invoice:** {invoice_num} ({invoice_date.strftime('%Y-%m-%d')})")
            email_lines.append(f"**Total:** ${invoice_total:,.2f}")
            email_lines.append("")
            
            # List items (limit to first 10 items per invoice to keep email manageable)
            for item_data in invoice_items[:10]:
                item_code = item_data['item']
                description = item_data['description']
                qty = item_data['qty']
                cost = item_data['cost']
                amount = item_data['amount']
                
                line = f"  - {item_code}"
                if description:
                    # Truncate description if too long
                    desc = description[:50] + "..." if len(description) > 50 else description
                    line += f": {desc}"
                line += f" (Qty: {qty}, Cost: ${cost:.2f}, Amount: ${amount:.2f})"
                email_lines.append(line)
            
            if len(invoice_items) > 10:
                email_lines.append(f"  ... and {len(invoice_items) - 10} more items")
            
            email_lines.append("")
        
        email_lines.append("")
        email_lines.append("Thanks")
        
        return "\n".join(email_lines)
    
    def get_capabilities(self) -> List[AgentCapability]:
        """Get agent capabilities"""
        return [AgentCapability.SEND_EMAIL]

