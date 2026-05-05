"""
Comprehensive tests for Intelligent QA System enhancements
Tests natural language understanding, fuzzy search, date parsing, and semantic processing
"""

from datetime import datetime
from mpi_backend.utils.chatbot.intelligent_query_processor import (
    DateParser, SynonymExpander, EntityExtractor, get_query_enhancer
)
from mpi_backend.utils.chatbot.fuzzy_search_builder import (
    FuzzySearchBuilder, SimilarityMatcher, get_fuzzy_search_builder
)
from mpi_backend.utils.chatbot.query_preprocessor import (
    TypoDetector, QueryNormalizer, get_query_preprocessor
)
from mpi_backend.utils.chatbot.semantic_enhancer import (
    SemanticMapper, RelationshipNavigator, get_semantic_enhancer
)


class TestDateParser:
    """Test natural language date parsing"""
    
    def test_parse_today(self):
        parser = DateParser({'date_patterns': {
            'relative_dates': {}, 'month_names': {}, 'quarter_mapping': {}
        }})
        result = parser.parse("show invoices from today")
        assert result['found'] is True
        assert result['type'] == 'relative'
        assert result['start_date'] == datetime.now().date()
    
    def test_parse_last_month(self):
        parser = DateParser({'date_patterns': {
            'relative_dates': {}, 'month_names': {}, 'quarter_mapping': {}
        }})
        result = parser.parse("invoices from last month")
        assert result['found'] is True
        assert result['type'] == 'relative'
        # Check date is approximately last month
        assert result['start_date'] < datetime.now().date()
    
    def test_parse_month_name(self):
        parser = DateParser({'date_patterns': {
            'relative_dates': {},
            'month_names': {
                'july': 7, 'jul': 7
            },
            'quarter_mapping': {}
        }})
        result = parser.parse("show July invoices")
        assert result['found'] is True
        assert result['type'] == 'month'
        assert result['start_date'].month == 7
    
    def test_parse_month_with_year(self):
        parser = DateParser({'date_patterns': {
            'relative_dates': {},
            'month_names': {'july': 7},
            'quarter_mapping': {}
        }})
        result = parser.parse("invoices from July 2024")
        assert result['found'] is True
        assert result['start_date'].year == 2024
        assert result['start_date'].month == 7
    
    def test_parse_quarter(self):
        parser = DateParser({'date_patterns': {
            'relative_dates': {},
            'month_names': {'january': 1, 'march': 1},
            'quarter_mapping': {'Q1': [1, 2, 3], 'Q2': [4, 5, 6]}
        }})
        result = parser.parse("show Q1 2024 invoices")
        assert result['found'] is True
        assert result['type'] == 'quarter'
        assert result['start_date'].month == 1
        assert result['end_date'].month == 3
    
    def test_parse_date_range(self):
        parser = DateParser({'date_patterns': {
            'relative_dates': {}, 'month_names': {'january': 1, 'december': 12}, 'quarter_mapping': {}
        }})
        result = parser.parse("from 2024-01-01 to 2024-12-31")
        assert result['found'] is True
        assert result['type'] == 'explicit_range'
        assert str(result['start_date']) == '2024-01-01'
        assert str(result['end_date']) == '2024-12-31'
    
    def test_no_date_found(self):
        parser = DateParser({'date_patterns': {
            'relative_dates': {}, 'month_names': {}, 'quarter_mapping': {}
        }})
        result = parser.parse("show all invoices")
        assert result['found'] is False


class TestSynonymExpander:
    """Test business term synonym expansion"""
    
    def test_expand_abbreviations(self):
        expander = SynonymExpander({
            'synonyms': {},
            'abbreviations': {'QB': 'QuickBooks', 'PO': 'purchase order'}
        })
        result = expander.expand("show QB exports")
        assert 'QuickBooks' in result['expanded_text']
        assert len(result['abbreviations_expanded']) > 0
    
    def test_identify_synonyms(self):
        expander = SynonymExpander({
            'synonyms': {
                'supplier': ['vendor', 'company'],
                'item': ['product', 'part']
            },
            'abbreviations': {}
        })
        result = expander.expand("find vendor products")
        assert len(result['replacements']) == 2
        # Should find vendor -> supplier and products -> items
    
    def test_multiple_abbreviations(self):
        expander = SynonymExpander({
            'synonyms': {},
            'abbreviations': {'QB': 'QuickBooks', 'inv': 'invoice'}
        })
        result = expander.expand("QB inv exports")
        assert 'QuickBooks' in result['expanded_text']
        assert 'invoice' in result['expanded_text']


