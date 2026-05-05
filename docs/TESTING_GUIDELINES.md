# Testing Guidelines

## Test Structure

Follow Given-When-Then pattern in docstrings:

```python
def test_example(self, controller, mock):
    """
    GIVEN initial context and preconditions
    WHEN action or trigger occurs
    THEN expected outcome happens
    """
    # Arrange
    request = build_test_data()

    # Act
    result = controller.method(request)

    # Assert
    assert result == expected
```

## Keep Tests DRY

If you are reusing some setup, use constants and builder functions.
For example: configuration dictionaries and builder functions:

```python
# Module-level configs
DEFAULT_CONFIG = {
    "filters": {"status": ["active"]},
    "comparison_filters": [ComparisonFilter(column="date", operator="gte", value="2024-01-01")]
}

# Builder helper
def build_request(**config):
    return Request(
        filters=config.get('filters', {}),
        comparison_filters=config.get('comparison_filters', [])
    )
```

## Reuse Fixtures

Create fixtures for common mocks to reduce boilerplate (they could live in the respective test's `conftest.py`):

```python
@pytest.fixture
def mock_dao_success():
    with patch('module.dao') as mock:
        mock.method.return_value = success_result
        yield mock
```

## Testing Strategy

**Use hybrid approach:**
- Parameterized tests for valid request scenarios
- Separate tests for each validation rule

**Organize tests by purpose:**
- `TestValidScenarios` - Happy path tests
- `TestInputValidation` - Validation and error handling
- `TestEdgeCases` - Boundary values and unusual inputs

## Assertions

**Verify content, not just counts:**

Bad:
```python
assert len(filters) == 2
```

Good:
```python
assert len(filters) == 2
for i, expected in enumerate(expected_filters):
    assert filters[i].column == expected.column
    assert filters[i].value == expected.value
```

**Derive expected values from config:**

```python
expected_count = len(config.get('comparison_filters', []))
assert len(actual_filters) == expected_count
```

## Controller vs DAO Testing

**Controller responsibilities:**
- Validate inputs
- Clean invalid data
- Pass validated Pydantic objects to DAO

**DAO responsibilities:**
- Assume inputs are valid
- Execute queries
- Return results

**Test accordingly:**
- Controller tests verify validation and cleaning
- Controller tests verify DAO receives valid Pydantic objects
- Mock DAO in controller tests

## What to Test

**Test behavior through public APIs, not implementation details:**
- Test the entry point function with scenarios that exercise internal logic
- Avoid testing private/internal helper functions directly
- If an internal function is complex enough to need its own tests, extract it into a separate module with a public API

This keeps tests resilient to refactoring - they only break when actual behavior changes.

**Critical scenarios:**
- Request objects are not mutated (Pydantic immutability)
- Invalid data is excluded before DAO call
- Valid operators/columns/values are enforced
- Pydantic objects are passed, not dicts
- Empty lists and None values are handled

**Edge cases:**
- Empty filter lists
- Boundary values (page=0, size=-1)
- Mixed valid/invalid data
- Special characters in values

## Test Naming

Use descriptive names that explain the scenario:

```python
def test_invalid_filter_columns_are_removed_from_request()
def test_controller_does_not_mutate_original_request()
def test_empty_filter_lists_are_excluded_from_filter_context()
```

## Code Principles

Keep code simple, reusable, maintainable, self-documenting, and error-prone resistant:

- Use existing variables instead of creating new ones
- Derive values from single source of truth (config)
- Don't duplicate data that can be computed
- Make tests readable without comments
- Fail fast with clear error messages
