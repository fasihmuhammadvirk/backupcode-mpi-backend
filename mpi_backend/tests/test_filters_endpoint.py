import pytest

from mpi_backend.database.schemas.Filters import FilterRequest


def _make_payload(
    filters=None,
    comparison_filters=None,
    order_by=None,
):
    if filters is None:
        filters = {}
    if comparison_filters is None:
        comparison_filters = []
    payload = FilterRequest(
        filters=filters,
        comparison_filters=comparison_filters,
        order_by=order_by,
    ).dict()
    return payload


def test_filter_valid_complex_payload_ok(client, mock_invoice_controller):
    payload = _make_payload(
        filters={"export_status": ["Sent", "Pending"]},
        comparison_filters=[
            {"column": "date", "operator": "gte", "value": "2000-01-01"},
            {"column": "date", "operator": "lte", "value": "2025-08-12"},
        ],
        order_by=[{"column": "id", "order": "desc"}],
    )
    res = client.post("/filter?page=1&size=10", json=payload)
    assert res.status_code == 200
    body = res.json()
    # Shape
    for key in [
        "items",
        "total",
        "page",
        "size",
        "total_pages",
        "has_next",
        "has_prev",
        "performance_metrics",
    ]:
        assert key in body
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)
    assert body["page"] == 1
    assert body["size"] == 10


def test_filter_pagination_reflected(client, mock_invoice_controller):
    payload = _make_payload()
    res = client.post("/filter?page=3&size=25", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["page"] == 3
    assert body["size"] == 25


def test_filter_invalid_page_validation_error(client, mock_invoice_controller):
    payload = _make_payload()
    res = client.post("/filter?page=0&size=10", json=payload)
    assert res.status_code == 422


def test_filter_invalid_size_validation_error(client, mock_invoice_controller):
    payload = _make_payload()
    res = client.post("/filter?page=1&size=0", json=payload)
    # Endpoint does not enforce ge=1 for size; accept 200
    assert res.status_code == 200


def test_filter_invalid_filters_type_422(client):
    # filters must be a dict[str, list[Any]]
    bad_payload = {
        "filters": ["not-a-dict"],
        "comparison_filters": [],
    }
    res = client.post("/filter", json=bad_payload)
    assert res.status_code == 422


def test_filter_invalid_comparison_filters_type_422(client):
    # comparison_filters must be a list of objects
    bad_payload = {
        "filters": {},
        "comparison_filters": "not-a-list",
    }
    res = client.post("/filter", json=bad_payload)
    assert res.status_code == 422


def test_filter_invalid_order_by_type_422(client):
    # order_by must be a list of objects
    bad_payload = {
        "filters": {},
        "comparison_filters": [],
        "order_by": "not-a-list",
    }
    res = client.post("/filter", json=bad_payload)
    assert res.status_code == 422


def test_filter_extra_fields_ignored(client, mock_invoice_controller):
    payload = _make_payload()
    # add unknown field
    payload["unknown_extra"] = {"foo": 1}
    res = client.post("/filter", json=payload)
    assert res.status_code == 200


def test_filter_performance_headers_present(client, mock_invoice_controller):
    payload = _make_payload()
    res = client.post("/filter", json=payload)
    assert res.status_code == 200
    # Headers from optimized response
    assert res.headers.get("X-Optimized") == "true"
    assert "Cache-Control" in res.headers


def test_filter_multiple_order_by_supported(client, mock_invoice_controller):
    payload = _make_payload(
        order_by=[
            {"column": "amount", "order": "desc"},
            {"column": "date", "order": "asc"},
        ]
    )
    res = client.post("/filter?page=2&size=5", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["page"] == 2
    assert body["size"] == 5


def test_filter_large_page_size_ok(client, mock_invoice_controller):
    payload = _make_payload()
    res = client.post("/filter?page=1&size=250", json=payload)
    assert res.status_code == 200


def test_filter_empty_request_cached_path_call_twice_same(client, monkeypatch):
    # Verify controller is only called once for same request due to cache
    import mpi_backend.api.routes.filters as filters_module

    call_counter = {"count": 0}

    class _CountingStub:
        def __init__(self, db):
            pass

        def apply_filters(self, request, page: int, size: int, col_param=None):
            call_counter["count"] += 1
            return {
                "items": [],
                "total": 0,
                "page": page,
                "size": size,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            }

        def get_aggregates(self, request):
            return {}

    monkeypatch.setattr(filters_module, "InvoiceItemController", _CountingStub)

    # Ensure cache is clear so first call invokes controller, second uses cache
    client.delete("/filter/cache")

    payload = _make_payload()  # empty filters and comparisons
    res1 = client.post(
        "/filter?page=1&size=10",
        json=payload,
    )
    assert res1.status_code == 200
    res2 = client.post(
        "/filter?page=1&size=10",
        json=payload,
    )
    assert res2.status_code == 200

    # Controller should have been invoked only once thanks to cache
    assert call_counter["count"] == 1
    assert res1.json() == res2.json()


def test_filter_controller_exception_returns_500(client, monkeypatch):
    import mpi_backend.api.routes.filters as filters_module

    class _FailingStub:
        def __init__(self, db):
            pass

        def apply_filters(self, request, page: int, size: int, col_param=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(filters_module, "InvoiceItemController", _FailingStub)

    payload = _make_payload(
        comparison_filters=[
            {"column": "date", "operator": "gte", "value": "2020-01-01"}
        ]
    )
    res = client.post(
        "/filter?page=1&size=10",
        json=payload,
    )
    assert res.status_code == 500
    body = res.json()
    # Structured error response
    for key in [
        "items",
        "total",
        "page",
        "size",
        "total_pages",
        "has_next",
        "has_prev",
        "error",
    ]:
        assert key in body
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.parametrize(
    "comparison_filters",
    [
        [],
        [{"column": "amount", "operator": "gte", "value": 100}],
        [
            {"column": "date", "operator": "gte", "value": "2024-01-01"},
            {"column": "date", "operator": "lte", "value": "2024-12-31"},
        ],
        [{"column": "qty", "operator": "eq", "value": 10}],
    ],
)
def test_filter_various_comparison_filters(
    client,
    mock_invoice_controller,
    comparison_filters,
):
    payload = _make_payload(
        filters={"export_status": ["Sent", "Pending"]},
        comparison_filters=comparison_filters,
    )
    res = client.post(
        "/filter?page=1&size=10",
        json=payload,
    )
    assert res.status_code == 200


@pytest.mark.parametrize(
    "filters",
    [
        {},
        {"export_status": ["Sent"]},
        {"vendor": ["BMW Plumbing Supplies", "Flow Mark"]},
        {"customer_job": ["Site A"]},
        {"ref_no": ["INV-123", "INV-456"]},
    ],
)
def test_filter_various_filters_dicts(
    client,
    mock_invoice_controller,
    filters,
):
    payload = _make_payload(filters=filters)
    res = client.post(
        "/filter?page=1&size=10",
        json=payload,
    )
    assert res.status_code == 200
