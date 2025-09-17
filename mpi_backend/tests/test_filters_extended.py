from unittest.mock import patch
from mpi_backend.database.schemas.Filters import FilterRequest


def test_filter_by_column_missing_param(client):
    res = client.post("/filter/by-column")
    assert res.status_code == 200
    assert res.json() == {"data": "Invalid Column Name Specified"}


def test_filter_by_column_ok(client, mock_invoice_controller):
    res = client.post("/filter/by-column?column_name=vendor", json={})
    assert res.status_code == 200


def test_filter_column_mapping(client):
    res = client.get("/filter/column-mapping")
    assert res.status_code == 200
    body = res.json()
    assert "filename" in body and "date" in body


def test_filter_get_locations_ok(client):
    res = client.get("/filter/get-locations")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_filter_main_success_basic(client, mock_invoice_controller):
    payload = FilterRequest(filters={}, comparison_filters=[]).dict()
    res = client.post("/filter", json=payload)
    assert res.status_code == 200
    assert "performance_metrics" in res.json()


def test_filter_get_aggregates_ok(client, mock_invoice_controller):
    payload = FilterRequest(filters={}, comparison_filters=[]).dict()
    res = client.post("/filter/get_aggregates", json=payload)
    assert res.status_code == 200
    body = res.json()
    for key in [
        "total_amount",
        "total_quantity",
        "average_cost",
        "item_count",
        "invoice_count",
        "supplier_count",
    ]:
        assert key in body


def test_filter_cache_stats_and_clear(client):
    stats = client.get("/filter/cache-stats")
    assert stats.status_code == 200
    cleared = client.delete("/filter/cache")
    assert cleared.status_code == 200
    assert cleared.json()["message"].lower().startswith("cache cleared")


def test_price_difference_empty_ok(client, mock_invoice_controller):
    # Controller returns empty items so endpoint returns []
    payload = FilterRequest(filters={}, comparison_filters=[]).dict()
    res = client.post("/filter/price-difference?page=1&size=5", json=payload)
    # Could be [] (200) or [] without wrapper
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_price_history_validation_errors(client):
    # Missing item_number
    res = client.post(
        "/filter/price-history",
        json={"vendor": "BMW"},
    )
    # Pydantic validation may raise 422 before endpoint logic
    assert res.status_code in (400, 422)
    # Missing vendor
    res = client.post(
        "/filter/price-history",
        json={"item_number": "ABC"},
    )
    assert res.status_code in (400, 422)


def test_price_history_ok_empty_list(client, mock_invoice_controller):
    res = client.post(
        "/filter/price-history",
        json={
            "item_number": "ABC",
            "vendor": "BMW",
            "description": "Test item",
        },
    )
    assert res.status_code == 200
    assert res.json() == []


def test_download_price_history_ok(
    client, mock_invoice_controller, mock_s3, mock_save_final_data
):
    with patch(
        "mpi_backend.api.routes.filters.export_price_history_to_excel",
        return_value="/tmp/x.xlsx",
    ):
        res = client.post(
            "/filter/download-price-history",
            json={
                "item_number": "ABC",
                "vendor": "BMW",
                "description": "Test item",
            },
        )
        assert res.status_code == 200
        assert isinstance(res.json(), str)
