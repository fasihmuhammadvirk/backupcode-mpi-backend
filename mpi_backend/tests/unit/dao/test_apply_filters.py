"""
Unit tests for invoice_item_mart.apply_filters function.

Testing Strategy:
- DAO assumes inputs are valid (validated by controller)
- Test SQL query construction correctness
- Test parameter binding and SQL injection safety
- Mock database execution to verify SQL without running queries
- Use unittest.mock to capture SQL text and parameters

Key Focus:
- WHERE clause construction from FilterRequest.filters
- WHERE clause construction from FilterRequest.comparison_filters
- ORDER BY clause construction from FilterRequest.order_by
- Pagination (LIMIT/OFFSET) calculation
- Parameter binding for SQL injection safety
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from typing import Dict, List, Optional, Any

from mpi_backend.database.dao import invoice_item_mart
from mpi_backend.database.schemas.Filters import ComparisonFilter, OrderByFilter, FilterRequest, ColorFilter


# ============================================================================
# TEST DATA BUILDERS
# ============================================================================

def build_comparison_filter(column: str, operator: str, value: Any) -> ComparisonFilter:
    """Build a ComparisonFilter Pydantic object."""
    return ComparisonFilter(column=column, operator=operator, value=value)


def build_order_by_filter(column: str, order: str) -> OrderByFilter:
    """Build an OrderByFilter Pydantic object."""
    return OrderByFilter(column=column, order=order)


def build_filter_request(
    filters: Optional[Dict[str, List[Any]]] = None,
    comparison_filters: Optional[List[ComparisonFilter]] = None,
    order_by: Optional[List[OrderByFilter]] = None,
    color_filters: Optional[ColorFilter] = None,
    page: int = 1,
    size: int = 50
) -> tuple[FilterRequest, int, int]:
    """
    Build a FilterRequest Pydantic object and return pagination params.

    Returns:
        Tuple of (FilterRequest, page, size) for easy unpacking in tests
    """
    request = FilterRequest(
        filters=filters or {},
        comparison_filters=comparison_filters or [],
        order_by=order_by,
        color_filters=color_filters
    )
    return request, page, size


# ============================================================================
# REQUEST CONFIGURATIONS
# ============================================================================

# Empty request (no filters)
EMPTY_REQUEST, EMPTY_PAGE, EMPTY_SIZE = build_filter_request()

# Comparison filters only
COMPARISON_REQUEST, COMP_PAGE, COMP_SIZE = build_filter_request(
    comparison_filters=[
        build_comparison_filter("date", "gte", "2024-01-01"),
        build_comparison_filter("date", "lte", "2024-12-31")
    ]
)

# Order by filters
ORDER_BY_REQUEST, ORDER_PAGE, ORDER_SIZE = build_filter_request(
    order_by=[
        build_order_by_filter("date", "desc"),
        build_order_by_filter("vendor", "asc")
    ]
)

# Combined filters
COMBINED_REQUEST, COMBINED_PAGE, COMBINED_SIZE = build_filter_request(
    filters={"vendor": ["Vendor A", "Vendor B"]},
    comparison_filters=[
        build_comparison_filter("date", "gte", "2024-01-01")
    ],
    order_by=[build_order_by_filter("date", "desc")],
    page=2,
    size=25
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_db_session():
    """Create a mock database session that captures SQL queries."""
    mock_session = Mock()

    # Mock execute to capture SQL text and params
    mock_result = MagicMock()
    mock_result.scalar.return_value = 100  # Total count
    mock_result.fetchall.return_value = []  # Data rows
    mock_result.keys.return_value = ['invoice_items_id', 'vendor', 'date']

    mock_session.execute.return_value = mock_result

    return mock_session


@pytest.fixture
def mock_mart_table_exists():
    """Mock check_mart_table_exists to return True - patch where it's imported."""
    with patch('mpi_backend.database.dao.invoice_item_mart.apply_filters.check_mart_table_exists') as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def mock_allowed_columns():
    """Mock _get_allowed_columns to return test columns."""
    with patch('mpi_backend.database.dao.invoice_item_mart.utils._get_allowed_columns') as mock:
        mock.return_value = {
            'invoice_items_id', 'vendor', 'customer_job', 'date',
            'amount', 'description', 'export_status', 'date_added'
        }
        yield mock


