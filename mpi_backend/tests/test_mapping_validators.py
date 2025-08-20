#!/usr/bin/env python3
"""
Comprehensive test suite for mapping validation utilities.
Tests temporary mapping detection, validation rules, and data quality checks.
"""

import pytest
from unittest.mock import Mock, patch

from mpi_backend.utils.mapping_validators import (
    is_temporary_mapping,
    validate_mapping_quality,
    is_valid_mpi_code,
    sanitize_mapping_data,
    detect_placeholder_patterns,
    validate_mapping_completeness,
    get_mapping_quality_score,
    suggest_mapping_improvements,
    TEMPORARY_MPI_PATTERNS,
    TEMPORARY_DESCRIPTIONS
)


class TestMappingValidators:
    """Test suite for mapping validation utilities."""

    def test_is_temporary_mapping_uidi_patterns(self):
        """Test detection of UIDI patterns as temporary."""
        uidi_codes = [
            "UIDI001",
            "UIDI_12345",
            "UIDIXYZ",
            "uidi-test",  # Case variations
            "UIDI"
        ]
        
        for code in uidi_codes:
            assert is_temporary_mapping(code) is True
            assert is_temporary_mapping(code.lower()) is True  # Case insensitive

    def test_is_temporary_mapping_no_match_patterns(self):
        """Test detection of 'No Match' patterns as temporary."""
        no_match_codes = [
            "No Match",
            "No Match Item",
            "NO MATCH",
            "no match"
        ]
        
        for code in no_match_codes:
            assert is_temporary_mapping(code) is True

    def test_is_temporary_mapping_temporary_patterns(self):
        """Test detection of temporary/placeholder patterns."""
        temp_patterns = [
            "Temp123",
            "TEMP_ITEM",
            "TMP001",
            "PLACEHOLDER_ITEM",
            "Temporary Item"
        ]
        
        for pattern in temp_patterns:
            assert is_temporary_mapping(pattern) is True

    def test_is_temporary_mapping_valid_codes(self):
        """Test that valid MPI codes are not flagged as temporary."""
        valid_codes = [
            "10 Materials",
            "20 Labor",
            "30 Equipment",
            "MPI12345",
            "PART_ABC123",
            "FITTING_001"
        ]
        
        for code in valid_codes:
            assert is_temporary_mapping(code) is False

    def test_is_temporary_mapping_with_description(self):
        """Test temporary detection using both code and description."""
        # Valid code but temporary description
        assert is_temporary_mapping("10 Materials", "No Match") is True
        assert is_temporary_mapping("PART123", "UIDI") is True
        assert is_temporary_mapping("VALID001", "Temporary") is True
        
        # Both valid
        assert is_temporary_mapping("10 Materials", "Standard Pipe") is False

    def test_is_temporary_mapping_with_supplier_context(self):
        """Test temporary detection with supplier context."""
        # Some patterns might be supplier-specific
        assert is_temporary_mapping("TEMP001", None, "BMW Plumbing") is True
        assert is_temporary_mapping("VALID001", None, "BMW Plumbing") is False

    def test_is_temporary_mapping_edge_cases(self):
        """Test edge cases for temporary mapping detection."""
        edge_cases = [
            (None, None, None, False),  # All None
            ("", "", "", False),  # Empty strings
            ("   ", "   ", "", False),  # Whitespace
            ("UIDI", "", "", True),  # Valid pattern with empty description
        ]
        
        for mpi_code, description, supplier, expected in edge_cases:
            result = is_temporary_mapping(mpi_code, description, supplier)
            assert result == expected

    def test_validate_mapping_quality_complete_mapping(self):
        """Test quality validation for complete mappings."""
        complete_mapping = {
            'item': 'PART001',
            'description': 'Standard Pipe Fitting',
            'supplier': 'BMW Plumbing',
            'mpi_item': '10 Materials',
            'mpi_description': 'Pipe Fitting - Standard'
        }
        
        result = validate_mapping_quality(complete_mapping)
        
        assert result['is_valid'] is True
        assert result['quality_score'] > 0.8
        assert len(result['issues']) == 0

    def test_validate_mapping_quality_incomplete_mapping(self):
        """Test quality validation for incomplete mappings."""
        incomplete_mapping = {
            'item': 'PART002',
            'description': '',  # Missing description
            'supplier': 'BMW Plumbing',
            'mpi_item': '',  # Missing MPI item
            'mpi_description': None  # Missing MPI description
        }
        
        result = validate_mapping_quality(incomplete_mapping)
        
        assert result['is_valid'] is False
        assert result['quality_score'] < 0.5
        assert len(result['issues']) > 0
        assert any('missing' in issue.lower() for issue in result['issues'])

    def test_validate_mapping_quality_temporary_mapping(self):
        """Test quality validation for temporary mappings."""
        temporary_mapping = {
            'item': 'PART003',
            'description': 'Some Item',
            'supplier': 'BMW Plumbing',
            'mpi_item': 'UIDI001',  # Temporary code
            'mpi_description': 'No Match'  # Temporary description
        }
        
        result = validate_mapping_quality(temporary_mapping)
        
        assert result['is_valid'] is False
        assert 'temporary' in str(result['issues']).lower()

    def test_is_valid_mpi_code_valid_codes(self):
        """Test validation of valid MPI codes."""
        valid_codes = [
            "10 Materials",
            "20 Labor",
            "30 Equipment",
            "40 Overhead",
            "50 Miscellaneous",
            "10.1 Pipe Materials",
            "20.2 Skilled Labor"
        ]
        
        for code in valid_codes:
            assert is_valid_mpi_code(code) is True

    def test_is_valid_mpi_code_invalid_codes(self):
        """Test validation of invalid MPI codes."""
        invalid_codes = [
            "UIDI001",
            "No Match",
            "Temporary",
            "",
            None,
            "Invalid Code 999",
            "ABC123"  # No category number
        ]
        
        for code in invalid_codes:
            assert is_valid_mpi_code(code) is False

    def test_sanitize_mapping_data_cleaning(self):
        """Test data sanitization and cleaning."""
        dirty_data = {
            'item': '  PART001  ',  # Extra whitespace
            'description': 'Item\nwith\nnewlines',  # Newlines
            'supplier': 'BMW Plumbing',
            'mpi_item': '\t10 Materials\t',  # Tabs
            'mpi_description': 'Description with    extra    spaces'
        }
        
        clean_data = sanitize_mapping_data(dirty_data)
        
        assert clean_data['item'] == 'PART001'
        assert '\n' not in clean_data['description']
        assert clean_data['mpi_item'] == '10 Materials'
        assert '    ' not in clean_data['mpi_description']

    def test_sanitize_mapping_data_normalization(self):
        """Test data normalization during sanitization."""
        data_to_normalize = {
            'item': 'part001',  # Lowercase
            'description': 'PIPE FITTING',  # Uppercase
            'supplier': 'bmw plumbing',  # Mixed case
            'mpi_item': '10 materials',  # Inconsistent case
            'mpi_description': 'pipe fitting - standard'
        }
        
        normalized_data = sanitize_mapping_data(data_to_normalize)
        
        # Check that normalization rules are applied consistently
        assert normalized_data['item'] == normalized_data['item'].strip()
        assert isinstance(normalized_data['description'], str)

    def test_detect_placeholder_patterns_common_patterns(self):
        """Test detection of common placeholder patterns."""
        placeholder_texts = [
            "TBD",
            "To Be Determined",
            "Unknown",
            "N/A",
            "Not Available",
            "Pending",
            "TODO",
            "XXX",
            "???",
            "TBC",  # To Be Confirmed
            "TBA"   # To Be Announced
        ]
        
        for text in placeholder_texts:
            assert detect_placeholder_patterns(text) is True
            assert detect_placeholder_patterns(text.lower()) is True

    def test_detect_placeholder_patterns_valid_text(self):
        """Test that valid text is not flagged as placeholder."""
        valid_texts = [
            "Standard Pipe Fitting",
            "10 Materials",
            "BMW Part 12345",
            "Copper Pipe 1/2 inch",
            "Labor - Installation"
        ]
        
        for text in valid_texts:
            assert detect_placeholder_patterns(text) is False

    def test_validate_mapping_completeness_complete(self):
        """Test completeness validation for complete mappings."""
        complete_mapping = {
            'item': 'PART001',
            'description': 'Pipe Fitting',
            'supplier': 'BMW Plumbing',
            'mpi_item': '10 Materials',
            'mpi_description': 'Standard Pipe Fitting'
        }
        
        result = validate_mapping_completeness(complete_mapping)
        
        assert result['is_complete'] is True
        assert result['completeness_score'] == 1.0
        assert len(result['missing_fields']) == 0

    def test_validate_mapping_completeness_partial(self):
        """Test completeness validation for partial mappings."""
        partial_mapping = {
            'item': 'PART002',
            'description': '',  # Missing
            'supplier': 'BMW Plumbing',
            'mpi_item': '10 Materials',
            # 'mpi_description' missing entirely
        }
        
        result = validate_mapping_completeness(partial_mapping)
        
        assert result['is_complete'] is False
        assert result['completeness_score'] < 1.0
        assert 'description' in result['missing_fields']
        assert 'mpi_description' in result['missing_fields']

    def test_get_mapping_quality_score_high_quality(self):
        """Test quality scoring for high-quality mappings."""
        high_quality_mapping = {
            'item': 'BMW_PART_12345',
            'description': 'Copper Pipe Fitting 1/2 inch',
            'supplier': 'BMW Plumbing Supplies',
            'mpi_item': '10 Materials',
            'mpi_description': 'Pipe Fittings - Copper'
        }
        
        score = get_mapping_quality_score(high_quality_mapping)
        
        assert score >= 0.8  # High quality
        assert score <= 1.0

    def test_get_mapping_quality_score_low_quality(self):
        """Test quality scoring for low-quality mappings."""
        low_quality_mapping = {
            'item': 'X',  # Too short
            'description': 'Item',  # Too generic
            'supplier': '',  # Missing
            'mpi_item': 'UIDI001',  # Temporary
            'mpi_description': 'TBD'  # Placeholder
        }
        
        score = get_mapping_quality_score(low_quality_mapping)
        
        assert score <= 0.3  # Low quality
        assert score >= 0.0

    def test_suggest_mapping_improvements_actionable_suggestions(self):
        """Test that improvement suggestions are actionable."""
        problematic_mapping = {
            'item': 'PART',  # Too generic
            'description': 'item desc',  # Too short
            'supplier': 'Supplier',
            'mpi_item': 'TEMP001',  # Temporary
            'mpi_description': 'TBD'  # Placeholder
        }
        
        suggestions = suggest_mapping_improvements(problematic_mapping)
        
        assert len(suggestions) > 0
        assert any('specific' in suggestion.lower() for suggestion in suggestions)
        assert any('description' in suggestion.lower() for suggestion in suggestions)
        assert any('temporary' in suggestion.lower() for suggestion in suggestions)

    def test_suggest_mapping_improvements_good_mapping(self):
        """Test suggestions for already good mappings."""
        good_mapping = {
            'item': 'BMW_COPPER_PIPE_12345',
            'description': 'Copper Pipe Fitting 1/2 inch with threads',
            'supplier': 'BMW Plumbing Supplies',
            'mpi_item': '10 Materials',
            'mpi_description': 'Pipe Fittings - Copper - Threaded'
        }
        
        suggestions = suggest_mapping_improvements(good_mapping)
        
        # Should have few or no suggestions
        assert len(suggestions) <= 2

    def test_pattern_matching_case_sensitivity(self):
        """Test that pattern matching handles case sensitivity correctly."""
        test_cases = [
            ("uidi001", True),  # Lowercase UIDI
            ("UIDI001", True),  # Uppercase UIDI
            ("UiDi001", True),  # Mixed case UIDI
            ("no match", True),  # Lowercase no match
            ("NO MATCH", True),  # Uppercase no match
            ("No Match", True),  # Title case no match
        ]
        
        for pattern, expected in test_cases:
            assert is_temporary_mapping(pattern) == expected

    def test_supplier_specific_validation_rules(self):
        """Test supplier-specific validation rules if they exist."""
        # Some suppliers might have specific patterns or rules
        bmw_mapping = {
            'item': 'BMW_PART_001',
            'supplier': 'BMW Plumbing Supplies'
        }
        
        supreme_mapping = {
            'item': 'SUP_PART_001',
            'supplier': 'Supreme Plumbing Supply'
        }
        
        # Both should be valid, but might have different validation rules
        bmw_result = validate_mapping_quality(bmw_mapping)
        supreme_result = validate_mapping_quality(supreme_mapping)
        
        assert isinstance(bmw_result, dict)
        assert isinstance(supreme_result, dict)

    def test_bulk_validation_operations(self):
        """Test validation of multiple mappings at once."""
        mappings = [
            {
                'item': f'PART_{i:03d}',
                'description': f'Test Item {i}',
                'supplier': 'Test Supplier',
                'mpi_item': '10 Materials' if i % 2 == 0 else 'UIDI001',
                'mpi_description': f'Test Description {i}'
            }
            for i in range(10)
        ]
        
        results = []
        for mapping in mappings:
            result = validate_mapping_quality(mapping)
            results.append(result)
        
        # Should have mixed results (some valid, some invalid due to UIDI)
        valid_count = sum(1 for r in results if r['is_valid'])
        invalid_count = sum(1 for r in results if not r['is_valid'])
        
        assert valid_count > 0
        assert invalid_count > 0

    def test_performance_with_large_datasets(self):
        """Test validation performance with larger datasets."""
        import time
        
        # Create a large mapping for testing
        large_mapping = {
            'item': 'A' * 1000,  # Long item code
            'description': 'B' * 2000,  # Long description
            'supplier': 'Test Supplier',
            'mpi_item': '10 Materials',
            'mpi_description': 'C' * 1000  # Long MPI description
        }
        
        start_time = time.time()
        result = validate_mapping_quality(large_mapping)
        end_time = time.time()
        
        # Should complete within reasonable time
        assert end_time - start_time < 1.0  # Less than 1 second
        assert isinstance(result, dict)

    def test_unicode_and_special_character_handling(self):
        """Test handling of Unicode and special characters."""
        unicode_mapping = {
            'item': 'PART_ñáéíóú',
            'description': 'Piñón con ñ and special chars: @#$%^&*()',
            'supplier': 'Señor Plumbing Süpply',
            'mpi_item': '10 Materials',
            'mpi_description': 'Descripción con acentos'
        }
        
        result = validate_mapping_quality(unicode_mapping)
        
        assert isinstance(result, dict)
        assert 'is_valid' in result
        
        # Should handle Unicode without errors
        cleaned = sanitize_mapping_data(unicode_mapping)
        assert isinstance(cleaned, dict)

    def test_validation_configuration_options(self):
        """Test validation with different configuration options."""
        mapping = {
            'item': 'TEST001',
            'description': 'Test Item',
            'supplier': 'Test Supplier',
            'mpi_item': '10 Materials',
            'mpi_description': 'Test Description'
        }
        
        # Test with strict validation
        strict_result = validate_mapping_quality(mapping, strict=True)
        
        # Test with lenient validation
        lenient_result = validate_mapping_quality(mapping, strict=False)
        
        # Both should return valid results, but might have different criteria
        assert isinstance(strict_result, dict)
        assert isinstance(lenient_result, dict)

    def test_error_handling_and_edge_cases(self):
        """Test error handling for edge cases."""
        edge_cases = [
            None,  # None input
            {},    # Empty dict
            {'item': None},  # None values
            {'invalid_field': 'value'},  # Invalid fields
        ]
        
        for case in edge_cases:
            try:
                result = validate_mapping_quality(case)
                # Should return a result or handle gracefully
                assert isinstance(result, dict)
            except (TypeError, ValueError, AttributeError):
                # Acceptable to raise these exceptions for invalid input
                pass
