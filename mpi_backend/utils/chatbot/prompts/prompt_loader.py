"""
Prompt Loader for QA System
Handles loading and caching of prompts from individual text files with template variable substitution.
"""

import json
import logging
import os
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class PromptLoader:
    """Loads and manages prompts from individual text files with caching and template substitution"""
    
    def __init__(self, prompts_dir: Optional[str] = None):
        """
        Initialize the prompt loader
        
        Args:
            prompts_dir: Directory containing prompt text files. 
                       Defaults to the prompts directory relative to this file.
        """
        if prompts_dir is None:
            # Get the directory containing this file
            current_dir = Path(__file__).parent
            self.prompts_dir = current_dir
        else:
            self.prompts_dir = Path(prompts_dir)
        
        # Cache for loaded prompts
        self._prompt_cache: Dict[str, str] = {}
        
        # Mapping of prompt types and keys to file names
        self.prompt_file_map = {
            'sql_generation': {
                'template': 'sql_generation.txt',
                'content': 'sql_generation.txt'  # Alias
            },
            'answer_formatting': {
                'standard': 'answer_formatting_standard.txt',
                'debug': 'answer_formatting_debug.txt'
            },
            'conversational_responses': {
                'greeting': 'conversational_greeting.txt',
                'farewell': 'conversational_farewell.txt',
                'help': 'conversational_help.txt',
                'system_info': 'conversational_system_info.txt',
                'small_talk': 'conversational_small_talk.txt',
                'capability_export': 'conversational_capability_export.txt',
                'capability_update': 'conversational_capability_update.txt',
                'capability_report': 'conversational_capability_report.txt',
                'capability_default': 'conversational_capability_default.txt',
                'clarification_default': 'conversational_clarification_default.txt',
                'clarification_invoices': 'conversational_clarification_invoices.txt',
                'clarification_suppliers': 'conversational_clarification_suppliers.txt',
                'clarification_items': 'conversational_clarification_items.txt',
                'clarification_customer_jobs': 'conversational_clarification_customer_jobs.txt',
                # New clarification prompts for vague action requests
                'clarification_export': 'conversational_clarification_export.txt',
                'clarification_data_request': 'conversational_clarification_data_request.txt',
                'clarification_action_default': 'conversational_clarification_action_default.txt'
            },
            'json_query_generation': {
                'system_prompt': 'json_query_generation.txt',
                'content': 'json_query_generation.txt',  # Alias
                'mart': 'json_query_generation_mart.txt'  # Mart-optimized prompt
            },
            'table_definitions': {
                'invoices': 'table_invoices.txt',
                'invoice_items': 'table_invoice_items.txt',
                'suppliers': 'table_suppliers.txt',
                'temporary_item_mappings': 'table_temporary_item_mappings.txt',
                'supplier_item_mappings': 'table_supplier_item_mappings.txt',
                'unmapped_items': 'table_unmapped_items.txt'
            }
        }
        
        logger.info(f"PromptLoader initialized with prompts directory: {self.prompts_dir}")
    
    def _load_text_file(self, filename: str) -> str:
        """Load a text file and return its contents"""
        file_path = self.prompts_dir / filename
        
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            logger.debug(f"Loaded prompt file: {filename}")
            return content.strip()
                
        except Exception as e:
            raise RuntimeError(f"Error loading prompt file {filename}: {e}")
    
    def _load_json_file(self, filename: str) -> Any:
        """Load a JSON file and return its contents"""
        file_path = self.prompts_dir / filename
        
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.debug(f"Loaded JSON file: {filename}")
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in file {filename}: {e}")
        except Exception as e:
            raise RuntimeError(f"Error loading JSON file {filename}: {e}")
    
    def _get_prompt_content(self, prompt_type: str, prompt_key: str) -> str:
        """Get prompt content for a specific type and key"""
        if prompt_type not in self.prompt_file_map:
            raise ValueError(f"Unknown prompt type: {prompt_type}. Available types: {list(self.prompt_file_map.keys())}")
        
        if prompt_key not in self.prompt_file_map[prompt_type]:
            available_keys = list(self.prompt_file_map[prompt_type].keys())
            raise ValueError(f"Prompt key '{prompt_key}' not found in {prompt_type}. Available keys: {available_keys}")
        
        filename = self.prompt_file_map[prompt_type][prompt_key]
        cache_key = f"{prompt_type}:{prompt_key}"
        
        # Check cache first
        if cache_key not in self._prompt_cache:
            if filename.endswith('.json'):
                # Special handling for JSON files (like table_definitions)
                data = self._load_json_file(filename)
                if isinstance(data, dict):
                    # For table_definitions, we need to handle the nested structure
                    self._prompt_cache[cache_key] = json.dumps(data, indent=2)
                else:
                    self._prompt_cache[cache_key] = str(data)
            else:
                # Load text file
                self._prompt_cache[cache_key] = self._load_text_file(filename)
        
        return self._prompt_cache[cache_key]
    
    def get_prompt(self, prompt_type: str, prompt_key: str, **kwargs) -> str:
        """
        Get a specific prompt with optional template variable substitution
        
        Args:
            prompt_type: Type of prompt file (sql_generation, answer_formatting, etc.)
            prompt_key: Key within the prompt type
            **kwargs: Template variables for substitution
            
        Returns:
            The prompt string with variables substituted
            
        Raises:
            ValueError: If prompt_type or prompt_key not found
            KeyError: If required template variables are missing
        """
        try:
            prompt_template = self._get_prompt_content(prompt_type, prompt_key)
            
            # Handle template substitution
            if kwargs:
                try:
                    return prompt_template.format(**kwargs)
                except KeyError as e:
                    raise KeyError(f"Missing template variable {e} for prompt {prompt_type}.{prompt_key}")
            else:
                return prompt_template
                
        except Exception as e:
            logger.error(f"Error getting prompt {prompt_type}.{prompt_key}: {e}")
            raise
    
    def get_table_info(self) -> Dict[str, str]:
        """Get enhanced table information for database queries"""
        try:
            # Load all table definition files
            table_info = {}
            
            if 'table_definitions' not in self.prompt_file_map:
                logger.error("table_definitions not found in prompt_file_map")
                return {}
            
            for table_name, filename in self.prompt_file_map['table_definitions'].items():
                try:
                    content = self._load_text_file(filename)
                    table_info[table_name] = content
                    logger.debug(f"Loaded table definition for: {table_name}")
                except Exception as e:
                    logger.warning(f"Failed to load table definition for {table_name}: {e}")
                    continue
            
            logger.info(f"Loaded {len(table_info)} table definitions")
            return table_info
            
        except Exception as e:
            logger.error(f"Error loading table info: {e}")
            # Return empty dict as fallback
            return {}
    
    def get_conversational_response(self, response_type: str) -> str:
        """Get a conversational response"""
        try:
            return self.get_prompt('conversational_responses', response_type)
        except Exception as e:
            logger.error(f"Error getting conversational response {response_type}: {e}")
            # Return a generic fallback
            return f"I'm sorry, I couldn't load the {response_type} response. Please try again."
    
    def get_sql_generation_prompt(self) -> str:
        """Get the SQL generation prompt template"""
        try:
            return self.get_prompt('sql_generation', 'content')
        except Exception as e:
            logger.error(f"Error loading SQL generation prompt: {e}")
            raise
    
    def get_answer_formatting_prompt(self, version: str = 'standard') -> str:
        """
        Get answer formatting prompt
        
        Args:
            version: 'standard' or 'debug' version of the prompt
        """
        try:
            return self.get_prompt('answer_formatting', version)
        except Exception as e:
            logger.error(f"Error loading answer formatting prompt ({version}): {e}")
            raise
    
    def get_json_query_generation_prompt(self) -> str:
        """Get the JSON query generation prompt template (legacy raw tables)"""
        try:
            return self.get_prompt('json_query_generation', 'content')
        except Exception as e:
            logger.error(f"Error loading JSON query generation prompt: {e}")
            raise
    
    def get_json_query_generation_prompt_mart(self) -> str:
        """
        Get the mart-optimized JSON query generation prompt template.
        
        This prompt is designed for querying pre-cleaned dbt mart tables:
        - analytics.mart__invoice_items
        - analytics.mart__price_increases
        - analytics.mart__address_sheet_aggregates
        
        Key differences from raw table prompt:
        - No relationship paths needed (flat structure)
        - Numeric fields already cast (amount, cost, qty are Float)
        - Normalized columns available for fuzzy search
        - Data already filtered for active records
        """
        try:
            return self.get_prompt('json_query_generation', 'mart')
        except Exception as e:
            logger.error(f"Error loading mart JSON query generation prompt: {e}")
            raise
    
    def clear_cache(self):
        """Clear the prompt cache to force reloading from files"""
        self._prompt_cache.clear()
        logger.info("Prompt cache cleared")
    
    def reload_prompts(self):
        """Reload all prompts from files"""
        self.clear_cache()
        logger.info("All prompts reloaded from files")
    
    def get_available_prompts(self) -> Dict[str, list]:
        """Get a list of all available prompts by type"""
        result = {}
        for prompt_type, keys in self.prompt_file_map.items():
            result[prompt_type] = list(keys.keys())
        return result


# Global prompt loader instance
_prompt_loader = None


def get_prompt_loader() -> PromptLoader:
    """Get or create PromptLoader instance (singleton pattern)"""
    global _prompt_loader
    if _prompt_loader is None:
        _prompt_loader = PromptLoader()
    return _prompt_loader
