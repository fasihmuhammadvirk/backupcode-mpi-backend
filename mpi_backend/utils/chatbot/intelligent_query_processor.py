"""
Intelligent Query Processor for Natural Language Understanding
Handles date parsing, synonym expansion, entity extraction, and query enhancement
"""

import logging
import re
import json
from typing import Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)


class DateParser:
    """Parse natural language date expressions into SQL-compatible date ranges"""
    
    def __init__(self, semantic_config: Dict[str, Any]):
        self.date_patterns = semantic_config.get('date_patterns', {})
        self.month_names = self.date_patterns.get('month_names', {})
        self.quarter_mapping = self.date_patterns.get('quarter_mapping', {})
    
    def parse(self, text: str) -> Dict[str, Any]:
        """
        Parse date expressions from text
        
        Returns:
            Dict with 'found', 'start_date', 'end_date', 'original_text'
        """
        text_lower = text.lower()
        today = datetime.now()
        
        # Check for relative dates
        relative_dates = {
            r'\btoday\b': (today.date(), today.date()),
            r'\byesterday\b': (
                (today - timedelta(days=1)).date(),
                (today - timedelta(days=1)).date()
            ),
            r'\blast week\b': (
                (today - timedelta(weeks=1)).date(),
                today.date()
            ),
            r'\bthis week\b': (
                (today - timedelta(days=today.weekday())).date(),
                today.date()
            ),
            r'\blast month\b': (
                (today - relativedelta(months=1)).replace(day=1).date(),
                (today.replace(day=1) - timedelta(days=1)).date()
            ),
            r'\bthis month\b': (
                today.replace(day=1).date(),
                today.date()
            ),
            r'\blast year\b': (
                today.replace(year=today.year - 1, month=1, day=1).date(),
                today.replace(year=today.year - 1, month=12, day=31).date()
            ),
            r'\bthis year\b': (
                today.replace(month=1, day=1).date(),
                today.date()
            )
        }
        
        for pattern, (start, end) in relative_dates.items():
            match = re.search(pattern, text_lower)
            if match:
                return {
                    'found': True,
                    'start_date': start,
                    'end_date': end,
                    'original_text': match.group(),
                    'type': 'relative'
                }
        
        # Check for month names (e.g., "July", "July 2024") and match only if self.month_names is not empty
        month_pattern = r'\b(' + '|'.join(self.month_names.keys()) + r')(?:\s+(\d{4}))?\b' if self.month_names else None
        month_match = month_pattern and re.search(month_pattern, text_lower)
        if month_match:
            month_name = month_match.group(1)
            year = int(month_match.group(2)) if month_match.group(2) else today.year
            month_num = self.month_names[month_name]
            
            # Calculate first and last day of month
            start_date = datetime(year, month_num, 1).date()
            if month_num == 12:
                end_date = datetime(year, 12, 31).date()
            else:
                end_date = (datetime(year, month_num + 1, 1) - timedelta(days=1)).date()
            
            return {
                'found': True,
                'start_date': start_date,
                'end_date': end_date,
                'original_text': month_match.group(),
                'type': 'month'
            }
        
        # Check for quarters (e.g., "Q1 2024", "Q1")
        quarter_pattern = r'\b(Q[1-4])(?:\s+(\d{4}))?\b'
        quarter_match = re.search(quarter_pattern, text, re.IGNORECASE)
        if quarter_match:
            quarter = quarter_match.group(1).upper()
            year = int(quarter_match.group(2)) if quarter_match.group(2) else today.year
            months = self.quarter_mapping[quarter]
            
            start_date = datetime(year, months[0], 1).date()
            end_month = months[-1]
            if end_month == 12:
                end_date = datetime(year, 12, 31).date()
            else:
                end_date = (datetime(year, end_month + 1, 1) - timedelta(days=1)).date()
            
            return {
                'found': True,
                'start_date': start_date,
                'end_date': end_date,
                'original_text': quarter_match.group(),
                'type': 'quarter'
            }
        
        # Check for date ranges (e.g., "from 2024-01-01 to 2024-12-31")
        date_range_pattern = r'\b(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\b'
        range_match = re.search(date_range_pattern, text)
        if range_match:
            try:
                start_date = datetime.strptime(range_match.group(1), '%Y-%m-%d').date()
                end_date = datetime.strptime(range_match.group(2), '%Y-%m-%d').date()
                return {
                    'found': True,
                    'start_date': start_date,
                    'end_date': end_date,
                    'original_text': range_match.group(),
                    'type': 'explicit_range'
                }
            except ValueError:
                pass
        
        # Check for single dates (e.g., "2024-07-15")
        single_date_pattern = r'\b(\d{4}-\d{2}-\d{2})\b'
        single_match = re.search(single_date_pattern, text)
        if single_match:
            try:
                date = datetime.strptime(single_match.group(1), '%Y-%m-%d').date()
                return {
                    'found': True,
                    'start_date': date,
                    'end_date': date,
                    'original_text': single_match.group(),
                    'type': 'single_date'
                }
            except ValueError:
                pass
        
        return {'found': False}


