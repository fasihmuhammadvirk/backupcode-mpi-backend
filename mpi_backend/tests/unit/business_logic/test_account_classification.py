"""
Unit tests for account classification business logic.

Tests the _auto_assign_account method which handles:
1. Priority order:
   - Preserve explicit 'A' if provided
   - UIDI mpi_item category mapping (M/E)
   - Exact classification match (M/E)
   - Fuzzy classification fallback
   - Keep current if 'L' or unknown
2. UIDI patterns mapping
3. Classification table lookup
4. Fallback behavior
"""

import pytest
from unittest.mock import MagicMock, Mock, patch
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController


pytestmark = pytest.mark.business_logic


class TestAccountClassificationPreserveExplicitA:
    """Test that explicit 'A' account is always preserved."""
    
    def test_preserve_explicit_a_account_uppercase(self, mock_db_session):
        """
        Test that explicit 'A' account is preserved.
        
        GIVEN current_account='A'
        WHEN auto-assigning account
        THEN should return 'A' (preserve explicit A)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Some Sheet",
            current_account="A",
            mpi_item="Some Item"
        )
        
        # Assert
        assert result == "A"
    
    def test_preserve_explicit_a_account_lowercase(self, mock_db_session):
        """
        Test that lowercase 'a' is also preserved as 'A'.
        
        GIVEN current_account='a' (lowercase)
        WHEN auto-assigning account
        THEN should return 'a' (preserve original case)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Some Sheet",
            current_account="a",
            mpi_item="Some Item"
        )
        
        # Assert
        assert result == "a"


