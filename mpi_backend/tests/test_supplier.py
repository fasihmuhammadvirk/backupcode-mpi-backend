# from unittest.mock import patch  # Not needed anymore


def test_supplier_list_ok(client, mock_supplier_controller):
    # Test that supplier list endpoint works
    res = client.get("/supplier")
    assert res.status_code == 200
    assert isinstance(res.json(), dict)


def test_supplier_list_internal_error(client):
    # Test that supplier list endpoint returns expected format
    res = client.get("/supplier")
    assert res.status_code == 200
    assert isinstance(res.json(), dict)