class SynonymExpander:
    """Expand business terms with their synonyms"""
    
    def __init__(self, semantic_config: Dict[str, Any]):
        self.synonyms = semantic_config.get('synonyms', {})
        self.abbreviations = semantic_config.get('abbreviations', {})
    
    def expand(self, text: str) -> Dict[str, Any]:
        """
        Expand synonyms and abbreviations in text
        
        Returns:
            Dict with 'expanded_text', 'replacements', 'abbreviations_expanded'
        """
        expanded_text = text
        replacements = []
        abbreviations_expanded = []
        
        # Expand abbreviations first
        for abbr, full_form in self.abbreviations.items():
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(abbr) + r'\b'
            if re.search(pattern, expanded_text, re.IGNORECASE):
                expanded_text = re.sub(pattern, full_form, expanded_text, flags=re.IGNORECASE)
                abbreviations_expanded.append({
                    'abbreviation': abbr,
                    'expanded_to': full_form
                })
        
        # Find and note synonyms (don't replace, just inform the LLM)
        for term, synonyms in self.synonyms.items():
            for synonym in synonyms:
                # allow suffex to words like: product -> products, part -> parts
                pattern = r'\b' + re.escape(synonym) + r'(?:es|s)?\b'
                if re.search(pattern, text, re.IGNORECASE):
                    replacements.append({
                        'synonym': synonym,
                        'canonical_term': term,
                        'all_synonyms': [term] + synonyms
                    })
        
        return {
            'expanded_text': expanded_text,
            'replacements': replacements,
            'abbreviations_expanded': abbreviations_expanded
        }


class EntityExtractor:
    """Extract key entities from queries"""
    
    def __init__(self, semantic_config: Dict[str, Any]):
        self.domain_terms = semantic_config.get('domain_terms', {})
        self.multi_table_queries = semantic_config.get('multi_table_queries', {})
    
    def extract(self, text: str) -> Dict[str, Any]:
        """
        Extract entities from text
        
        Returns:
            Dict with 'supplier_mentions', 'item_mentions', 'reference_numbers', etc.
        """
        entities = {
            'supplier_mentions': [],
            'item_mentions': [],
            'reference_numbers': [],
            'po_numbers': [],
            'customer_jobs': [],
            'plumbing_items': [],
            'multi_table_query': None
        }
        
        text_lower = text.lower()
        
        # Check for multi-table queries (e.g., org item queries)
        for query_type, config in self.multi_table_queries.items():
            # Check if any related terms are mentioned
            # Replace underscores with spaces to match natural language (e.g., 'org_item' -> 'org item')
            query_type_natural = query_type.replace('_', ' ')
            if (
                query_type in text_lower
                or query_type_natural in text_lower
                or 'original item' in text_lower
                or 'supplier item' in text_lower
            ):
                entities['multi_table_query'] = {
                    'type': query_type,
                    'tables': config['tables'],
                    'columns': config['columns'],
                    'description': config['description']
                }
        
        # Extract plumbing-related items
        plumbing_items = self.domain_terms.get('plumbing_items', [])
        for item in plumbing_items:
            if re.search(r'\b' + re.escape(item) + r'\b', text_lower):
                entities['plumbing_items'].append(item)
        
        # Extract reference numbers (pattern: alphanumeric, possibly with dashes)
        ref_pattern = r'\b([A-Z0-9]+-[A-Z0-9]+|[A-Z]{2,}\d+|\d+[A-Z]{2,})\b'
        ref_matches = re.findall(ref_pattern, text, re.IGNORECASE)
        entities['reference_numbers'] = ref_matches
        
        # Extract potential supplier names (capitalized words, possibly with "Supply", "Plumbing", etc.)
        supplier_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(?:Supply|Supplies|Plumbing|Co|Company|Inc|LLC))?)\b'
        supplier_matches = re.findall(supplier_pattern, text)
        entities['supplier_mentions'] = supplier_matches
        
        # Extract PO numbers (pattern: "PO" followed by digits or alphanumeric)
        po_pattern = r'\bPO[-\s]?([A-Z0-9]+)\b'
        po_matches = re.findall(po_pattern, text, re.IGNORECASE)
        entities['po_numbers'] = po_matches
        
        return entities


