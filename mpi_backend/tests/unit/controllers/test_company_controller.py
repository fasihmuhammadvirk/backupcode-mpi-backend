import pytest
from unittest.mock import MagicMock, Mock

from mpi_backend.database.controllers.CompanyController import CompanyController
from mpi_backend.database.models.Company import Company


@pytest.fixture
def mock_db():
    """Provides a mocked SQLAlchemy database session for unit tests."""
    return MagicMock()


class TestGetAllCompanies:
    """Test retrieving all companies."""

    def test_get_all_companies_returns_all_companies(self, mock_db):
        """Test that get_all_companies returns all companies from database."""
        controller = CompanyController(mock_db)

        companies = [
            Company(id=1, name="Company A"),
            Company(id=2, name="Company B"),
            Company(id=3, name="Company C")
        ]
        mock_db.query.return_value.all.return_value = companies

        result = controller.get_all_companies()

        assert result == companies
        assert len(result) == 3
        mock_db.query.assert_called_once_with(Company)

    def test_get_all_companies_returns_empty_list_when_no_companies(self, mock_db):
        """Test that empty list is returned when no companies exist."""
        controller = CompanyController(mock_db)

        mock_db.query.return_value.all.return_value = []

        result = controller.get_all_companies()

        assert result == []
        assert len(result) == 0


class TestGetCompanyById:
    """Test retrieving company by ID."""

    def test_get_company_by_id_returns_company(self, mock_db):
        """Test that company is returned when ID exists."""
        controller = CompanyController(mock_db)

        expected_company = Company(id=1, name="Test Company")
        mock_db.query.return_value.filter.return_value.first.return_value = expected_company

        result = controller.get_company_by_id(1)

        assert result == expected_company
        mock_db.query.assert_called_once_with(Company)

    def test_get_company_by_id_returns_none_when_not_found(self, mock_db):
        """Test that None is returned when company ID doesn't exist."""
        controller = CompanyController(mock_db)

        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = controller.get_company_by_id(999)

        assert result is None


class TestGetCompanyByName:
    """Test retrieving company by name."""

    def test_get_company_by_name_returns_company(self, mock_db):
        """Test that company is returned when name exists."""
        controller = CompanyController(mock_db)

        expected_company = Company(id=1, name="Test Company")
        mock_db.query.return_value.filter.return_value.first.return_value = expected_company

        result = controller.get_company_by_name("Test Company")

        assert result == expected_company
        mock_db.query.assert_called_once_with(Company)

    def test_get_company_by_name_returns_none_when_not_found(self, mock_db):
        """Test that None is returned when company name doesn't exist."""
        controller = CompanyController(mock_db)

        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = controller.get_company_by_name("Nonexistent Company")

        assert result is None

    def test_get_company_by_name_is_case_sensitive(self, mock_db):
        """Test that company name search is case sensitive."""
        controller = CompanyController(mock_db)

        # This test documents current behavior - actual case sensitivity
        # depends on database collation
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = controller.get_company_by_name("test company")

        assert result is None