class TestEntityExtractor:
    """Test entity extraction from queries"""
    
    def test_extract_supplier_mentions(self):
        extractor = EntityExtractor({'domain_terms': {}, 'multi_table_queries': {}})
        result = extractor.extract("show invoices from BMW Plumbing Supplies")
        assert len(result['supplier_mentions']) > 0
    
    def test_extract_reference_numbers(self):
        extractor = EntityExtractor({'domain_terms': {}, 'multi_table_queries': {}})
        result = extractor.extract("find invoice ABC-123")
        assert 'ABC-123' in result['reference_numbers']
    
    def test_extract_plumbing_items(self):
        extractor = EntityExtractor({
            'domain_terms': {'plumbing_items': ['pipe', 'valve', 'fitting']},
            'multi_table_queries': {}
        })
        result = extractor.extract("show all pipe items")
        assert 'pipe' in result['plumbing_items']
    
    def test_multi_table_query_detection(self):
        extractor = EntityExtractor({
            'domain_terms': {},
            'multi_table_queries': {
                'org_item': {
                    'tables': ['temporary_item_mappings', 'supplier_item_mappings'],
                    'columns': {},
                    'description': 'Multi-table org item query'
                }
            }
        })
        result = extractor.extract("how many org items for NHPT20-W")
        assert result['multi_table_query'] is not None
        assert result['multi_table_query']['type'] == 'org_item'


class TestFuzzySearchBuilder:
    """Test fuzzy search SQL generation"""
    
    def test_build_fuzzy_supplier_search(self):
        builder = FuzzySearchBuilder(similarity_threshold=0.3)
        result = builder.build_fuzzy_supplier_search("BMW Plumbing", exact_first=True)
        assert len(result['strategies']) >= 2
        assert result['strategies'][0]['name'] == 'exact'
        assert 'similarity' in [s['name'] for s in result['strategies']]
    
    def test_build_fuzzy_item_search(self):
        builder = FuzzySearchBuilder()
        result = builder.build_fuzzy_item_search("pipe")
        assert len(result['strategies']) >= 2
        assert result['columns'] == [
            'item', 'description', 'mpi_item', 'mpi_description'
        ]
    
    def test_similarity_matcher(self):
        matcher = SimilarityMatcher()
        where_clause, order_clause = matcher.build_similarity_condition(
            'supplier_name', 'BMW', threshold=0.3
        )
        assert 'similarity' in where_clause
        assert '> 0.3' in where_clause
        assert 'similarity' in order_clause
        assert 'DESC' in order_clause


class TestQueryNormalizer:
    """Test query normalization"""
    
    def test_normalize_item_codes(self):
        normalizer = QueryNormalizer()
        result = normalizer.normalize_item_codes("find item nhpt20-w")
        assert 'NHPT20-W' in result
    
    def test_normalize_dates(self):
        normalizer = QueryNormalizer()
        result = normalizer.normalize_dates("invoices from 12/25/2024")
        # Should convert to YYYY-MM-DD format
        assert '2024' in result
    
    def test_full_normalization(self):
        normalizer = QueryNormalizer()
        result = normalizer.normalize("find nhpt20-w from 12/25/2024")
        assert 'NHPT20-W' in result
        assert '2024' in result