class QueryEnhancer:
    """Enhance queries with intelligent context and suggestions"""
    
    def __init__(self):
        # Load semantic configuration
        current_dir = Path(__file__).parent
        semantic_file = current_dir / 'prompts' / 'semantic_mappings.json'
        
        with open(semantic_file, 'r', encoding='utf-8') as f:
            self.semantic_config = json.load(f)
        
        self.date_parser = DateParser(self.semantic_config)
        self.synonym_expander = SynonymExpander(self.semantic_config)
        self.entity_extractor = EntityExtractor(self.semantic_config)
    
    def enhance(self, question: str) -> Dict[str, Any]:
        """
        Enhance a user question with intelligent processing
        
        Args:
            question: User's natural language question
            
        Returns:
            Dict with enhanced question, metadata, and suggestions
        """
        logger.info(f"Enhancing question: {question[:100]}...")
        
        # Parse dates
        date_info = self.date_parser.parse(question)
        
        # Expand synonyms and abbreviations
        synonym_info = self.synonym_expander.expand(question)
        
        # Extract entities
        entities = self.entity_extractor.extract(question)
        
        # Build enhanced question with context
        enhanced_question = synonym_info['expanded_text']
        
        # Build context hints for the LLM
        context_hints = []
        
        if date_info['found']:
            context_hints.append(
                f"Date range detected: {date_info['original_text']} "
                f"({date_info['start_date']} to {date_info['end_date']})"
            )
        
        if synonym_info['replacements']:
            synonym_list = ', '.join([
                f"'{r['synonym']}' (means '{r['canonical_term']}')"
                for r in synonym_info['replacements']
            ])
            context_hints.append(f"Synonyms detected: {synonym_list}")
        
        if synonym_info['abbreviations_expanded']:
            abbr_list = ', '.join([
                f"'{a['abbreviation']}' → '{a['expanded_to']}'"
                for a in synonym_info['abbreviations_expanded']
            ])
            context_hints.append(f"Abbreviations expanded: {abbr_list}")
        
        if entities['multi_table_query']:
            mtq = entities['multi_table_query']
            context_hints.append(
                f"Multi-table query required: {mtq['description']}. "
                f"Must query tables: {', '.join(mtq['tables'])}"
            )
        
        if entities['plumbing_items']:
            context_hints.append(
                f"Plumbing items mentioned: {', '.join(entities['plumbing_items'])}"
            )
        
        if entities['supplier_mentions']:
            context_hints.append(
                f"Potential suppliers: {', '.join(entities['supplier_mentions'])}"
            )
        
        # Build fuzzy search suggestions
        fuzzy_config = self.semantic_config.get('fuzzy_search_config', {})
        fuzzy_suggestions = []
        
        # Check if supplier names should use fuzzy search
        if entities['supplier_mentions']:
            fuzzy_suggestions.append(
                "Use PostgreSQL similarity() function for supplier name matching "
                "to handle potential typos"
            )
        
        # Check if item searches should use fuzzy search
        if entities['plumbing_items'] or 'item' in question.lower():
            fuzzy_suggestions.append(
                "Search across multiple columns: item, description, mpi_item, mpi_description"
            )
        
        # Combine everything into enhanced context
        enhancement_notes = "\n".join([
            "INTELLIGENT QUERY ENHANCEMENT:",
            *[f"• {hint}" for hint in context_hints],
            "",
            "FUZZY SEARCH RECOMMENDATIONS:",
            *[f"• {suggestion}" for suggestion in fuzzy_suggestions]
        ]) if context_hints or fuzzy_suggestions else ""
        
        result = {
            'original_question': question,
            'enhanced_question': enhanced_question,
            'enhancement_notes': enhancement_notes,
            'date_info': date_info,
            'synonym_info': synonym_info,
            'entities': entities,
            'fuzzy_config': fuzzy_config,
            'has_enhancements': bool(context_hints or fuzzy_suggestions)
        }
        
        logger.info(f"Enhancement complete. Has enhancements: {result['has_enhancements']}")
        
        return result


# Singleton instance
_query_enhancer = None


def get_query_enhancer() -> QueryEnhancer:
    """Get or create QueryEnhancer instance (singleton pattern)"""
    global _query_enhancer
    if _query_enhancer is None:
        _query_enhancer = QueryEnhancer()
    return _query_enhancer

