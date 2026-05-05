"""
Fuzzy Search Builder for PostgreSQL
Generates intelligent fuzzy search SQL using pg_trgm and similarity functions
"""

import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SimilarityMatcher:
    """Generate PostgreSQL similarity matching SQL"""
    
    @staticmethod
    def build_similarity_condition(
        column: str,
        search_term: str,
        threshold: float = 0.3,
        table_alias: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Build a similarity condition using PostgreSQL pg_trgm
        
        Args:
            column: Column name to search
            search_term: Term to match against
            threshold: Similarity threshold (0.0 to 1.0)
            table_alias: Optional table alias
            
        Returns:
            Tuple of (WHERE condition, ORDER BY clause)
        """
        col_ref = f"{table_alias}.{column}" if table_alias else column
        
        where_clause = f"similarity({col_ref}, :search_term) > {threshold}"
        order_clause = f"similarity({col_ref}, :search_term) DESC"
        
        return where_clause, order_clause
    
    @staticmethod
    def build_word_similarity_condition(
        column: str,
        search_term: str,
        threshold: float = 0.3,
        table_alias: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Build a word similarity condition (better for substring matching)
        
        Args:
            column: Column name to search
            search_term: Term to match against
            threshold: Similarity threshold (0.0 to 1.0)
            table_alias: Optional table alias
            
        Returns:
            Tuple of (WHERE condition, ORDER BY clause)
        """
        col_ref = f"{table_alias}.{column}" if table_alias else column
        
        where_clause = f"word_similarity(:search_term, {col_ref}) > {threshold}"
        order_clause = f"word_similarity(:search_term, {col_ref}) DESC"
        
        return where_clause, order_clause
    
    @staticmethod
    def build_trigram_operator_condition(
        column: str,
        search_term: str,
        table_alias: Optional[str] = None
    ) -> str:
        """
        Build a condition using the % trigram operator (fast with GIN indexes)
        
        Args:
            column: Column name to search
            search_term: Term to match against
            table_alias: Optional table alias
            
        Returns:
            WHERE condition string
        """
        col_ref = f"{table_alias}.{column}" if table_alias else column
        return f"{col_ref} % :search_term"


class FuzzySearchBuilder:
    """Build fuzzy search SQL queries with intelligent fallback strategies"""
    
    def __init__(self, similarity_threshold: float = 0.3):
        self.similarity_threshold = similarity_threshold
        self.high_confidence_threshold = 0.7
        self.similarity_matcher = SimilarityMatcher()
    
    def build_fuzzy_supplier_search(
        self,
        search_term: str,
        exact_first: bool = True
    ) -> Dict[str, Any]:
        """
        Build fuzzy search SQL for suppliers
        
        Args:
            search_term: Supplier name to search
            exact_first: Whether to try exact match first
            
        Returns:
            Dict with SQL components and strategy info
        """
        strategies = []
        
        # Strategy 1: Exact match (case-insensitive)
        if exact_first:
            strategies.append({
                'name': 'exact',
                'where': "LOWER(supplier_name) = LOWER(:search_term)",
                'order': "supplier_name",
                'description': 'Exact match (case-insensitive)'
            })
        
        # Strategy 2: ILIKE pattern match
        strategies.append({
            'name': 'ilike',
            'where': "supplier_name ILIKE :search_pattern",
            'order': "LENGTH(supplier_name), supplier_name",
            'params': {'search_pattern': f'%{search_term}%'},
            'description': 'Case-insensitive pattern match'
        })
        
        # Strategy 3: Trigram similarity
        where_clause, order_clause = self.similarity_matcher.build_similarity_condition(
            'supplier_name',
            search_term,
            self.similarity_threshold
        )
        strategies.append({
            'name': 'similarity',
            'where': where_clause,
            'order': order_clause,
            'description': f'Trigram similarity (threshold: {self.similarity_threshold})'
        })
        
        return {
            'strategies': strategies,
            'search_term': search_term,
            'table': 'suppliers'
        }
    
    def build_fuzzy_item_search(
        self,
        search_term: str,
        columns: Optional[List[str]] = None,
        exact_first: bool = True
    ) -> Dict[str, Any]:
        """
        Build fuzzy search SQL for items across multiple columns
        
        Args:
            search_term: Item to search
            columns: Columns to search (default: item, description, mpi_item, mpi_description)
            exact_first: Whether to try exact match first
            
        Returns:
            Dict with SQL components and strategy info
        """
        if columns is None:
            columns = ['item', 'description', 'mpi_item', 'mpi_description']
        
        strategies = []
        
        # Strategy 1: Exact match on any column
        if exact_first:
            exact_conditions = [f"LOWER({col}) = LOWER(:search_term)" for col in columns]
            strategies.append({
                'name': 'exact_multi',
                'where': f"({' OR '.join(exact_conditions)})",
                'order': "date DESC, ref_no",
                'description': 'Exact match across multiple columns'
            })
        
        # Strategy 2: ILIKE on any column
        ilike_conditions = [f"{col} ILIKE :search_pattern" for col in columns]
        strategies.append({
            'name': 'ilike_multi',
            'where': f"({' OR '.join(ilike_conditions)})",
            'order': "date DESC, ref_no",
            'params': {'search_pattern': f'%{search_term}%'},
            'description': 'Pattern match across multiple columns'
        })
        
        # Strategy 3: Trigram similarity on primary columns
        similarity_conditions = []
        for col in columns[:2]:  # Use first 2 columns for similarity
            where_clause, _ = self.similarity_matcher.build_similarity_condition(
                col,
                search_term,
                self.similarity_threshold
            )
            similarity_conditions.append(where_clause)
        
        strategies.append({
            'name': 'similarity_multi',
            'where': f"({' OR '.join(similarity_conditions)})",
            'order': f"similarity({columns[0]}, :search_term) DESC",
            'description': f'Trigram similarity on {", ".join(columns[:2])}'
        })
        
        return {
            'strategies': strategies,
            'search_term': search_term,
            'columns': columns,
            'table': 'invoice_items'
        }
    
    def build_fuzzy_customer_job_search(
        self,
        search_term: str,
        exact_first: bool = True
    ) -> Dict[str, Any]:
        """
        Build fuzzy search SQL for customer jobs
        
        Args:
            search_term: Customer job to search
            exact_first: Whether to try exact match first
            
        Returns:
            Dict with SQL components and strategy info
        """
        strategies = []
        
        # Strategy 1: Exact match
        if exact_first:
            strategies.append({
                'name': 'exact',
                'where': "LOWER(customer_job) = LOWER(:search_term)",
                'order': "date DESC",
                'description': 'Exact match (case-insensitive)'
            })
        
        # Strategy 2: ILIKE pattern
        strategies.append({
            'name': 'ilike',
            'where': "customer_job ILIKE :search_pattern",
            'order': "LENGTH(customer_job), date DESC",
            'params': {'search_pattern': f'%{search_term}%'},
            'description': 'Case-insensitive pattern match'
        })
        
        # Strategy 3: Trigram similarity
        where_clause, order_clause = self.similarity_matcher.build_similarity_condition(
            'customer_job',
            search_term,
            self.similarity_threshold
        )
        strategies.append({
            'name': 'similarity',
            'where': where_clause,
            'order': order_clause,
            'description': f'Trigram similarity (threshold: {self.similarity_threshold})'
        })
        
        return {
            'strategies': strategies,
            'search_term': search_term,
            'table': 'invoice_items'
        }
    
    def generate_fuzzy_search_hints(
        self,
        entity_type: str,
        search_term: str
    ) -> str:
        """
        Generate hints for the LLM about using fuzzy search
        
        Args:
            entity_type: Type of entity (supplier, item, customer_job)
            search_term: Term being searched
            
        Returns:
            Hint text for the LLM
        """
        hints = []
        
        if entity_type == 'supplier':
            hints.append(
                f"For supplier name '{search_term}', use fuzzy search strategy:\n"
                f"1. Try exact match: WHERE LOWER(supplier_name) = LOWER('{search_term}')\n"
                f"2. If no results, use ILIKE: WHERE supplier_name ILIKE '%{search_term}%'\n"
                f"3. If still no results, use similarity: WHERE similarity(supplier_name, '{search_term}') > {self.similarity_threshold}\n"
                f"   ORDER BY similarity(supplier_name, '{search_term}') DESC LIMIT 10"
            )
        
        elif entity_type == 'item':
            hints.append(
                f"For item '{search_term}', search across multiple columns:\n"
                f"WHERE item ILIKE '%{search_term}%' \n"
                f"   OR description ILIKE '%{search_term}%' \n"
                f"   OR mpi_item ILIKE '%{search_term}%' \n"
                f"   OR mpi_description ILIKE '%{search_term}%'"
            )
        
        elif entity_type == 'customer_job':
            hints.append(
                f"For customer job '{search_term}', use fuzzy search:\n"
                f"WHERE customer_job ILIKE '%{search_term}%'\n"
                f"   OR similarity(customer_job, '{search_term}') > {self.similarity_threshold}"
            )
        
        return '\n'.join(hints)


class FallbackStrategy:
    """Manages intelligent fallback when searches return no results"""
    
    def __init__(self):
        self.fuzzy_builder = FuzzySearchBuilder()
    
    def generate_fallback_suggestions(
        self,
        original_query: str,
        entity_type: str,
        search_term: str
    ) -> Dict[str, Any]:
        """
        Generate fallback suggestions when a query returns no results
        
        Args:
            original_query: The original SQL query that returned no results
            entity_type: Type of entity being searched
            search_term: Original search term
            
        Returns:
            Dict with fallback suggestions and alternative queries
        """
        suggestions = {
            'message': f"No exact matches found for '{search_term}'.",
            'suggestions': [],
            'alternative_queries': []
        }
        
        # Suggest fuzzy search
        if entity_type == 'supplier':
            search_config = self.fuzzy_builder.build_fuzzy_supplier_search(
                search_term,
                exact_first=False
            )
            suggestions['suggestions'].append(
                "Try fuzzy search for similar supplier names"
            )
            suggestions['alternative_queries'] = search_config['strategies']
        
        elif entity_type in ['item', 'product', 'part']:
            search_config = self.fuzzy_builder.build_fuzzy_item_search(
                search_term,
                exact_first=False
            )
            suggestions['suggestions'].append(
                "Try searching across item, description, and MPI fields"
            )
            suggestions['alternative_queries'] = search_config['strategies']
        
        elif entity_type == 'customer_job':
            search_config = self.fuzzy_builder.build_fuzzy_customer_job_search(
                search_term,
                exact_first=False
            )
            suggestions['suggestions'].append(
                "Try partial matching for customer job names"
            )
            suggestions['alternative_queries'] = search_config['strategies']
        
        # General suggestions
        suggestions['suggestions'].extend([
            "Check spelling of the search term",
            "Try using partial names or codes",
            "Use broader search criteria"
        ])
        
        return suggestions


# Singleton instances
_fuzzy_search_builder = None
_fallback_strategy = None


def get_fuzzy_search_builder(similarity_threshold: float = 0.3) -> FuzzySearchBuilder:
    """Get or create FuzzySearchBuilder instance"""
    global _fuzzy_search_builder
    if _fuzzy_search_builder is None:
        _fuzzy_search_builder = FuzzySearchBuilder(similarity_threshold)
    return _fuzzy_search_builder


def get_fallback_strategy() -> FallbackStrategy:
    """Get or create FallbackStrategy instance"""
    global _fallback_strategy
    if _fallback_strategy is None:
        _fallback_strategy = FallbackStrategy()
    return _fallback_strategy