# ============================================================================
# TESTS: SQL Query Construction
# ============================================================================

class TestSQLQueryConstruction:
    """
    Test that SQL queries are constructed correctly from input parameters.

    Focus: Verify SQL structure, WHERE clauses, ORDER BY, and pagination.
    """

    def test_empty_filters_generates_valid_sql(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN no filters provided in FilterRequest
        WHEN apply_filters is called
        THEN SQL should have WHERE 1=1 and default ORDER BY
        """
        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=EMPTY_REQUEST,
            page=EMPTY_PAGE,
            size=EMPTY_SIZE
        )

        # Assert - DAO was called twice (count + data query)
        assert mock_db_session.execute.call_count == 2

        # Get the SQL queries
        count_call = mock_db_session.execute.call_args_list[0]
        data_call = mock_db_session.execute.call_args_list[1]

        count_sql = str(count_call[0][0])
        data_sql = str(data_call[0][0])

        # Assert - Count query has WHERE 1=1
        assert "WHERE 1=1" in count_sql
        assert "FROM analytics.mart__invoice_items" in count_sql

        # Assert - Data query has WHERE 1=1 and default ORDER BY
        assert "WHERE 1=1" in data_sql
        assert "ORDER BY" in data_sql
        assert "LIMIT" in data_sql
        assert "OFFSET" in data_sql

    def test_filter_context_single_item_list_generates_in_clause(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest.filters with single-item list
        WHEN apply_filters is called
        THEN SQL should have IN clause with one bound parameter
        """
        # Arrange - Simple filter (single column, single-item list)
        request, page, size = build_filter_request(
            filters={"vendor": ["Test Vendor"]}
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query SQL and params
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])
        data_params = data_call[0][1]

        # Assert - SQL has vendor IN clause (even for single item)
        assert "vendor IN (" in data_sql
        assert ":filter_vendor_0" in data_sql

        # Assert - Parameter is bound
        assert 'filter_vendor_0' in data_params
        assert data_params['filter_vendor_0'] == "Test Vendor"

    def test_filter_context_list_values_generates_in_clause(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest.filters with list of values
        WHEN apply_filters is called
        THEN SQL should have IN clause with multiple bound parameters
        """
        # Arrange - Filter with list values
        request, page, size = build_filter_request(
            filters={"vendor": ["Vendor A", "Vendor B", "Vendor C"]}
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query SQL and params
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])
        data_params = data_call[0][1]

        # Assert - SQL has vendor IN (...)
        assert "vendor IN (" in data_sql
        assert ":filter_vendor_0" in data_sql
        assert ":filter_vendor_1" in data_sql
        assert ":filter_vendor_2" in data_sql

        # Assert - All parameters are bound
        assert data_params['filter_vendor_0'] == "Vendor A"
        assert data_params['filter_vendor_1'] == "Vendor B"
        assert data_params['filter_vendor_2'] == "Vendor C"

    def test_comparison_filters_generate_date_range_where(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest.comparison_filters with gte and lte
        WHEN apply_filters is called
        THEN SQL should have date >= and date <= clauses
        """
        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=COMPARISON_REQUEST,
            page=COMP_PAGE,
            size=COMP_SIZE
        )

        # Assert - Get data query SQL and params
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])
        data_params = data_call[0][1]

        # Assert - SQL has date comparison clauses
        assert "date >= :date_0" in data_sql
        assert "date <= :date_1" in data_sql

        # Assert - Parameters are bound
        assert data_params['date_0'] == "2024-01-01"
        assert data_params['date_1'] == "2024-12-31"

    def test_order_by_generates_correct_order_clause(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest.order_by filters
        WHEN apply_filters is called
        THEN SQL should have ORDER BY with specified columns and directions
        """
        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=ORDER_BY_REQUEST,
            page=ORDER_PAGE,
            size=ORDER_SIZE
        )

        # Assert - Get data query SQL
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])

        # Assert - SQL has ORDER BY clause with both columns (case-insensitive)
        data_sql_lower = data_sql.lower()
        assert "order by date desc" in data_sql_lower and "vendor asc" in data_sql_lower

    def test_pagination_calculates_correct_offset(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN page=2 and size=25
        WHEN apply_filters is called
        THEN SQL should have LIMIT 25 OFFSET 25
        """
        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=COMBINED_REQUEST,
            page=COMBINED_PAGE,
            size=COMBINED_SIZE
        )

        # Assert - Get data query params
        data_call = mock_db_session.execute.call_args_list[1]
        data_params = data_call[0][1]

        # Assert - Pagination parameters correct
        assert data_params['limit'] == 25
        assert data_params['offset'] == 25  # (page 2 - 1) * size 25


