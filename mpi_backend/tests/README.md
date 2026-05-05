# MPI Backend Test Suite

## Overview

Comprehensive test suite with business logic coverage, professional organization, and industry best practices.

**Coverage Targets:**
- Overall: 80%+
- Business Logic: 90%+
- Controllers: 85%+
- Utils: 75%+

## Directory Structure

```
tests/
├── unit/                           # Unit tests (isolated, mocked dependencies)
│   ├── business_logic/            # Core business logic tests ⭐
│   │   ├── test_invoice_duplicate_detection.py
│   │   ├── test_reference_number_normalization.py
│   │   ├── test_quickbooks_tax_calculations.py
│   │   ├── test_statement_validation_rules.py
│   │   └── test_account_classification.py
│   ├── controllers/               # Controller unit tests
│   │   ├── test_company_controller.py
│   │   └── test_user_controller.py
│   ├── utils/                     # Utility function tests
│   │   ├── test_intelligent_qa.py          # QA system utilities
│   │   ├── test_auth_handler.py
│   │   ├── test_export_utils.py
│   │   ├── test_mapping_validators.py
│   │   ├── test_pdf_to_excel_conversion.py
│   │   └── [other utility tests]
│   └── models/                     # Model tests
│       ├── test_models.py
│       └── test_schema_variants.py
│
├── integration/                   # Integration tests (real DB)
│   ├── api/                       # API endpoint integration tests
│   │   ├── test_qa_api.py              # Core QA API tests
│   │   ├── test_qa_api_enhancements.py # QA enhancements tests
│   │   ├── test_invoices_api.py
│   │   ├── test_filters_api.py
│   │   ├── test_health_api.py
│   │   └── [other API tests]
│   ├── workflows/                 # End-to-end workflow tests
│   │   ├── test_comprehensive_workflow.py
│   │   ├── test_invoice_upload_workflow.py
│   │   └── test_price_comparison_workflow.py
│   └── database/                   # Database integration tests
│
├── functional/                    # Functional/acceptance tests
│   ├── test_authentication.py
│   ├── test_signin_flow.py
│   ├── test_supplier_authentication.py
│   ├── test_supplier_management.py
│   └── test_user_authentication.py
│
├── fixtures/                      # Shared test data factories
│   ├── invoice_data.py            # Invoice and invoice item factories
│   ├── supplier_data.py           # Supplier and mapping factories
│   └── user_data.py               # User and company factories
│
├── pdf_to_excel_test_files/       # PDF conversion test data
│   ├── bmw/                       # BMW Plumbing test files
│   ├── flowmark/                  # Flow Mark test files
│   ├── ghotam/                    # Gotham test files
│   └── [other supplier test files]
│
├── conftest.py                     # Shared pytest configuration
└── README.md                       # This file
```

## Test Types

### 1. Unit Tests (`unit/`)
- Fast, isolated tests with mocked dependencies
- Test individual functions and methods
- Run frequently during development

**Business Logic Tests (`unit/business_logic/`):**
- `test_invoice_duplicate_detection.py` - Invoice duplicate detection logic (17+ tests)
- `test_reference_number_normalization.py` - Reference number normalization (25+ tests)
- `test_quickbooks_tax_calculations.py` - Tax calculation and distribution (20+ tests)
- `test_account_classification.py` - Account classification rules (25+ tests)
- `test_statement_validation_rules.py` - Statement validation logic (30+ tests)

**Utility Tests (`unit/utils/`):**
- `test_intelligent_qa.py` - QA system utilities (date parsing, synonym expansion, entity extraction)
- `test_auth_handler.py` - Authentication handler tests
- `test_export_utils.py` - Export utility tests
- `test_mapping_validators.py` - Mapping validation tests
- `test_pdf_to_excel_conversion.py` - PDF to Excel conversion tests for all suppliers

### 2. Integration Tests (`integration/`)

**API Integration Tests (`integration/api/`):**
- `test_qa_api.py` - Core QA API endpoint tests (11 tests)
  - ChatbotEngine tests (safe query validation, query processing)
  - ChatbotController tests (query processing, validation)
  - QA Routes tests (endpoint validation)
  - QA Safety tests (SQL injection protection, result limiting)
