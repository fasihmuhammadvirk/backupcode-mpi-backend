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
        params={"invoice_id": "11111111-1111-1111-1111-111111111111"},
    )
    assert res.status_code == 200
    assert "link" in res.json()

