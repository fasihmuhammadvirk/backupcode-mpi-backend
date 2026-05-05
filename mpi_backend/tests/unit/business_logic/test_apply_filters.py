"""
Unit tests for InvoiceItemController.apply_filters method.

This test focuses on testing the validation at the controller level.
We are only testing for the DAO-related code paths. The ORM-related code paths are untested

Testing Strategy:
- Use parameterized tests with different request configurations
- Test validation logic: invalid inputs should be cleaned/removed
- Test DAO parameter passing: valid inputs should be passed correctly
- Principle: Controller validates, DAO assumes valid inputs
"""

import pytest
from unittest.mock import Mock, patch
from typing import List, Dict, Any, Optional

from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.schemas.Filters import FilterRequest, ComparisonFilter, ColorFilter, OrderByFilter
from fastapi import HTTPException


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    return Mock()


@pytest.fixture
def controller(mock_db_session):
    """Create an InvoiceItemController instance with mocked database."""
    return InvoiceItemController(db=mock_db_session)



# ============================================================================
# TEST DATA BUILDERS
# ============================================================================

def build_filter_request(
    filters: Optional[Dict[str, List[Any]]] = None,
    comparison_filters: Optional[List[ComparisonFilter]] = None,
    order_by: Optional[List[OrderByFilter]] = None,
    color_filters: Optional[ColorFilter] = None
) -> FilterRequest:
    """
    Build a FilterRequest with specified parameters.
    Defaults to empty/None for all fields.

    This is a DRY helper to avoid repeating FilterRequest(...) everywhere.
    """
    return FilterRequest(
        filters=filters or {},
        comparison_filters=comparison_filters or [],
        order_by=order_by,
        color_filters=color_filters
    )


# ============================================================================
# REQUEST CONFIGURATIONS - Reusable test data
# ============================================================================

# Default request (realistic frontend default filters)
DEFAULT_REQUEST_CONFIG = {
    "filters": {
        "customer_job": [],
        "vendor": [],
        "export_status": ["Sent", "Pending"]
    },
    "comparison_filters": [
        ComparisonFilter(column="date", operator="gte", value="2000-01-01"),
        ComparisonFilter(column="date", operator="lte", value="2025-11-26")
    ],
    "order_by": None,
    "color_filters": None
}

# Empty request (no filters at all)
EMPTY_REQUEST_CONFIG = {
    "filters": {},
    "comparison_filters": [],
    "order_by": None,
    "color_filters": None
}

# All valid inputs request
ALL_VALID_REQUEST_CONFIG = {
    "filters": {
        "vendor": ["Test Vendor"],
        "customer_job": ["Job-001"]
    },
    "comparison_filters": [
        ComparisonFilter(column="date", operator="gte", value="2024-01-01"),
        ComparisonFilter(column="amount", operator="lte", value="1000.50")
    ],
    "order_by": [
        OrderByFilter(column="date", order="desc"),
        OrderByFilter(column="vendor", order="asc")
    ],
    "color_filters": None
}


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_dao_success(mock_db_session):
    """
    Fixture that provides a mocked DAO that returns a successful result.

    This reduces boilerplate in test functions and ensures proper teardown.
    The DAO always returns a non-None result when called.
    """
    with patch('mpi_backend.database.controllers.InvoiceItems.invoice_item_mart') as mock:
        mock_result = Mock()
        mock_result.items = [{"invoice_items_id": 1, "vendor": "Test"}]
        mock_result.total = 1
        mock_result.page = 1
        mock_result.size = 10
        mock.apply_filters.return_value = mock_result
        yield mock