# ============================================================================
# TESTS: Parameter Binding and SQL Injection Safety
# ============================================================================

class TestParameterBinding:
    """
    Test that all values are bound as parameters, not concatenated into SQL.

    Focus: SQL injection safety through proper parameter binding.
    """

    def test_filter_values_are_bound_not_concatenated(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest.filters with special characters
        WHEN apply_filters is called
        THEN values should be bound as parameters, not in SQL string
        """
        # Arrange - Use potentially dangerous SQL injection string (wrapped in list)
        request, page, size = build_filter_request(
            filters={"vendor": ["'; DROP TABLE invoices; --"]}
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])
        data_params = data_call[0][1]

        # Assert - SQL doesn't contain the dangerous string
        assert "DROP TABLE" not in data_sql

        # Assert - Value is passed as parameter (in IN clause)
        assert 'filter_vendor_0' in data_params
        assert data_params['filter_vendor_0'] == "'; DROP TABLE invoices; --"

    def test_comparison_filter_values_are_bound(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest.comparison_filters with values
        WHEN apply_filters is called
        THEN date values should be bound as parameters
        """
        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=COMPARISON_REQUEST,
            page=COMP_PAGE,
            size=COMP_SIZE
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])
        data_params = data_call[0][1]

        # Assert - SQL uses parameter placeholders
        assert ":date_0" in data_sql
        assert ":date_1" in data_sql

        # Assert - Actual dates not in SQL string
        assert "2024-01-01" not in data_sql
        assert "2024-12-31" not in data_sql

        # Assert - Values bound as parameters
        assert data_params['date_0'] == "2024-01-01"
        assert data_params['date_1'] == "2024-12-31"


# ============================================================================
# TESTS: Combined Filters
# ============================================================================

