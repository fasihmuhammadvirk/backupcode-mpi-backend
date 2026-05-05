"""
Query Pre-Processor for Typo Detection, Normalization, and Context Enhancement
"""

import logging
import re
from typing import Dict, Any, List, Optional
from sqlalchemy import text
from mpi_backend.database import engine

logger = logging.getLogger(__name__)


class TypoDetector:
    """Detect and suggest corrections for potential typos"""
    
    def __init__(self):
        self._supplier_cache = None
        self._popular_items_cache = None
    
    def _load_suppliers(self) -> List[str]:
        """Load supplier names from database for typo detection"""
        if self._supplier_cache is not None:
            return self._supplier_cache
        
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT DISTINCT supplier_name FROM suppliers"))
                self._supplier_cache = [row[0] for row in result.fetchall() if row[0]]
                logger.info(f"Loaded {len(self._supplier_cache)} suppliers for typo detection")
                return self._supplier_cache
        except Exception as e:
            logger.error(f"Failed to load suppliers: {e}")
            return []
    
    def _load_popular_items(self, limit: int = 100) -> List[str]:
        """Load popular item codes for typo detection"""
        if self._popular_items_cache is not None:
            return self._popular_items_cache
        
        try:
            with engine.connect() as conn:
                query = text("""
                    SELECT DISTINCT mpi_item 
                    FROM invoice_items 
                    WHERE mpi_item IS NOT NULL 
                      AND mpi_item != 'No Match' 
                      AND mpi_item != ''
                      AND is_active IS NOT FALSE
                    ORDER BY mpi_item
                    LIMIT :limit
                """)
                result = conn.execute(query, {'limit': limit})
                self._popular_items_cache = [row[0] for row in result.fetchall() if row[0]]
                logger.info(f"Loaded {len(self._popular_items_cache)} popular items")
                return self._popular_items_cache
        except Exception as e:
            logger.error(f"Failed to load popular items: {e}")
            return []
    
    def detect_supplier_typos(self, text: str) -> List[Dict[str, Any]]:
        """
        Detect potential typos in supplier names
        
        Args:
            text: User query text
            
        Returns:
            List of potential corrections
        """
        try:
            from fuzzywuzzy import fuzz
        except ImportError:
            logger.warning("fuzzywuzzy not available for typo detection")
            return []
        
        suppliers = self._load_suppliers()
        if not suppliers:
            return []
        
        corrections = []
        words = text.split()
        
        # Check for potential supplier name fragments
        for i, word in enumerate(words):
            if len(word) < 3:  # Skip very short words
                continue
            
            # Look for similar supplier names
            for supplier in suppliers:
                # Check if word is part of supplier name
                if word.lower() in supplier.lower():
                    continue  # Exact substring, not a typo
                
                # Calculate similarity
                similarity = fuzz.partial_ratio(word.lower(), supplier.lower())
                
                if 60 <= similarity < 100:  # Potential typo range
                    corrections.append({
                        'original': word,
                        'suggestion': supplier,
                        'similarity': similarity,
                        'type': 'supplier'
                    })
        
        # Sort by similarity and take top suggestions
        corrections.sort(key=lambda x: x['similarity'], reverse=True)
        return corrections[:5]  # Top 5 suggestions
    
    def detect_common_typos(self, text: str) -> List[Dict[str, Any]]:
        """
        Detect common typos and misspellings
        
        Args:
            text: User query text
            
        Returns:
            List of corrections
        """
        common_typos = {
            'plumbng': 'plumbing',
            'suppies': 'supplies',
            'invioce': 'invoice',
            'invioces': 'invoices',
            'custoemr': 'customer',
            'itme': 'item',
            'itmes': 'items',
            'supplr': 'supplier',
            'suppiler': 'supplier',
            'quickbok': 'quickbooks',
            'quikbooks': 'quickbooks',
            'exportd': 'exported',
            'pendng': 'pending',
            'processd': 'processed'
        }
        
        corrections = []
        text_lower = text.lower()
        
        for typo, correction in common_typos.items():
            if typo in text_lower:
                corrections.append({
                    'original': typo,
                    'suggestion': correction,
                    'type': 'common_typo',
                    'auto_correct': True
                })
        
        return corrections


