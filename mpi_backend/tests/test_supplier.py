from unittest.mock import patch


def test_supplier_list_ok(client, mock_supplier_controller):
    # Stub controller to return a minimal list
    with patch(
        "mpi_backend.api.routes.supplier.SupplierController.get_all_suppliers",
        return_value=[],
    ):
        res = client.get("/supplier")
        assert res.status_code == 200
        assert isinstance(res.json(), dict)


def test_supplier_list_internal_error(client):
    # Force the call to raise to hit 500 path
    with patch(
        "mpi_backend.api.routes.supplier.SupplierController.get_all_suppliers",
        side_effect=RuntimeError("db down"),
    ):
        res = client.get("/supplier")
        assert res.status_code == 500
        assert "Failed to fetch suppliers" in res.text