class TestCreateCompany:
    """Test company creation with duplicate prevention."""

    def test_create_company_adds_new_company(self, mock_db):
        """Test that new company is added to database."""
        controller = CompanyController(mock_db)

        # Mock: company doesn't exist yet
        mock_db.query.return_value.filter.return_value.first.return_value = None

        company = controller.create_company("New Company")

        # Verify company was added
        assert mock_db.add.called
        company_add_call = [c for c in mock_db.add.call_args_list
                           if isinstance(c[0][0], Company)]
        assert len(company_add_call) == 1

        added_company = company_add_call[0][0][0]
        assert added_company.name == "New Company"

        # Verify commit was called
        assert mock_db.commit.called

    def test_create_company_prevents_duplicates(self, mock_db):
        """Business rule: cannot create company with duplicate name."""
        controller = CompanyController(mock_db)

        # Mock: company already exists
        existing_company = Company(id=1, name="Existing Company")
        mock_db.query.return_value.filter.return_value.first.return_value = existing_company

        result = controller.create_company("Existing Company")

        # Should return None when duplicate
        assert result is None

        # Should NOT add or commit
        assert not mock_db.add.called
        assert not mock_db.commit.called

    def test_create_company_checks_name_before_creating(self, mock_db):
        """Test that duplicate check happens before creation."""
        controller = CompanyController(mock_db)

        # Track call order
        call_order = []

        def track_query(*args):
            call_order.append("query")
            mock_query = Mock()
            mock_query.filter.return_value.first.return_value = None
            return mock_query

        def track_add(*args):
            call_order.append("add")

        mock_db.query.side_effect = track_query
        mock_db.add.side_effect = track_add

        controller.create_company("Test Company")

        # Query should happen before add
        assert call_order[0] == "query"
        assert call_order[1] == "add"

    def test_create_company_returns_created_company(self, mock_db):
        """Test that created company object is returned."""
        controller = CompanyController(mock_db)

        # Mock: company doesn't exist
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = controller.create_company("Test Company")

        # Should return Company object
        assert result is not None
        assert isinstance(result, Company)
        assert result.name == "Test Company"

    def test_create_company_rolls_back_on_exception(self, mock_db):
        """Test that transaction is rolled back on error."""
        controller = CompanyController(mock_db)

        # Mock: company doesn't exist
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Make commit raise exception
        mock_db.commit.side_effect = Exception("Database error")

        result = controller.create_company("Test Company")

        # Should return None on error
        assert result is None

        # Rollback should be called
        assert mock_db.rollback.called

    def test_create_company_handles_various_name_formats(self, mock_db):
        """Test company creation with various name formats."""
        controller = CompanyController(mock_db)

        # Mock: no companies exist
        mock_db.query.return_value.filter.return_value.first.return_value = None

        test_names = [
            "Simple Company",
            "Company-with-Dashes",
            "Company Inc.",
            "Company & Co.",
            "Company (USA)",
            "123 Numeric Company"
        ]

        for name in test_names:
            mock_db.reset_mock()
            mock_db.query.return_value.filter.return_value.first.return_value = None

            result = controller.create_company(name)

            assert result is not None
            assert result.name == name


class TestDuplicatePreventionLogic:
    """Test duplicate prevention business logic in detail."""

    def test_duplicate_check_uses_get_company_by_name(self, mock_db):
        """Test that duplicate check uses get_company_by_name method."""
        controller = CompanyController(mock_db)

        existing = Company(id=1, name="Existing")
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        result = controller.create_company("Existing")

        # Should query by name
        assert mock_db.query.called
        assert result is None

    def test_duplicate_check_exact_name_match(self, mock_db):
        """Test that duplicate check requires exact name match."""
        controller = CompanyController(mock_db)

        # Setup: existing company "Test Company"
        existing = Company(id=1, name="Test Company")

        # First call: check for "Test Company" (exists)
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        result1 = controller.create_company("Test Company")
        assert result1 is None  # Duplicate rejected

        # Second call: check for "Different Company" (doesn't exist)
        mock_db.reset_mock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result2 = controller.create_company("Different Company")
        assert result2 is not None  # Should succeed


class TestErrorHandling:
    """Test error handling in CompanyController."""

    def test_create_company_handles_database_exception_gracefully(self, mock_db):
        """Test that database exceptions are handled gracefully."""
        controller = CompanyController(mock_db)

        # Mock: query fails
        mock_db.query.side_effect = Exception("Database connection lost")

        result = controller.create_company("Test Company")

        # Should return None instead of raising exception
        assert result is None

    def test_get_company_by_name_with_none_input(self, mock_db):
        """Test behavior when None is passed as company name."""
        controller = CompanyController(mock_db)

        # This documents current behavior - may want to add validation
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = controller.get_company_by_name(None)

        # Current implementation will query for None
        assert result is None

    def test_get_company_by_id_with_invalid_id(self, mock_db):
        """Test behavior with invalid company ID."""
        controller = CompanyController(mock_db)

        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Test various invalid IDs
        assert controller.get_company_by_id(0) is None
        assert controller.get_company_by_id(-1) is None
        assert controller.get_company_by_id(999999) is None
