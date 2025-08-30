"""
Test configuration for MPI Backend
Sets up test environment variables and configurations
"""

import os
from unittest.mock import MagicMock

# Set test environment variables
os.environ["PYTEST_CURRENT_TEST"] = "1"
os.environ["TESTING_MODE"] = "1"

# Add test-specific configurations
TEST_CONFIG = {
    "database_mock": True,
    "skip_real_connections": True,
    "use_test_data": True
}


def setup_test_environment():
    """Setup test environment variables and configurations"""
    print("Setting up test environment...")
    
    # Set environment variables for testing
    os.environ["PYTEST_CURRENT_TEST"] = "1"
    os.environ["TESTING_MODE"] = "1"
    
    print("Test environment setup complete")
    return True


def create_mock_db_session():
    """Create a mock database session for testing"""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result
    mock_session.commit = MagicMock()
    mock_session.rollback = MagicMock()
    mock_session.close = MagicMock()
    return mock_session
