"""
Unit test fixtures and configuration.

This module provides fixtures for unit tests with mocked dependencies.
Unit tests should be fast, isolated, and not require external resources.
"""

import pytest
from unittest.mock import MagicMock, Mock
from datetime import datetime, date
from uuid import uuid4
from sqlalchemy.orm import Session


@pytest.fixture
def mock_db_session():
    """
    Mock database session for unit tests.
    
    Returns a MagicMock with spec=Session to ensure proper method signatures.
    """
    mock_session = MagicMock(spec=Session)
    mock_session.query = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = MagicMock()
    mock_session.rollback = MagicMock()
    mock_session.flush = MagicMock()
    mock_session.refresh = MagicMock()
    mock_session.close = MagicMock()
    return mock_session


@pytest.fixture
def mock_query_result():
    """
    Factory fixture for creating mock query results.
    
    Usage:
        result = mock_query_result([item1, item2, item3])
    """
    def _create_result(items=None):
        mock_result = MagicMock()
        if items is None:
            items = []
        mock_result.all.return_value = items
        mock_result.first.return_value = items[0] if items else None
        mock_result.count.return_value = len(items)
        return mock_result
    return _create_result


@pytest.fixture
def sample_date():
    """Sample date for testing."""
    return date(2024, 7, 15)


@pytest.fixture
def sample_datetime():
    """Sample datetime for testing."""
    return datetime(2024, 7, 15, 10, 30, 0)


@pytest.fixture
def sample_uuid():
    """Sample UUID for testing."""
    return uuid4()


# Mark all tests in this directory as unit tests
pytestmark = pytest.mark.unit