class TestSemanticMapper:
    """Test semantic term mapping"""
    
    def test_find_canonical_term(self):
        mapper = SemanticMapper({
            'synonyms': {
                'supplier': ['vendor', 'company']
            },
            'abbreviations': {},
            'domain_terms': {}
        })
        canonical = mapper.find_canonical_term('vendor')
        assert canonical == 'supplier'
    
    def test_get_all_terms(self):
        mapper = SemanticMapper({
            'synonyms': {
                'supplier': ['vendor', 'company']
            },
            'abbreviations': {},
            'domain_terms': {}
        })
        all_terms = mapper.get_all_terms('supplier')
        assert 'supplier' in all_terms
        assert 'vendor' in all_terms
        assert 'company' in all_terms
    
    def test_expand_abbreviation(self):
        mapper = SemanticMapper({
            'synonyms': {},
            'abbreviations': {'QB': 'QuickBooks'},
            'domain_terms': {}
        })
        expanded = mapper.expand_abbreviation('QB')
        assert expanded == 'QuickBooks'


class TestRelationshipNavigator:
    """Test database relationship navigation"""
    
    def test_get_join_path_direct(self):
        navigator = RelationshipNavigator()
        join_path = navigator.get_join_path('invoices', 'suppliers')
        assert join_path is not None
        assert 'join_sql' in join_path
        assert 'supplier_id' in join_path['join_sql']
    
    def test_get_join_path_indirect(self):
        navigator = RelationshipNavigator()
        join_path = navigator.get_join_path('invoice_items', 'suppliers')
        assert join_path is not None
        assert join_path['type'] == 'indirect'
        assert 'invoices' in join_path['intermediate_tables']
    
    def test_get_searchable_columns(self):
        navigator = RelationshipNavigator()
        columns = navigator.get_searchable_columns('invoice_items')
        assert 'ref_no' in columns
        assert 'customer_job' in columns
        assert 'item' in columns
    
    def test_get_business_key(self):
        navigator = RelationshipNavigator()
        business_key = navigator.get_business_key('invoice_items')
        assert 'ref_no' in business_key
        assert 'customer_job' in business_key


class TestIntegration:
    """Integration tests for the complete intelligent QA system"""
    
    def test_query_enhancer_full_workflow(self):
        enhancer = get_query_enhancer()
        result = enhancer.enhance(
            "show me pipes from BMW last month"
        )
        assert result['has_enhancements'] is True
        assert result['entities']['plumbing_items']
        # Should detect date reference
        # Should detect supplier mention
    
    def test_preprocessor_full_workflow(self):
        preprocessor = get_query_preprocessor()
        result = preprocessor.preprocess("show invoices from BMW Plumbng")
        # Should normalize and potentially detect typo
        assert result['normalized_question'] is not None
    
    def test_semantic_enhancer_workflow(self):
        enhancer = get_semantic_enhancer()
        result = enhancer.enhance_with_semantics(
            "show vendor items",
            entities={'supplier_mentions': ['BMW']}
        )
        # Should map vendor -> supplier
        assert len(result['canonical_terms']) > 0


class TestBackwardCompatibility:
    """Test that enhancements don't break existing functionality"""
    
    def test_simple_query_still_works(self):
        enhancer = get_query_enhancer()
        result = enhancer.enhance("show all invoices")
        assert result['original_question'] == "show all invoices"
        assert result['enhanced_question'] is not None
    
    def test_exact_match_preserved(self):
        builder = get_fuzzy_search_builder()
        result = builder.build_fuzzy_supplier_search(
            "BMW Plumbing Supplies",
            exact_first=True
        )
        # First strategy should be exact match
        assert result['strategies'][0]['name'] == 'exact'
    
    def test_no_enhancements_graceful(self):
        enhancer = get_query_enhancer()
        result = enhancer.enhance("simple query")
        # Should not fail even if no enhancements detected
        assert 'enhanced_question' in result


class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_empty_query(self):
        enhancer = get_query_enhancer()
        result = enhancer.enhance("")
        assert result is not None
    
    def test_very_long_query(self):
        enhancer = get_query_enhancer()
        long_query = "show " + " ".join(["invoices"] * 100)
        result = enhancer.enhance(long_query)
        assert result is not None
    
    def test_special_characters(self):
        normalizer = QueryNormalizer()
        result = normalizer.normalize("find item @#$%^&*()")
        assert result is not None
    
    def test_unicode_characters(self):
        enhancer = get_query_enhancer()
        result = enhancer.enhance("show invoices from café supplier")
        assert result is not None