class TestCombinedFilters:
    """
    Test complex scenarios with multiple filter types combined.
    """

    def test_all_filter_types_combined_generate_correct_sql(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest with filters, comparison_filters, order_by, and pagination
        WHEN apply_filters is called
        THEN SQL should combine all filters with AND
        """
        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=COMBINED_REQUEST,
            page=COMBINED_PAGE,
            size=COMBINED_SIZE
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])
        data_params = data_call[0][1]

        # Assert - SQL has all filter types
        assert "vendor IN (" in data_sql  # request.filters
        assert "date >= :date_0" in data_sql  # request.comparison_filters
        # Case-insensitive check for ORDER BY clause
        assert "ORDER BY date" in data_sql and "desc" in data_sql.lower()  # request.order_by
        assert "LIMIT" in data_sql  # pagination

        # Assert - All parameters bound
        assert 'filter_vendor_0' in data_params
        assert 'filter_vendor_1' in data_params
        assert 'date_0' in data_params
        assert 'limit' in data_params
        assert 'offset' in data_params


# ============================================================================
# TESTS: Edge Cases and Error Handling
# ============================================================================

class TestEdgeCases:
    """
    Test edge cases and error conditions.
    """

    def test_mart_table_not_exists_returns_none(
        self,
        mock_db_session,
        mock_allowed_columns
    ):
        """
        GIVEN mart table doesn't exist
        WHEN apply_filters is called
        THEN should return None for fallback
        """
        # Arrange - Mock table doesn't exist
        with patch('mpi_backend.database.dao.invoice_item_mart.apply_filters.check_mart_table_exists') as mock:
            mock.return_value = False

            # Act
            result = invoice_item_mart.apply_filters(
                db=mock_db_session,
                request=EMPTY_REQUEST,
                page=EMPTY_PAGE,
                size=EMPTY_SIZE
            )

        # Assert - Returns None
        assert result is None

    def test_empty_filter_list_is_skipped(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest.filters with empty list
        WHEN apply_filters is called
        THEN empty list should not generate WHERE clause
        """
        # Arrange - Empty list in filters
        request, page, size = build_filter_request(
            filters={"vendor": []}
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])

        # Assert - No vendor filter in SQL
        assert "vendor IN" not in data_sql
        assert "WHERE 1=1" in data_sql

    def test_invalid_column_raises_error_returns_none(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest.filters with invalid column
        WHEN apply_filters is called
        THEN should catch ValueError and return None for fallback
        """
        # Arrange - Invalid column not in allowed_columns
        request, page, size = build_filter_request(
            filters={"invalid_column": ["value"]}
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Returns None for fallback
        assert result is None

    def test_database_error_returns_none(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN database execution raises exception
        WHEN apply_filters is called
        THEN should catch exception and return None for fallback
        """
        # Arrange - Mock execute to raise exception
        mock_db_session.execute.side_effect = Exception("Database error")

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=EMPTY_REQUEST,
            page=EMPTY_PAGE,
            size=EMPTY_SIZE
        )

        # Assert - Returns None
        assert result is None


# ============================================================================
# TESTS: Return Value Structure
# ============================================================================