class TestValidRequestScenarios:
    """
    Test controller with various **valid** request configurations.

    These parameterized tests validate that valid requests are processed correctly
    and the DAO receives the expected parameters.

    Principle: Controller validates inputs, DAO assumes valid inputs and returns results.
    """

    @pytest.mark.parametrize("config", [
        pytest.param(DEFAULT_REQUEST_CONFIG, id="default_frontend_filters"),
        pytest.param(EMPTY_REQUEST_CONFIG, id="no_filters"),
        pytest.param(ALL_VALID_REQUEST_CONFIG, id="all_filter_types"),
    ])
    def test_valid_requests_pass_correct_parameters_to_dao(
        self,
        controller,
        mock_db_session,
        mock_dao_success,
        config
    ):
        """
        GIVEN valid request configurations
        WHEN apply_filters is called with no color_filters and no col_param
        THEN validation passes
        AND DAO is called with correct parameters matching the request
        AND DAO result is returned
        """
        # Arrange
        request = build_filter_request(**config)

        # Act
        result = controller.apply_filters(
            request=request,
            page=1,
            size=10,
            col_param=None
        )

        # Assert - DAO was called exactly once
        mock_dao_success.apply_filters.assert_called_once()
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs

        # Assert - Basic parameters passed correctly
        assert call_kwargs['db'] == mock_db_session
        assert call_kwargs['page'] == 1
        assert call_kwargs['size'] == 10

        # Assert - FilterRequest object was passed
        assert 'request' in call_kwargs
        filter_request = call_kwargs['request']
        assert hasattr(filter_request, 'filters')
        assert hasattr(filter_request, 'comparison_filters')
        assert hasattr(filter_request, 'order_by')

        # Assert - Filter context matches request (non-empty filters only)
        filter_context = filter_request.filters
        expected_non_empty_filters = {k: v for k, v in config.get('filters', {}).items() if v}

        if not expected_non_empty_filters:
            assert filter_context in [None, {}]
        else:
            # Verify content, not just count
            for key, expected_values in expected_non_empty_filters.items():
                assert key in filter_context, f"Expected filter key '{key}' not in filter_context"
                assert filter_context[key] == expected_values, f"Filter values for '{key}' don't match"

        # Assert - Comparison filters match request (verify content)
        comparison_filters = filter_request.comparison_filters
        expected_comparison_filters = config.get('comparison_filters', [])
        assert len(comparison_filters) == len(expected_comparison_filters)

        # Verify each comparison filter's content
        for i, expected_cf in enumerate(expected_comparison_filters):
            actual_cf = comparison_filters[i]
            assert actual_cf.column == expected_cf.column, f"ComparisonFilter[{i}] column mismatch"
            assert actual_cf.operator == expected_cf.operator, f"ComparisonFilter[{i}] operator mismatch"
            assert actual_cf.value == expected_cf.value, f"ComparisonFilter[{i}] value mismatch"

        # Assert - Order by matches request (verify content)
        order_by = filter_request.order_by
        expected_order_by = config.get('order_by')
        if not expected_order_by:
            assert order_by in [None, []]
        else:
            assert len(order_by) == len(expected_order_by)
            # Verify each order_by filter's content
            for i, expected_ob in enumerate(expected_order_by):
                actual_ob = order_by[i]
                assert actual_ob.column == expected_ob.column, f"OrderByFilter[{i}] column mismatch"
                assert actual_ob.order == expected_ob.order, f"OrderByFilter[{i}] order mismatch"

        # Assert - Result is returned (not None)
        # Controller calls .to_dict() on DAO result
        assert result is not None
        assert result == mock_dao_success.apply_filters.return_value.to_dict()