class QueryNormalizer:
    """Normalize query text for better processing"""
    
    @staticmethod
    def normalize_item_codes(text: str) -> str:
        """
        Normalize item codes (uppercase, trim)
        
        Args:
            text: Query text
            
        Returns:
            Normalized text
        """
        # Pattern for potential item codes (alphanumeric with dashes/underscores)
        item_code_pattern = r'\b([A-Z0-9]+-[A-Z0-9]+|[A-Z]{2,}\d+|\d+[A-Z]{2,})\b'
        
        def uppercase_code(match):
            return match.group(1).upper()
        
        normalized = re.sub(item_code_pattern, uppercase_code, text, flags=re.IGNORECASE)
        return normalized
    
    @staticmethod
    def normalize_dates(text: str) -> str:
        """
        Normalize date references
        
        Args:
            text: Query text
            
        Returns:
            Normalized text
        """
        # Convert common date formats to standard form
        date_replacements = {
            r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b': r'\3-\1-\2',  # MM/DD/YYYY to YYYY-MM-DD
            r'\b(\d{1,2})-(\d{1,2})-(\d{4})\b': r'\3-\1-\2',  # MM-DD-YYYY to YYYY-MM-DD
        }
        
        normalized = text
        for pattern, replacement in date_replacements.items():
            normalized = re.sub(pattern, replacement, normalized)
        
        return normalized
    
    @staticmethod
    def expand_common_abbreviations(text: str) -> str:
        """
        Expand common abbreviations
        
        Args:
            text: Query text
            
        Returns:
            Expanded text
        """
        # This is now handled by SynonymExpander, but keep for backward compatibility
        abbreviations = {
            r'\bQB\b': 'QuickBooks',
            r'\bPO\b': 'purchase order',
            r'\binv\b': 'invoice',
            r'\bsup\b': 'supplier',
        }
        
        expanded = text
        for pattern, replacement in abbreviations.items():
            expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
        
        return expanded
    
    def normalize(self, text: str) -> str:
        """
        Apply all normalization steps
        
        Args:
            text: Query text
            
        Returns:
            Fully normalized text
        """
        normalized = text
        normalized = self.normalize_item_codes(normalized)
        normalized = self.normalize_dates(normalized)
        # Don't expand abbreviations here - let SynonymExpander handle it
        return normalized