class TestReturnValue:
    """
    Test that return value structure is correct.
    """

    def test_successful_query_returns_dao_result(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN successful query execution with FilterRequest
        WHEN apply_filters is called
        THEN should return DaoFilteredItemsResult with correct fields
        """
        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=EMPTY_REQUEST,
            page=EMPTY_PAGE,
            size=EMPTY_SIZE
        )

        # Assert - Result is not None
        assert result is not None

        # Assert - Result has expected fields
        assert hasattr(result, 'items')
        assert hasattr(result, 'total')
        assert hasattr(result, 'page')
        assert hasattr(result, 'size')
        assert hasattr(result, 'source')

        # Assert - Values match input
        assert result.page == 1
        assert result.size == 50
        assert result.total == 100  # Mocked value
        assert result.source == "mart_invoice_items_filtered"

    @pytest.mark.xfail(reason="wip")
    def test_color_filter_green_generates_join_and_where_clause(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest with color_filters for green items
        WHEN apply_filters is called
        THEN SQL should JOIN with mart__price_increases
        AND WHERE clause should include percentage_increase > 10
        """
        # Arrange - Color filter for green (>10% increase)
        request, page, size = build_filter_request(
            color_filters=ColorFilter(colors=["green"])
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0]).lower()

        # Assert - SQL has JOIN with price_increases table
        assert "join" in data_sql and "mart__price_increases" in data_sql, \
               "Color filter should JOIN with mart__price_increases table"

        # Assert - SQL has percentage_increase filter for green
        assert "percentage_increase > 10" in data_sql or \
               "percentage_increase > :color" in data_sql, \
               "Green color filter should add percentage_increase > 10 to WHERE clause"

    @pytest.mark.xfail(reason="wip")
    def test_color_filter_orange_generates_join_and_between_clause(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest with color_filters for orange items
        WHEN apply_filters is called
        THEN SQL should JOIN with mart__price_increases
        AND WHERE clause should include percentage_increase BETWEEN 4 AND 10
        """
        # Arrange - Color filter for orange (4-10% increase)
        request, page, size = build_filter_request(
            color_filters=ColorFilter(colors=["orange"])
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0]).lower()

        # Assert - SQL has JOIN with price_increases table
        assert "join" in data_sql and "mart__price_increases" in data_sql, \
               "Color filter should JOIN with mart__price_increases table"

        # Assert - SQL has percentage_increase filter for orange
        assert ("between" in data_sql or
                (">=" in data_sql and "<=" in data_sql)), \
               "Orange color filter should add percentage_increase BETWEEN 4 AND 10 to WHERE clause"

    @pytest.mark.xfail(reason="wip")
    def test_color_filter_both_generates_join_and_where_clause(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest with color_filters for 'both' (green OR orange)
        WHEN apply_filters is called
        THEN SQL should JOIN with mart__price_increases
        AND WHERE clause should include percentage_increase > 4
        """
        # Arrange - Color filter for both (>4% increase)
        request, page, size = build_filter_request(
            color_filters=ColorFilter(colors=["both"])
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0]).lower()

        # Assert - SQL has JOIN with price_increases table
        assert "join" in data_sql and "mart__price_increases" in data_sql, \
               "Color filter should JOIN with mart__price_increases table"

        # Assert - SQL has percentage_increase filter for both
        assert "percentage_increase > 4" in data_sql or \
               "percentage_increase > :color" in data_sql, \
               "'Both' color filter should add percentage_increase > 4 to WHERE clause"

    @pytest.mark.xfail(reason="wip")
    def test_color_filter_multiple_colors_generates_join_and_or_condition(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest with multiple color filters (green AND orange)
        WHEN apply_filters is called
        THEN SQL should JOIN with mart__price_increases
        AND WHERE clause should include OR conditions for each color range
        OR simplified to > 4 (since green >10 OR orange 4-10 = >4)
        """
        # Arrange - Multiple color filters
        request, page, size = build_filter_request(
            color_filters=ColorFilter(colors=["green", "orange"])
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0]).lower()

        # Assert - SQL has JOIN with price_increases table
        assert "join" in data_sql and "mart__price_increases" in data_sql, \
               "Color filter should JOIN with mart__price_increases table"

        # Assert - SQL should have OR condition (or simplified to > 4 since that covers both)
        # Green (>10) OR Orange (4-10) can be simplified to >4
        assert ("percentage_increase > 4" in data_sql or
                "or" in data_sql), \
               "Multiple color filters should generate OR conditions or simplified threshold"

    @pytest.mark.xfail(reason="wip")
    def test_color_filter_combined_with_other_filters(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest with color_filters AND regular filters
        WHEN apply_filters is called
        THEN SQL should JOIN with mart__price_increases
        AND combine all filters with AND
        """
        # Arrange - Color filter + regular filters
        request, page, size = build_filter_request(
            filters={"vendor": ["Test Vendor"]},
            comparison_filters=[
                build_comparison_filter("date", "gte", "2024-01-01")
            ],
            color_filters=ColorFilter(colors=["green"])
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])
        data_sql_lower = data_sql.lower()
        data_params = data_call[0][1]

        # Assert - SQL has JOIN with price_increases table
        assert "join" in data_sql_lower and "mart__price_increases" in data_sql_lower, \
               "Color filter should JOIN with mart__price_increases table"

        # Assert - SQL has all filter types
        assert "vendor IN (" in data_sql  # regular filter
        assert "date >= :date_0" in data_sql  # comparison filter
        assert ("percentage_increase >" in data_sql_lower), \
               "Color filter should be combined with other filters"

        # Assert - All parameters bound
        assert 'filter_vendor_0' in data_params
        assert 'date_0' in data_params