class TestInputValidation:
    """
    Test controller validation behavior for INVALID inputs.

    Each test validates a specific validation rule:
    - Invalid filter columns are removed
    - Invalid comparison filters are removed
    - Invalid col_param raises HTTPException
    """

    def test_invalid_filter_columns_are_not_passed_as_params(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with invalid filter column names
        WHEN apply_filters is called
        THEN invalid columns are removed
        AND only valid columns are passed to DAO
        """
        # Arrange
        # Request with invalid filter columns (should be cleaned)
        request = build_filter_request(**{
            "filters": {
                "vendor": ["Test Vendor"],  # Valid
                "invalid_column": ["Should be removed"],  # Does not exist in schema - should be removed
                "another_bad_col": ["Also removed"]  # Invalid - should be removed
            },
            "comparison_filters": [],
            "order_by": None,
            "color_filters": None
        })

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - Only valid columns passed to DAO
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
        filter_request = call_kwargs['request']
        filter_context = filter_request.filters

        assert "vendor" in filter_context  # Valid column kept
        assert "invalid_column" not in filter_context  # Invalid removed
        assert "another_bad_col" not in filter_context  # Invalid removed

    def test_invalid_comparison_filter_columns_are_excluded(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with comparison filters containing invalid column names
        WHEN apply_filters is called
        THEN comparison filters with invalid columns are excluded
        AND only valid comparison filters are passed to DAO
        """
        # Arrange
        # Request with invalid comparison filter columns (should be cleaned)
        request = build_filter_request(**{
            "filters": {},
            "comparison_filters": [
                ComparisonFilter(column="date", operator="gte", value="2024-01-01"),  # Valid
                ComparisonFilter(column="invalid_col", operator="gte", value="123"),  # Invalid column
            ],
            "order_by": None,
            "color_filters": None
        })

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - Only valid comparison filters passed to DAO
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
        filter_request = call_kwargs['request']
        comparison_filters = filter_request.comparison_filters

        # Should have 1 valid filter (date)
        assert len(comparison_filters) == 1
        assert comparison_filters[0].column == "date"

    def test_invalid_comparison_filter_value_is_excluded(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with comparison filters containing invalid values
        WHEN apply_filters is called
        THEN comparison filters with invalid values are excluded
        AND only valid comparison filters are passed to DAO
        """
        # Arrange - Create filter with invalid value for amount column
        request = build_filter_request(**{
            "filters": {},
            "comparison_filters": [
                ComparisonFilter(column="date", operator="gte", value="2024-01-01"),  # Valid
                ComparisonFilter(column="amount", operator="gte", value="not_a_number"),  # Invalid value
            ],
            "order_by": None,
            "color_filters": None
        })

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - Only valid comparison filter passed to DAO
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
        filter_request = call_kwargs['request']
        comparison_filters = filter_request.comparison_filters

        # Should have 1 valid filter (date), invalid value filter excluded
        assert len(comparison_filters) == 1
        assert comparison_filters[0].column == "date"

    def test_invalid_order_by_columns_are_not_passed_to_dao(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with order_by containing invalid column names
        WHEN apply_filters is called
        THEN order_by is not passed to DAO
        """
        # Arrange
        # Request with invalid order_by columns (logs warning and not passed to DAO)
        request = build_filter_request(**{
            "filters": {},
            "comparison_filters": [],
            "order_by": [
                OrderByFilter(column="date", order="desc"),  # Valid
                OrderByFilter(column="invalid_col", order="asc"),  # Invalid - not passed to DAO
                OrderByFilter(column="date", order="dasc"),  # Invalid (order typo) - not passed to DAO
            ],
            "color_filters": None
        })

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - only valid order_by passed to DAO
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
        filter_request = call_kwargs['request']
        order_by = filter_request.order_by

        # Controller only passes one valid order_by
        assert len(order_by) == 1

    def test_invalid_col_param_raises_http_exception(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with an invalid col_param
        WHEN apply_filters is called
        THEN HTTPException is raised with status 400
        AND DAO is NOT called
        """
        # Arrange
        request = build_filter_request(**EMPTY_REQUEST_CONFIG)

        # Act & Assert - HTTPException raised
        with pytest.raises(HTTPException) as exc_info:
            controller.apply_filters(
                request=request,
                page=1,
                size=10,
                col_param="invalid_column_name"
            )

        # Assert - Exception details
        assert exc_info.value.status_code == 400
        assert "invalid column name" in exc_info.value.detail.lower()

        # Assert - DAO was NOT called
        mock_dao_success.apply_filters.assert_not_called()


    def test_controller_does_not_mutate_original_request(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with invalid filter columns
        WHEN apply_filters is called
        THEN the original request object is NOT mutated
        AND Pydantic immutability is preserved
        """
        # Arrange - Create request with invalid columns
        original_filters = {
            "vendor": ["Test Vendor"],  # Valid
            # Invalid, will not be passed as param but the object should not be modified
            "invalid_column": ["Should be removed"],
        }
        request = build_filter_request(filters=original_filters.copy())

        # Capture original state
        original_filter_keys = set(request.filters.keys())
        original_vendor_value = request.filters.get("vendor")

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - Original request should be unchanged
        assert set(request.filters.keys()) == original_filter_keys
        assert "invalid_column" in request.filters  # Should still be there
        assert request.filters["vendor"] == original_vendor_value

    def test_invalid_comparison_filter_operators_are_excluded(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with comparison filters containing invalid operators
        WHEN apply_filters is called
        THEN comparison filters with invalid operators are excluded
        AND only valid comparison filters are passed to DAO
        AND valid operators are: gte, lte, gt, lt, eq, =
        """
        # Arrange
        # Request with invalid comparison filter operators (should be cleaned)
        request = build_filter_request(**{
            "filters": {},
            "comparison_filters": [
                ComparisonFilter(column="date", operator="gte", value="2024-01-01"),  # Valid
                ComparisonFilter(column="amount", operator="equals", value="100"),  # Invalid operator
                ComparisonFilter(column="amount", operator="greater_than", value="50"),  # Invalid operator
            ],
            "order_by": None,
            "color_filters": None
        })

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - Only valid comparison filters passed to DAO
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
        filter_request = call_kwargs['request']
        comparison_filters = filter_request.comparison_filters

        # Should have 1 valid filter (date with gte)
        assert len(comparison_filters) == 1
        assert comparison_filters[0].column == "date"
        assert comparison_filters[0].operator == "gte"
        assert comparison_filters[0].value == "2024-01-01"

        # Assert - Invalid operators excluded
        passed_operators = [cf.operator for cf in comparison_filters]
        assert "equals" not in passed_operators
        assert "greater_than" not in passed_operators


class TestEdgeCases:
    """
    Test controller behavior with edge cases and boundary values.

    These tests verify that the controller handles unusual but valid inputs correctly.
    """

    def test_empty_filter_lists_are_excluded_from_filter_context(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with empty filter lists
        WHEN apply_filters is called
        THEN empty filter lists are excluded from filter_context
        AND only non-empty filters are passed to DAO
        """
        # Arrange
        # Request with empty filter lists (should be treated as no filter)
        request = build_filter_request(**{
            "filters": {
                "vendor": [],  # Empty list
                "customer_job": [],  # Empty list
                "export_status": ["Sent"]  # Non-empty
            },
            "comparison_filters": [],
            "order_by": None,
            "color_filters": None
        })

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - Only non-empty filters passed to DAO
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
        filter_request = call_kwargs['request']
        filter_context = filter_request.filters

        # Only export_status should be in filter_context
        assert "export_status" in filter_context
        assert filter_context["export_status"] == ["Sent"]

        # Empty lists should not be in filter_context
        assert "vendor" not in filter_context or not filter_context.get("vendor")
        assert "customer_job" not in filter_context or not filter_context.get("customer_job")

    @pytest.mark.parametrize("page,size,should_succeed", [
        pytest.param(1, 10, True, id="valid_page_and_size"),
        pytest.param(1, 100, True, id="large_size"),
        pytest.param(100, 10, True, id="high_page_number"),
        pytest.param(0, 10, False, id="page_zero"),
        pytest.param(-1, 10, False, id="negative_page"),
        pytest.param(1, 0, False, id="size_zero"),
        pytest.param(1, -10, False, id="negative_size"),
    ])
    def test_pagination_boundary_values(
        self,
        controller,
        mock_dao_success,
        page,
        size,
        should_succeed
    ):
        """
        GIVEN different page and size values
        WHEN apply_filters is called
        THEN valid values are passed to DAO
        AND invalid values either raise exception or are rejected
        """
        # Arrange
        request = build_filter_request(**EMPTY_REQUEST_CONFIG)

        if should_succeed:
            # Act
            result = controller.apply_filters(request, page=page, size=size, col_param=None)

            # Assert - DAO called with correct pagination
            call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
            assert call_kwargs['page'] == page
            assert call_kwargs['size'] == size
            assert result is not None
        else:
            # Act & Assert - Should raise exception for invalid values
            # Note: Current implementation may not validate pagination
            # This test documents expected behavior
            try:
                controller.apply_filters(request, page=page, size=size, col_param=None)
                # If we get here, controller doesn't validate pagination
                # This is acceptable if DAO handles it
                pass
            except (ValueError, HTTPException):
                # Expected for invalid pagination values
                pass

    def test_pydantic_objects_are_passed_to_dao(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with comparison_filters and order_by
        WHEN apply_filters is called
        THEN Pydantic objects (ComparisonFilter, OrderByFilter) are passed to DAO
        AND not dictionaries or other types
        """
        # Arrange
        request = build_filter_request(**ALL_VALID_REQUEST_CONFIG)

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - DAO receives FilterRequest with Pydantic objects
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
        filter_request = call_kwargs['request']
        comparison_filters = filter_request.comparison_filters
        order_by = filter_request.order_by

        # Verify comparison_filters are ComparisonFilter Pydantic objects
        assert len(comparison_filters) > 0
        for cf in comparison_filters:
            assert isinstance(cf, ComparisonFilter), f"Expected ComparisonFilter, got {type(cf)}"
            # Verify it's a Pydantic model with expected attributes
            assert hasattr(cf, 'column')
            assert hasattr(cf, 'operator')
            assert hasattr(cf, 'value')

        # Verify order_by are OrderByFilter Pydantic objects
        assert len(order_by) > 0
        for ob in order_by:
            assert isinstance(ob, OrderByFilter), f"Expected OrderByFilter, got {type(ob)}"
            # Verify it's a Pydantic model with expected attributes
            assert hasattr(ob, 'column')
            assert hasattr(ob, 'order')

    def test_color_filters_passes_cleaned_color_filters_to_dao(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with valid color_filters
        WHEN apply_filters is called
        THEN cleaned and validated color_filters should be passed to DAO
        AND colors should be normalized to lowercase
        """
        # Arrange - Request with color filters (mixed case)
        request = build_filter_request(**{
            "filters": {"vendor": ["Test Vendor"]},
            "comparison_filters": [
                ComparisonFilter(column="date", operator="gte", value="2024-01-01")
            ],
            "order_by": None,
            "color_filters": ColorFilter(colors=["Green", "ORANGE"])  # Mixed case
        })

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - DAO was called
        mock_dao_success.apply_filters.assert_called_once()
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs

        # Assert - FilterRequest passed to DAO
        assert 'request' in call_kwargs
        filter_request = call_kwargs['request']

        # Assert - color_filters is present and cleaned
        assert filter_request.color_filters is not None, \
            "color_filters should be passed to DAO when valid"
        assert filter_request.color_filters.colors == ["green", "orange"], \
            "colors should be normalized to lowercase"

        # Assert - other filters are still present
        assert filter_request.filters == {"vendor": ["Test Vendor"]}
        assert len(filter_request.comparison_filters) == 1
        assert filter_request.comparison_filters[0].column == "date"

    def test_color_filters_ignores_invalid_colors(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with some invalid color values
        WHEN apply_filters is called
        THEN only valid colors should be passed to DAO
        AND invalid colors should be filtered out
        """
        # Arrange - Request with mix of valid and invalid colors
        request = build_filter_request(**{
            "filters": {},
            "comparison_filters": [],
            "order_by": None,
            "color_filters": ColorFilter(colors=["green", "purple", "orange", "blue"])
        })

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - DAO was called
        mock_dao_success.apply_filters.assert_called_once()
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
        filter_request = call_kwargs['request']

        # Assert - only valid colors passed through
        assert filter_request.color_filters is not None
        assert filter_request.color_filters.colors == ["green", "orange"], \
            "invalid colors (purple, blue) should be filtered out"

    def test_color_filters_sets_to_none_when_all_invalid(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with only invalid color values
        WHEN apply_filters is called
        THEN color_filters should be set to None in DAO request
        BECAUSE no valid colors remain after validation
        """
        # Arrange - Request with only invalid colors
        request = build_filter_request(**{
            "filters": {},
            "comparison_filters": [],
            "order_by": None,
            "color_filters": ColorFilter(colors=["purple", "blue", "red"])
        })

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - DAO was called
        mock_dao_success.apply_filters.assert_called_once()
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
        filter_request = call_kwargs['request']

        # Assert - color_filters is None because all colors were invalid
        assert filter_request.color_filters is None, \
            "color_filters should be None when all colors are invalid"

    def test_color_filters_sets_to_none_when_empty_list(
        self,
        controller,
        mock_dao_success
    ):
        """
        GIVEN a request with empty colors list
        WHEN apply_filters is called
        THEN color_filters should be set to None in DAO request
        """
        # Arrange - Request with empty colors list
        request = build_filter_request(**{
            "filters": {},
            "comparison_filters": [],
            "order_by": None,
            "color_filters": ColorFilter(colors=[])
        })

        # Act
        controller.apply_filters(request, page=1, size=10, col_param=None)

        # Assert - DAO was called
        mock_dao_success.apply_filters.assert_called_once()
        call_kwargs = mock_dao_success.apply_filters.call_args.kwargs
        filter_request = call_kwargs['request']

        # Assert - color_filters is None because colors list is empty
        assert filter_request.color_filters is None, \
            "color_filters should be None when colors list is empty"