class TestAccountClassificationUIDIMappings:
    """Test UIDI mpi_item category mappings."""
    
    def test_uidi_job_materials_purchased_maps_to_m(self, mock_db_session):
        """
        Test UIDI-JOB MATERIALS PURCHASED maps to 'M'.
        
        GIVEN mpi_item='UIDI-JOB MATERIALS PURCHASED'
        WHEN auto-assigning account
        THEN should return 'M'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="",
            current_account="",
            mpi_item="UIDI-JOB MATERIALS PURCHASED"
        )
        
        # Assert
        assert result == "M"
    
    def test_uidi_job_material_maps_to_m(self, mock_db_session):
        """
        Test UIDI JOB MATERIAL maps to 'M'.
        
        GIVEN mpi_item='UIDI JOB MATERIAL'
        WHEN auto-assigning account
        THEN should return 'M'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="",
            current_account="",
            mpi_item="UIDI JOB MATERIAL"
        )
        
        # Assert
        assert result == "M"
    
    def test_uidi_job_equipment_maps_to_e(self, mock_db_session):
        """
        Test UIDI-JOB EQUIPMENT maps to 'E'.
        
        GIVEN mpi_item='UIDI-JOB EQUIPMENT'
        WHEN auto-assigning account
        THEN should return 'E'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="",
            current_account="",
            mpi_item="UIDI-JOB EQUIPMENT"
        )
        
        # Assert
        assert result == "E"
    
    def test_uidi_sprinkler_specialty_item_maps_to_m(self, mock_db_session):
        """
        Test UIDI-SPRINKLER SPECIALTY ITEM maps to 'M'.
        
        GIVEN mpi_item='UIDI-SPRINKLER SPECIALTY ITEM'
        WHEN auto-assigning account
        THEN should return 'M'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="",
            current_account="",
            mpi_item="UIDI-SPRINKLER SPECIALTY ITEM"
        )
        
        # Assert
        assert result == "M"
    
    def test_uidi_drainage_material_maps_to_m(self, mock_db_session):
        """
        Test UIDI-DRAINAGE MATERIAL maps to 'M'.
        
        GIVEN mpi_item='UIDI-DRAINAGE MATERIAL'
        WHEN auto-assigning account
        THEN should return 'M'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="",
            current_account="",
            mpi_item="UIDI-DRAINAGE MATERIAL"
        )
        
        # Assert
        assert result == "M"
    
    def test_uidi_mapping_case_insensitive(self, mock_db_session):
        """
        Test UIDI mapping is case-insensitive.
        
        GIVEN mpi_item='uidi-job equipment' (lowercase)
        WHEN auto-assigning account
        THEN should return 'E' (case-insensitive match)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="",
            current_account="",
            mpi_item="uidi-job equipment"
        )
        
        # Assert
        assert result == "E"
    
    def test_uidi_mapping_only_if_no_current_account(self, mock_db_session):
        """
        Test UIDI mapping only applies if no current account.
        
        GIVEN mpi_item='UIDI-JOB EQUIPMENT' AND current_account='M'
        WHEN auto-assigning account
        THEN should return 'M' (current account preserved, UIDI not applied)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="",
            current_account="M",  # Already has account
            mpi_item="UIDI-JOB EQUIPMENT"
        )
        
        # Assert
        # Should return current since UIDI only applies if no current account
        assert result == "M"


class TestAccountClassificationExactMatch:
    """Test exact classification table matches."""
    
    def test_exact_classification_match_m(self, mock_db_session):
        """
        Test exact match for Materials (M) category.
        
        GIVEN sheet_name matches classification with category='M'
        WHEN auto-assigning account
        THEN should return 'M'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock classification lookup
        mock_classification = Mock()
        mock_classification.category = "M"
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = mock_classification
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Material Item",
            current_account="",
            mpi_item=""
        )
        
        # Assert
        assert result == "M"
    
    def test_exact_classification_match_e(self, mock_db_session):
        """
        Test exact match for Equipment (E) category.
        
        GIVEN sheet_name matches classification with category='E'
        WHEN auto-assigning account
        THEN should return 'E'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock classification lookup
        mock_classification = Mock()
        mock_classification.category = "E"
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = mock_classification
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Equipment Item",
            current_account="",
            mpi_item=""
        )
        
        # Assert
        assert result == "E"
    
    def test_classification_l_keeps_current(self, mock_db_session):
        """
        Test that Labor (L) category preserves current account.
        
        GIVEN sheet_name matches classification with category='L'
        WHEN auto-assigning account
        THEN should return current account (L not auto-assigned)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock classification lookup
        mock_classification = Mock()
        mock_classification.category = "L"
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = mock_classification
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Labor Item",
            current_account="X",  # Some current value
            mpi_item=""
        )
        
        # Assert
        assert result == "X"  # Current preserved
    
    def test_classification_category_case_handling(self, mock_db_session):
        """
        Test that category is converted to uppercase.
        
        GIVEN classification with category='m' (lowercase)
        WHEN auto-assigning account
        THEN should return 'M' (uppercase)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock classification lookup
        mock_classification = Mock()
        mock_classification.category = "m"  # lowercase
        
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = mock_classification
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Material Item",
            current_account="",
            mpi_item=""
        )
        
        # Assert
        assert result == "M"


class TestAccountClassificationFuzzyFallback:
    """Test fuzzy classification fallback."""
    
    @patch('mpi_backend.database.controllers.ItemClassification.ItemClassificationController')
    def test_fuzzy_classification_job_materials_purchased(self, mock_icc_class, mock_db_session):
        """
        Test fuzzy fallback for 'job materials purchased'.
        
        GIVEN no exact match but fuzzy returns 'job materials purchased'
        WHEN auto-assigning account
        THEN should return 'M'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock no exact match
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = None
        
        # Mock fuzzy classification
        mock_icc_instance = mock_icc_class.return_value
        mock_icc_instance.get_classification.return_value = "UnInvoiced JIP:Cost Of Materials:Job Materials Purchased"
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Pipe Fitting",
            current_account="",
            mpi_item=""
        )
        
        # Assert
        assert result == "M"
    
    @patch('mpi_backend.database.controllers.ItemClassification.ItemClassificationController')
    def test_fuzzy_classification_job_equipment(self, mock_icc_class, mock_db_session):
        """
        Test fuzzy fallback for 'job equipment'.
        
        GIVEN no exact match but fuzzy returns 'job equipment'
        WHEN auto-assigning account
        THEN should return 'E'
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock no exact match
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = None
        
        # Mock fuzzy classification
        mock_icc_instance = mock_icc_class.return_value
        mock_icc_instance.get_classification.return_value = "UnInvoiced JIP:Cost Of Materials:Job Equipment"
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Power Tool",
            current_account="",
            mpi_item=""
        )
        
        # Assert
        assert result == "E"


class TestAccountClassificationEdgeCases:
    """Test edge cases and error handling."""
    
    def test_no_match_returns_current(self, mock_db_session):
        """
        Test that when no match found, current account is returned.
        
        GIVEN no UIDI, no exact match, no fuzzy match
        WHEN auto-assigning account
        THEN should return current account
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock no exact match
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = None
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Unknown Item",
            current_account="X",
            mpi_item=""
        )
        
        # Assert
        assert result == "X"
    
    def test_empty_sheet_name_returns_current(self, mock_db_session):
        """
        Test that empty sheet_name returns current account.
        
        GIVEN empty sheet_name
        WHEN auto-assigning account
        THEN should return current account
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="",
            current_account="M",
            mpi_item=""
        )
        
        # Assert
        assert result == "M"
    
    def test_none_sheet_name_returns_current(self, mock_db_session):
        """
        Test that None sheet_name returns current account.
        
        GIVEN sheet_name=None
        WHEN auto-assigning account
        THEN should return current account
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name=None,
            current_account="E",
            mpi_item=""
        )
        
        # Assert
        assert result == "E"
    
    def test_whitespace_handling(self, mock_db_session):
        """
        Test that whitespace is properly trimmed.
        
        GIVEN inputs with leading/trailing whitespace
        WHEN auto-assigning account
        THEN whitespace should be trimmed for comparison
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="  ",  # Only whitespace
            current_account="  M  ",  # Whitespace around value
            mpi_item="  UIDI-JOB EQUIPMENT  "
        )
        
        # Assert
        # Should handle whitespace gracefully
        assert result in ["M", "E"]  # Either current trimmed or UIDI mapped
    
    def test_exception_handling_returns_current(self, mock_db_session):
        """
        Test that exceptions are handled and current account is returned.
        
        GIVEN an exception occurs during classification
        WHEN auto-assigning account
        THEN should return current account (graceful fallback)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock exception in query
        mock_db_session.query.side_effect = Exception("Database error")
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Some Item",
            current_account="M",
            mpi_item=""
        )
        
        # Assert
        assert result == "M"  # Returns current on error
    
    def test_none_current_account_returns_empty_string_when_no_match(self, mock_db_session):
        """
        Test that None current_account returns empty string when no match.
        
        GIVEN current_account=None AND no classification match
        WHEN auto-assigning account
        THEN should return empty string
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock no exact match
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = None
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Unknown Item",
            current_account=None,
            mpi_item=""
        )
        
        # Assert
        assert result == ""


class TestAccountClassificationPriorityOrder:
    """Test the priority order of classification rules."""
    
    def test_explicit_a_has_highest_priority(self, mock_db_session):
        """
        Test that explicit 'A' overrides all other rules.
        
        GIVEN current_account='A' AND UIDI item AND classification match
        WHEN auto-assigning account
        THEN should return 'A' (highest priority)
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock classification match
        mock_classification = Mock()
        mock_classification.category = "M"
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = mock_classification
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Material Item",
            current_account="A",  # Explicit A should win
            mpi_item="UIDI-JOB EQUIPMENT"  # Would normally return E
        )
        
        # Assert
        assert result == "A"  # A preserved despite UIDI and classification
    
    def test_uidi_has_priority_over_classification_when_no_current(self, mock_db_session):
        """
        Test that UIDI mapping has priority over classification when no current account.
        
        GIVEN UIDI item AND classification match AND no current account
        WHEN auto-assigning account
        THEN should use UIDI mapping
        """
        # Arrange
        controller = InvoiceItemController(mock_db_session)
        
        # Mock classification match (would return M)
        mock_classification = Mock()
        mock_classification.category = "M"
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = mock_classification
        
        # Act
        result = controller._auto_assign_account(
            sheet_name="Material Item",
            current_account="",  # No current
            mpi_item="UIDI-JOB EQUIPMENT"  # UIDI returns E
        )
        
        # Assert
        assert result == "E"  # UIDI wins over classification

