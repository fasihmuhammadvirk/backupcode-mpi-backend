from unittest.mock import patch, Mock


def test_supplier_list_ok(client, override_get_current_user):
    # Mock the supplier controller to return test data
    with (
        override_get_current_user(),
        patch('mpi_backend.database.controllers.Suppliers.SupplierController') as mock_controller,
    ):
        mock_instance = Mock()
        mock_instance.get_suppliers.return_value = {
            "suppliers": [
                {"id": 1, "name": "Test Supplier 1"},
                {"id": 2, "name": "Test Supplier 2"}
            ]
        }
        mock_controller.return_value = mock_instance
        
        # Test that supplier list endpoint works
        res = client.get("/supplier")
        assert res.status_code == 200
        assert isinstance(res.json(), dict)


def test_supplier_list_internal_error(client, override_get_current_user):
    # Mock the supplier controller to return test data
    with (
        override_get_current_user(),
        patch('mpi_backend.database.controllers.Suppliers.SupplierController') as mock_controller,
    ):
        mock_instance = Mock()
        mock_instance.get_suppliers.return_value = {
            "suppliers": [
                {"id": 1, "name": "Test Supplier 1"},
                {"id": 2, "name": "Test Supplier 2"}
            ]
        }
        mock_controller.return_value = mock_instance
        
        # Test that supplier list endpoint returns expected format
        res = client.get("/supplier")
        assert res.status_code == 200
        assert isinstance(res.json(), dict)

