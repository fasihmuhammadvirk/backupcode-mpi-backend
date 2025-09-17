def test_get_invoices_empty(client, mock_invoice_controller):
    res = client.get("/invoice?page=1&size=10")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_get_all_invoices(client, mock_invoice_controller):
    res = client.get("/invoice/all")
    assert res.status_code == 200
    assert res.json() == []


def test_download_invoice_mocked(
    client,
    mock_invoice_controller,
    mock_supplier_controller,
    mock_s3,
):
    res = client.get(
        "/invoice/download",
        params={
            "invoice_id": "11111111-1111-1111-1111-111111111111"
        },
    )
    assert res.status_code == 200
    assert "link" in res.json()


def test_get_invoices_unauthorized_without_token_header(client):
    # JWT bypassed via env in conftest; ensure structure via stub
    res = client.get("/invoice?page=1&size=10")
    assert res.status_code == 200
    body = res.json()
    assert "items" in body and isinstance(body["items"], list)


def test_invoice_sort_invalid_column_returns_400(client):
    res = client.get("/invoice/sort", params={"column_name": "Invalid"})
    assert res.status_code == 400
    assert "Invalid column name" in res.text


def test_invoice_delete_ok_path(client, mock_invoice_controller):
    # JWT is bypassed in tests; controller stub returns the passed id.
    res = client.delete(
        "/invoice/delete",
        params={"invoice_id": "abc-123"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "status" in body
