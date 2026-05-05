
import pytest
from unittest.mock import patch, Mock
from mpi_backend.database.models.User import User
from uuid import uuid4

def test_supplier_list_ok_with_auth(client, override_get_current_user):
    """
    Tests that the supplier list endpoint returns a 200 OK status when an
    authenticated user makes a request.
    """
    # Create a mock user with a standard role
    user = User(
        id=uuid4(),
        username='test_user',
        role='standard',
        company_id=1,
        is_active=True
    )

    # Use the override_get_current_user fixture to simulate an authenticated request
    with override_get_current_user(user):
        # Mock the supplier controller to return test data
        with patch('mpi_backend.api.routes.supplier.SupplierController') as mock_controller:
            mock_instance = Mock()
            mock_instance.get_all_suppliers.return_value = [
                Mock(id=1, supplier_name="Test Supplier 1"),
                Mock(id=2, supplier_name="Test Supplier 2")
            ]
            mock_controller.return_value = mock_instance

            # Test that supplier list endpoint works
            res = client.get("/supplier")
            assert res.status_code == 200
            assert res.json() == {
                "1": "Test Supplier 1",
                "2": "Test Supplier 2"
            }