- `test_qa_api_enhancements.py` - QA system enhancements tests (16 tests)
  - Intent classification tests
  - Conversation context management
  - Conversational response generation
  - Backward compatibility tests
  - New features (greetings, help, session context)
- `test_invoices_api.py` - Invoice API endpoint tests
- `test_filters_api.py` - Filter API endpoint tests
- `test_health_api.py` - Health check endpoint tests
- [Other API integration tests]

**Workflow Tests (`integration/workflows/`):**
- `test_comprehensive_workflow.py` - End-to-end workflow tests
- `test_invoice_upload_workflow.py` - Invoice upload workflow
- `test_price_comparison_workflow.py` - Price comparison workflow

**Database Integration Tests (`integration/database/`):**
- Tests with real database (PostgreSQL via Testcontainers)
- Test multiple components working together
- Run before commits and in CI/CD

### 3. Functional Tests (`functional/`)
- High-level feature testing
- Test complete user workflows
- Run before releases

## Running Tests

### Run All Tests
```bash
pytest
```

### Run Unit Tests Only
```bash
pytest mpi_backend/tests/unit/
```

### Run Business Logic Tests Only
```bash
pytest mpi_backend/tests/unit/business_logic/ -v
```

### Run Specific Test File
```bash
pytest mpi_backend/tests/unit/business_logic/test_invoice_duplicate_detection.py -v
```

### Run Tests by Marker
```bash
# Run only business logic tests
pytest -m business_logic

# Run only integration tests
pytest -m integration

# Run only unit tests
pytest -m unit
```

### Run with Coverage
```bash
pytest --cov=mpi_backend --cov-report=html
# Open htmlcov/index.html to view coverage report
```

### Run Tests and Stop on First Failure
```bash
pytest -x
```

### Run Tests in Parallel (faster)
```bash
pytest -n auto
```

## Test Markers

Available test markers (defined in `pytest.ini`):
- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.functional` - Functional tests
- `@pytest.mark.performance` - Performance tests
- `@pytest.mark.business_logic` - Business logic tests
- `@pytest.mark.slow` - Slow running tests
- `@pytest.mark.requires_db` - Tests requiring database
- `@pytest.mark.requires_external` - Tests requiring external services

## Writing Tests

### Test Naming Convention
```python
def test_<function>_<scenario>_<expected_result>():
    """
    Test description in plain English.
    
    GIVEN initial conditions
    WHEN action is performed
    THEN expected outcome
    """
```

### Test Structure (AAA Pattern)
```python
def test_example():
    # Arrange - Set up test data and dependencies
    input_data = {...}
    expected_output = {...}
    
    # Act - Execute the function under test
    result = function_under_test(input_data)
    
    # Assert - Verify the result
    assert result == expected_output
```

### Using Fixtures
```python
def test_with_fixture(mock_db_session, sample_invoice_items):
    """Test using shared fixtures."""
    controller = InvoiceItemController(mock_db_session)
    result = controller.process(sample_invoice_items)
    assert result is not None
```

### Parametrized Tests
```python
@pytest.mark.parametrize("input_val,expected", [
    ("066617", "66617"),
    ("I-000987", "I-987"),
    ("0000", "0"),
])
def test_normalize(input_val, expected):
    result = normalize_ref_no(input_val)
    assert result == expected
```

## Test Data Factories

Located in `fixtures/`:
- `invoice_data.py` - Invoice and invoice item factories
- `user_data.py` - User and company factories
- `supplier_data.py` - Supplier and mapping factories

### Using Factories
```python
from mpi_backend.tests.fixtures.invoice_data import InvoiceItemFactory

def test_with_factory():
    # Create test invoice item
    item = InvoiceItemFactory.create(
        ref_no="INV-001",
        vendor="Test Vendor",
        amount="1000.00"
    )
    
    # Create multiple items
    items = InvoiceItemFactory.create_multiple(5)
    
    # Use preset scenarios
    existing, new = InvoiceScenarios.exact_duplicate()