class TestPriceIncreaseAlwaysIncluded:
    """
    Tests that verify percentage_increase is ALWAYS included in results,
    regardless of whether color_filters are present.
    """

    def test_percentage_increase_always_joined_no_filters(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest with NO filters (empty request)
        WHEN apply_filters is called
        THEN SQL should ALWAYS JOIN with mart__price_increases
        AND SELECT should include percentage_increase column
        """
        # Arrange - Empty request
        request, page, size = build_filter_request()

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])
        data_sql_lower = data_sql.lower()

        # Assert - SQL ALWAYS has LEFT JOIN with price_increases
        assert "join" in data_sql_lower and "mart__price_increases" in data_sql_lower, \
               "Should ALWAYS JOIN with mart__price_increases for percentage_increase data"

        # Assert - SQL selects percentage_increase column
        # The SELECT should include pi.percentage_increase in the CTE or final SELECT
        assert "percentage_increase" in data_sql_lower, \
               "Should SELECT percentage_increase column"

    def test_percentage_increase_always_joined_with_regular_filters(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN FilterRequest with regular filters (NO color_filters)
        WHEN apply_filters is called
        THEN SQL should ALWAYS JOIN with mart__price_increases
        AND SELECT should include percentage_increase column
        """
        # Arrange - Regular filters only (no color_filters)
        request, page, size = build_filter_request(
            filters={"vendor": ["Test Vendor"]},
            comparison_filters=[
                build_comparison_filter("date", "gte", "2024-01-01")
            ]
        )

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Get data query
        data_call = mock_db_session.execute.call_args_list[1]
        data_sql = str(data_call[0][0])
        data_sql_lower = data_sql.lower()

        # Assert - SQL ALWAYS has LEFT JOIN with price_increases
        assert "join" in data_sql_lower and "mart__price_increases" in data_sql_lower, \
               "Should ALWAYS JOIN with mart__price_increases even without color_filters"

        # Assert - SQL selects percentage_increase column
        assert "percentage_increase" in data_sql_lower, \
               "Should SELECT percentage_increase column"

    def test_percentage_increase_included_in_results(
        self,
        mock_db_session,
        mock_mart_table_exists,
        mock_allowed_columns
    ):
        """
        GIVEN apply_filters returns results
        WHEN results are returned
        THEN each item should have 'percentage_increase' field as a float
        """
        # Arrange - Empty request
        request, page, size = build_filter_request()

        # Mock database to return a row with percentage_increase
        # Create a mock result that works for both count and data queries
        mock_result = Mock()
        mock_result.scalar.return_value = 1  # total count for first call
        mock_result.fetchall.return_value = [
            (1, "Item A", "Vendor A", 12.5),  # id, item, vendor, percentage_increase
        ]
        mock_result.keys.return_value = ['invoice_items_id', 'item', 'vendor', 'percentage_increase']

        # Both execute calls will return the same mock (it has both scalar and fetchall)
        mock_db_session.execute.return_value = mock_result

        # Act
        result = invoice_item_mart.apply_filters(
            db=mock_db_session,
            request=request,
            page=page,
            size=size
        )

        # Assert - Result should have percentage_increase
        assert result is not None
        assert len(result.items) == 1

        # Assert - percentage_increase should be a float
        item = result.items[0]
        assert 'percentage_increase' in item, \
               "Each item should have percentage_increase field"

        # Check that it's a float (raw value from database)
        percentage_val = item['percentage_increase']
        assert isinstance(percentage_val, (float, int, type(None))), \
               "percentage_increase should be a numeric type or None"

        # Verify the actual value
        assert percentage_val == 12.5, \
               "percentage_increase should be the raw float value from database"