class ContextAdder:
    """Add business context and inferred filters to queries"""
    
    @staticmethod
    def add_context_hints(question: str, entities: Dict[str, Any]) -> List[str]:
        """
        Generate context hints based on extracted entities
        
        Args:
            question: User question
            entities: Extracted entities from EntityExtractor
            
        Returns:
            List of context hints
        """
        hints = []
        
        # Always filter for active items when querying invoice_items
        if any(word in question.lower() for word in ['item', 'items', 'invoice items']):
            hints.append(
                "IMPORTANT: Always add 'WHERE is_active IS NOT FALSE' when querying invoice_items "
                "to exclude deleted items"
            )
        
        # Suggest joining suppliers for invoice queries
        if 'invoice' in question.lower() and 'supplier' not in question.lower():
            hints.append(
                "Consider joining with suppliers table to include supplier_name in results"
            )
        
        # Suggest joining invoice_items for invoice details
        if 'invoice' in question.lower() and all(
            word not in question.lower() for word in ['ref_no', 'reference', 'customer job']
        ):
            hints.append(
                "Consider joining with invoice_items to include ref_no and customer_job "
                "for better invoice identification"
            )
        
        # Multi-table query hint for org items
        if entities.get('multi_table_query'):
            mtq = entities['multi_table_query']
            hints.append(
                f"CRITICAL: This is a multi-table query. Must use UNION to query ALL these tables: "
                f"{', '.join(mtq['tables'])}"
            )
        
        # Date range filtering hint
        if entities.get('date_info') and entities['date_info'].get('found'):
            date_info = entities['date_info']
            hints.append(
                f"Apply date range filter: date >= '{date_info['start_date']}' "
                f"AND date <= '{date_info['end_date']}'"
            )
        
        return hints
    
    @staticmethod
    def infer_business_rules(question: str) -> List[str]:
        """
        Infer business rules that should be applied
        
        Args:
            question: User question
            
        Returns:
            List of business rule hints
        """
        rules = []
        
        question_lower = question.lower()
        
        # Export-related queries
        if any(word in question_lower for word in ['export', 'quickbooks', 'qb']):
            rules.append(
                "For export queries, use export_status column and is_exported column appropriately"
            )
        
        # Mapping-related queries
        if any(word in question_lower for word in ['mapping', 'mapped', 'unmapped', 'no match']):
            rules.append(
                "For mapping queries, exclude temporary UIDI codes: "
                "WHERE mpi_code NOT LIKE 'UIDI%'"
            )
        
        # Total/sum queries
        if any(word in question_lower for word in ['total', 'sum', 'aggregate']):
            rules.append(
                "For totals, remember that amount column is VARCHAR with commas. "
                "Use: CAST(REPLACE(amount, ',', '') AS DECIMAL)"
            )
        
        # Count queries
        if 'count' in question_lower or 'how many' in question_lower:
            rules.append(
                "For count queries, use COUNT(DISTINCT ...) to avoid duplicates from joins"
            )
        
        return rules


class QueryPreProcessor:
    """Main query pre-processor coordinating all enhancement steps"""
    
    def __init__(self):
        self.typo_detector = TypoDetector()
        self.query_normalizer = QueryNormalizer()
        self.context_adder = ContextAdder()
    
    def preprocess(
        self,
        question: str,
        enhancement_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Pre-process a query with all enhancements
        
        Args:
            question: User question
            enhancement_data: Data from QueryEnhancer (optional)
            
        Returns:
            Dict with preprocessing results
        """
        logger.info(f"Pre-processing query: {question[:100]}...")
        
        # Detect typos
        supplier_typos = self.typo_detector.detect_supplier_typos(question)
        common_typos = self.typo_detector.detect_common_typos(question)
        
        # Auto-correct common typos
        corrected_question = question
        for typo_info in common_typos:
            if typo_info.get('auto_correct'):
                corrected_question = corrected_question.replace(
                    typo_info['original'],
                    typo_info['suggestion']
                )
        
        # Normalize query
        normalized_question = self.query_normalizer.normalize(corrected_question)
        
        # Add context hints
        entities = enhancement_data.get('entities', {}) if enhancement_data else {}
        context_hints = self.context_adder.add_context_hints(normalized_question, entities)
        business_rules = self.context_adder.infer_business_rules(normalized_question)
        
        result = {
            'original_question': question,
            'normalized_question': normalized_question,
            'typos_detected': {
                'supplier_typos': supplier_typos,
                'common_typos': common_typos
            },
            'context_hints': context_hints,
            'business_rules': business_rules,
            'has_corrections': len(supplier_typos) > 0 or len(common_typos) > 0,
            'has_context': len(context_hints) > 0 or len(business_rules) > 0
        }
        
        logger.info(
            f"Pre-processing complete. Corrections: {result['has_corrections']}, "
            f"Context: {result['has_context']}"
        )
        
        return result


# Singleton instance
_query_preprocessor = None


def get_query_preprocessor() -> QueryPreProcessor:
    """Get or create QueryPreProcessor instance (singleton pattern)"""
    global _query_preprocessor
    if _query_preprocessor is None:
        _query_preprocessor = QueryPreProcessor()
    return _query_preprocessor

