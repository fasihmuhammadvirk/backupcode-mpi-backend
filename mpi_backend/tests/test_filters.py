from mpi_backend.database.schemas.Filters import FilterRequest


def test_filter_empty_request(client, mock_invoice_controller):
    payload = FilterRequest(filters={}, comparison_filters=[]).dict()
    res = client.post("/filter", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_by_column_missing_param(client, mock_invoice_controller):
    res = client.post("/filter/by-column")
    assert res.status_code in (200, 422)


def test_get_locations_ok(client):
    res = client.get("/filter/get-locations")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
