"""
Semantic Understanding Layer for Business Term Mapping and Relationship Navigation
"""

import logging
import json
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class SemanticMapper:
    """Map synonyms and related business terms"""
    
    def __init__(self, semantic_config: Dict[str, Any]):
        self.synonyms = semantic_config.get('synonyms', {})
        self.abbreviations = semantic_config.get('abbreviations', {})
        self.domain_terms = semantic_config.get('domain_terms', {})
    
    def find_canonical_term(self, term: str) -> Optional[str]:
        """
        Find the canonical database term for a given synonym
        
        Args:
            term: User's term (might be synonym)
            
        Returns:
            Canonical term or None if not found
        """
        term_lower = term.lower()
        
        # Check if term is already canonical
        if term_lower in self.synonyms:
            return term_lower
        
        # Search through synonyms
        for canonical, synonym_list in self.synonyms.items():
            if term_lower in [s.lower() for s in synonym_list]:
                return canonical
        
        return None
    
    def get_all_terms(self, canonical_term: str) -> List[str]:
        """
        Get all synonyms for a canonical term
        
        Args:
            canonical_term: The canonical database term
            
        Returns:
            List of all terms including canonical
        """
        canonical_lower = canonical_term.lower()
        
        if canonical_lower in self.synonyms:
            return [canonical_lower] + self.synonyms[canonical_lower]
        
        return [canonical_lower]
    
    def expand_abbreviation(self, abbr: str) -> Optional[str]:
        """
        Expand an abbreviation to its full form
        
        Args:
            abbr: Abbreviation
            
        Returns:
            Full form or None
        """
        return self.abbreviations.get(abbr)
    
    def is_domain_term(self, term: str, domain: str) -> bool:
        """
        Check if a term belongs to a specific domain
        
        Args:
            term: Term to check
            domain: Domain name (e.g., 'plumbing_items', 'common_suppliers')
            
        Returns:
            True if term is in domain
        """
        if domain not in self.domain_terms:
            return False
        
        term_lower = term.lower()
        domain_list = self.domain_terms[domain]
        
        if isinstance(domain_list, list):
            return term_lower in [t.lower() for t in domain_list]
        elif isinstance(domain_list, dict):
            # Check all values in nested dict
            for values in domain_list.values():
                if isinstance(values, list) and term_lower in [v.lower() for v in values]:
                    return True
        
        return False


