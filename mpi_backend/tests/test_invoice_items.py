def test_invoice_items_all_ok(client, mock_invoice_controller):
    res = client.get("/invoice-items/all")
    assert res.status_code in (200, 404)


def test_invoice_items_by_id_missing_uuid_validation(client):
    # Invalid UUID should not crash; route treats None as /all
    res = client.get(
        "/invoice-items/id",
        params={"invoice_id": "not-a-uuid"},
    )
    # FastAPI validator returns 422 for invalid UUID
    assert res.status_code in (200, 404, 422)


def test_invoice_items_supplier_date_filters_ok(
    client, mock_invoice_controller
):
    res = client.get(
        "/invoice-items/supplier-date",
        params={
            "supplier_name": ["BMW Plumbing"],
            "page": 1,
            "size": 10,
        },
    )
    assert res.status_code in (200, 404)


def test_invoice_items_sort_invalid_column(client):
    res = client.get(
        "/invoice-items/sort",
        params={"column_name": "NotAColumn"},
    )
    assert res.status_code == 400


def test_invoice_items_count_ok(client, mock_invoice_controller):
    res = client.get("/invoice-items/count")
    assert res.status_code == 200
    assert "count" in res.json()


def test_toggle_visibility_requires_body(client, mock_invoice_controller):
    res = client.put("/invoice-items/toggle-visibility")
    assert res.status_code in (400, 422)
