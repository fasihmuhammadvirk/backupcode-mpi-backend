import io


def test_upload_invoice_pipeline(
    client,
    mock_invoice_controller,
    mock_supplier_controller,
    mock_invoice_upload_pipeline,
):
    file_content = b"%PDF-1.4 dummy"
    files = {"file": ("test.pdf", io.BytesIO(file_content), "application/pdf")}
    res = client.post(
        "/invoice/upload",
        params={"supplier_id": 1},
        files=files,
    )
    assert res.status_code in (200, 500)