class RelationshipNavigator:
    """Understand and navigate database table relationships"""
    
    # Define database schema relationships
    RELATIONSHIPS = {
        'invoices': {
            'belongs_to': {
                'suppliers': {
                    'foreign_key': 'supplier_id',
                    'primary_key': 'id',
                    'description': 'Each invoice belongs to one supplier'
                }
            },
            'has_many': {
                'invoice_items': {
                    'foreign_key': 'invoice_id',
                    'primary_key': 'id',
                    'description': 'Each invoice has many line items'
                }
            }
        },
        'invoice_items': {
            'belongs_to': {
                'invoices': {
                    'foreign_key': 'invoice_id',
                    'primary_key': 'id',
                    'description': 'Each item belongs to one invoice'
                }
            }
        },
        'suppliers': {
            'has_many': {
                'invoices': {
                    'foreign_key': 'supplier_id',
                    'primary_key': 'id',
                    'description': 'Each supplier can have many invoices'
                },
                'supplier_item_mappings': {
                    'foreign_key': 'supplier_id',
                    'primary_key': 'id',
                    'description': 'Each supplier has many item mappings'
                }
            }
        },
        'supplier_item_mappings': {
            'belongs_to': {
                'suppliers': {
                    'foreign_key': 'supplier_id',
                    'primary_key': 'id',
                    'description': 'Each mapping belongs to one supplier'
                }
            }
        }
    }
    
    # Key columns per table
    TABLE_KEY_COLUMNS = {
        'invoices': {
            'primary_key': 'id',
            'business_key': ['date', 'supplier_id'],
            'display_columns': ['date', 'status', 'is_exported'],
            'searchable': ['status', 'is_exported']
        },
        'invoice_items': {
            'primary_key': 'id',
            'business_key': ['ref_no', 'customer_job'],
            'display_columns': [
                'ref_no', 'customer_job', 'item', 'description', 
                'qty', 'cost', 'amount', 'date', 'vendor'
            ],
            'searchable': [
                'ref_no', 'customer_job', 'item', 'description',
                'vendor', 'mpi_item', 'mpi_description'
            ]
        },
        'suppliers': {
            'primary_key': 'id',
            'business_key': ['supplier_name'],
            'display_columns': ['supplier_name'],
            'searchable': ['supplier_name']
        },
        'temporary_item_mappings': {
            'primary_key': 'id',
            'business_key': ['original_item', 'sheet_name'],
            'display_columns': ['original_item', 'original_description', 'sheet_name'],
            'searchable': ['original_item', 'original_description']
        },
        'supplier_item_mappings': {
            'primary_key': 'id',
            'business_key': ['supplier_item_ids', 'mpi_code'],
            'display_columns': [
                'supplier_item_ids', 'mpi_code', 'description', 'google_sheet_name'
            ],
            'searchable': ['supplier_item_ids', 'mpi_code', 'description']
        },
        'unmapped_items': {
            'primary_key': 'id',
            'business_key': ['supplier_item_ids'],
            'display_columns': ['supplier_item_ids', 'mpi_code', 'description'],
            'searchable': ['supplier_item_ids', 'description']
        }
    }
    
    def get_join_path(
        self,
        from_table: str,
        to_table: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the join path between two tables
        
        Args:
            from_table: Starting table
            to_table: Destination table
            
        Returns:
            Join information or None
        """
        # Direct relationship
        if from_table in self.RELATIONSHIPS:
            # Check belongs_to
            if 'belongs_to' in self.RELATIONSHIPS[from_table]:
                if to_table in self.RELATIONSHIPS[from_table]['belongs_to']:
                    rel = self.RELATIONSHIPS[from_table]['belongs_to'][to_table]
                    return {
                        'type': 'belongs_to',
                        'join_sql': f"{from_table}.{rel['foreign_key']} = {to_table}.{rel['primary_key']}",
                        'description': rel['description']
                    }
            
            # Check has_many
            if 'has_many' in self.RELATIONSHIPS[from_table]:
                if to_table in self.RELATIONSHIPS[from_table]['has_many']:
                    rel = self.RELATIONSHIPS[from_table]['has_many'][to_table]
                    return {
                        'type': 'has_many',
                        'join_sql': f"{from_table}.{rel['primary_key']} = {to_table}.{rel['foreign_key']}",
                        'description': rel['description']
                    }
        
        # Indirect relationship (invoice_items to suppliers through invoices)
        if from_table == 'invoice_items' and to_table == 'suppliers':
            return {
                'type': 'indirect',
                'join_sql': (
                    f"invoice_items.invoice_id = invoices.id "
                    f"AND invoices.supplier_id = suppliers.id"
                ),
                'description': 'Invoice items to suppliers through invoices',
                'intermediate_tables': ['invoices']
            }
        
        return None
    
    def get_searchable_columns(self, table: str) -> List[str]:
        """Get searchable columns for a table"""
        return self.TABLE_KEY_COLUMNS.get(table, {}).get('searchable', [])
    
    def get_display_columns(self, table: str) -> List[str]:
        """Get recommended display columns for a table"""
        return self.TABLE_KEY_COLUMNS.get(table, {}).get('display_columns', [])
    
    def get_business_key(self, table: str) -> List[str]:
        """Get business key columns (for user identification)"""
        return self.TABLE_KEY_COLUMNS.get(table, {}).get('business_key', [])


class DomainKnowledge:
    """Plumbing supply domain-specific knowledge"""
    
    # Common plumbing supply item patterns
    ITEM_PATTERNS = {
        'pipe_sizes': r'\b(\d+(?:\.\d+)?)\s*(?:inch|in|")\b',
        'material_types': ['PVC', 'CPVC', 'copper', 'brass', 'steel', 'galvanized', 'iron'],
        'connection_types': ['threaded', 'solvent', 'compression', 'push-fit', 'crimp'],
        'common_fittings': ['elbow', 'tee', 'coupling', 'adapter', 'reducer', 'cap', 'plug']
    }
    
    # Business workflow understanding
    WORKFLOW_STAGES = {
        'invoice_processing': [
            'uploaded',
            'extracted',
            'processed',
            'mapped',
            'ready_for_export',
            'exported'
        ],
        'item_mapping': [
            'temporary',
            'pending_approval',
            'permanent',
            'unmapped'
        ],
        'export_status': [
            'pending',
            'in_progress',
            'exported',
            'failed'
        ]
    }
    
    @classmethod
    def identify_item_characteristics(cls, item_text: str) -> Dict[str, Any]:
        """
        Identify characteristics of a plumbing item from text
        
        Args:
            item_text: Item description or code
            
        Returns:
            Dict with identified characteristics
        """
        import re
        
        characteristics = {
            'has_size': False,
            'material': None,
            'connection_type': None,
            'fitting_type': None
        }
        
        item_lower = item_text.lower()
        
        # Check for size
        size_match = re.search(cls.ITEM_PATTERNS['pipe_sizes'], item_lower)
        if size_match:
            characteristics['has_size'] = True
            characteristics['size'] = size_match.group(1)
        
        # Check for material
        for material in cls.ITEM_PATTERNS['material_types']:
            if material.lower() in item_lower:
                characteristics['material'] = material
                break
        
        # Check for connection type
        for conn_type in cls.ITEM_PATTERNS['connection_types']:
            if conn_type.lower() in item_lower:
                characteristics['connection_type'] = conn_type
                break
        
        # Check for fitting type
        for fitting in cls.ITEM_PATTERNS['common_fittings']:
            if fitting.lower() in item_lower:
                characteristics['fitting_type'] = fitting
                break
        
        return characteristics
    
    @classmethod
    def get_workflow_stage_info(cls, workflow: str, stage: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a workflow stage
        
        Args:
            workflow: Workflow name
            stage: Stage name
            
        Returns:
            Stage information
        """
        if workflow not in cls.WORKFLOW_STAGES:
            return None
        
        stages = cls.WORKFLOW_STAGES[workflow]
        if stage.lower() not in [s.lower() for s in stages]:
            return None
        
        # Find stage index
        stage_index = next(
            i for i, s in enumerate(stages)
            if s.lower() == stage.lower()
        )
        
        return {
            'workflow': workflow,
            'stage': stages[stage_index],
            'index': stage_index,
            'total_stages': len(stages),
            'is_initial': stage_index == 0,
            'is_final': stage_index == len(stages) - 1,
            'previous_stage': stages[stage_index - 1] if stage_index > 0 else None,
            'next_stage': stages[stage_index + 1] if stage_index < len(stages) - 1 else None
        }


class SemanticEnhancer:
    """Main semantic enhancement coordinator"""
    
    def __init__(self):
        # Load semantic configuration
        current_dir = Path(__file__).parent
        semantic_file = current_dir / 'prompts' / 'semantic_mappings.json'
        
        with open(semantic_file, 'r', encoding='utf-8') as f:
            self.semantic_config = json.load(f)
        
        self.semantic_mapper = SemanticMapper(self.semantic_config)
        self.relationship_navigator = RelationshipNavigator()
        self.domain_knowledge = DomainKnowledge()
    
    def enhance_with_semantics(
        self,
        question: str,
        entities: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Add semantic understanding to a query
        
        Args:
            question: User question
            entities: Extracted entities (optional)
            
        Returns:
            Dict with semantic enhancements
        """
        logger.info(f"Adding semantic enhancements to: {question[:100]}...")
        
        enhancements = {
            'canonical_terms': {},
            'relationships': [],
            'domain_insights': [],
            'table_suggestions': []
        }
        
        # Find canonical terms for common words
        words = question.lower().split()
        for word in words:
            canonical = self.semantic_mapper.find_canonical_term(word)
            if canonical:
                enhancements['canonical_terms'][word] = {
                    'canonical': canonical,
                    'all_terms': self.semantic_mapper.get_all_terms(canonical)
                }
        
        # Suggest table relationships based on entities
        if entities:
            tables_mentioned = set()
            
            if entities.get('supplier_mentions'):
                tables_mentioned.add('suppliers')
            
            if entities.get('item_mentions') or entities.get('plumbing_items'):
                tables_mentioned.add('invoice_items')
            
            if 'invoice' in question.lower():
                tables_mentioned.add('invoices')
            
            # Find relationships between mentioned tables
            tables_list = list(tables_mentioned)
            for i, table1 in enumerate(tables_list):
                for table2 in tables_list[i+1:]:
                    join_path = self.relationship_navigator.get_join_path(table1, table2)
                    if join_path:
                        enhancements['relationships'].append({
                            'from_table': table1,
                            'to_table': table2,
                            'join_info': join_path
                        })
        
        # Add domain-specific insights
        if entities and entities.get('plumbing_items'):
            for item in entities['plumbing_items']:
                characteristics = self.domain_knowledge.identify_item_characteristics(item)
                if any(characteristics.values()):
                    enhancements['domain_insights'].append({
                        'item': item,
                        'characteristics': characteristics
                    })
        
        # Suggest appropriate tables for multi-table queries
        if entities and entities.get('multi_table_query'):
            mtq = entities['multi_table_query']
            enhancements['table_suggestions'] = mtq['tables']
        
        logger.info(
            f"Semantic enhancements complete. "
            f"Found {len(enhancements['canonical_terms'])} terms"
        )
        
        return enhancements


# Singleton instance
_semantic_enhancer = None


def get_semantic_enhancer() -> SemanticEnhancer:
    """Get or create SemanticEnhancer instance (singleton pattern)"""
    global _semantic_enhancer
    if _semantic_enhancer is None:
        _semantic_enhancer = SemanticEnhancer()
    return _semantic_enhancer