```

## Continuous Integration

Tests run automatically on:
- Pull requests
- Commits to main/develop branches
- Nightly builds

### CI Pipeline
1. Unit tests (fast feedback)
2. Integration tests (database validation)
3. Functional tests (feature validation)
4. Coverage report generation

## Best Practices

1. **Keep tests fast** - Unit tests should run in milliseconds
2. **Test one thing** - Each test should verify one behavior
3. **Use meaningful names** - Test names should describe what they test
4. **Don't test implementation details** - Test behavior, not internals
5. **Mock external dependencies** - Unit tests should be isolated
6. **Use factories** - Reuse test data creation logic
7. **Keep tests maintainable** - Clear, simple, and well-organized

## Troubleshooting

### Tests Not Running
- Ensure you're in the project root directory
- Check that pytest is installed: `pip install pytest`
- Verify test file names start with `test_`

### Import Errors
- Ensure project is in Python path
- Check that `__init__.py` files exist in test directories

### Database Connection Issues (Integration Tests)
- Ensure Docker is running (for Testcontainers)
- Check database connection settings
- Verify PostgreSQL container is accessible

### Slow Tests
- Run unit tests only: `pytest mpi_backend/tests/unit/`
- Use parallel execution: `pytest -n auto`
- Check for unintended integration tests in unit test directory

## Coverage Goals

### Current Coverage (as of implementation)
- **Business Logic**: 90%+ ✅
  - Invoice duplicate detection
  - Reference number normalization
  - Tax calculations
  - Account classification
  - Statement validation

### Next Steps
- Controller unit tests: 85%+ target
- Integration tests: 50+ test cases
- API endpoint tests
- Workflow tests

## Recent Test Structure Updates

### QA API Tests Structure

The QA API tests have been restructured to match the current codebase architecture:

#### Import Path Updates
- **Old**: `mpi_backend.utils.database_qa_agent` (non-existent module)
- **New**: 
  - `mpi_backend.database.engine` for database engine
  - `mpi_backend.utils.chatbot.engine` for chatbot components
  - `mpi_backend.utils.chatbot.intelligent_query_processor` for query processing

#### Controller Updates
- **Old**: `QAController` (removed module)
- **New**: `ChatbotController` with multi-agent architecture support

#### Mocking Pattern Updates
- **Old**: Mocking `_get_chatbot_engine` directly
- **New**: Mocking `_get_agent_manager` to support multi-agent architecture:
  ```python
  mock_manager = Mock()
  mock_manager.process_request = AsyncMock(return_value={...})
  
  with patch.object(controller, '_get_agent_manager', return_value=mock_manager):
      result = await controller.process_query("question")
  ```

#### Endpoint Path Updates
- **Old**: `/chatbot/query`
- **New**: `/qa/query` (matches router prefix configuration)

#### Test Organization
- `test_qa_api.py` - Core QA functionality tests (11 tests)
- `test_qa_api_enhancements.py` - Enhanced features tests (16 tests)
- Both files use proper mocking and follow AAA pattern

### Test File Naming Conventions

All test files follow consistent naming:
- Unit tests: `test_<module_name>.py` (e.g., `test_invoice_duplicate_detection.py`)
- Integration tests: `test_<feature>_api.py` (e.g., `test_qa_api.py`)
- Functional tests: `test_<feature>_flow.py` (e.g., `test_signin_flow.py`)

### Test Coverage by Category

- **Unit Tests**: 300+ tests
  - Business Logic: 120+ tests
  - Controllers: 40+ tests
  - Utils: 100+ tests
  - Models: 40+ tests
  
- **Integration Tests**: 200+ tests
  - API Integration: 150+ tests
  - Workflows: 30+ tests
  - Database: 20+ tests
  
- **Functional Tests**: 20+ tests

**Total**: 600+ tests with 80%+ code coverage

## Contributing

When adding new tests:
1. Place in appropriate directory (unit/integration/functional)
2. Use appropriate markers (`@pytest.mark.unit`, `@pytest.mark.integration`, etc.)
3. Follow AAA pattern (Arrange-Act-Assert)
4. Add docstrings explaining test purpose
5. Use fixtures from `fixtures/` directory for test data
6. Update this README if adding new test categories or significant changes
7. Ensure mocks use correct import paths and match current architecture

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Testing Best Practices](https://docs.python-guide.org/writing/tests/)
- [AAA Pattern](https://medium.com/@pjbgf/title-testing-code-ocd-and-the-aaa-pattern-df453975ab80)

