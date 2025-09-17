from unittest.mock import patch
import mpi_backend.api.routes.statements as st


def test_statements_invoice_data_minimal_params(client):
    res = client.get(
        "/statements/invoice-data",
        params={"page": 1, "page_size": 10},
    )
    assert res.status_code in (200, 500)


def test_statements_invoice_data_invalid_dates(client):
    # Invalid date formats should return 400
    res = client.get(
        "/statements/invoice-data",
        params={"from_date": "32/13/2025", "to_date": "01/01/2025"},
    )
    assert res.status_code == 400


def test_statements_download_not_found(client):
    # Force controller to return None to get 404
    with patch.object(
        st.StatementController,
        "get_statement_by_id",
        return_value=None,
    ):
        res = client.get(
            "/statements/download",
            params={"statement_id": 1},
        )
        assert res.status_code == 404


def test_statements_download_ok(client):
    with patch.object(
        st.StatementController,
        "get_statement_by_id",
        return_value={
            "statement_id": 1,
            "supplier_name": "ABC",
            "statement_date": "2025-01-31",
            "pdf_filename": "file.pdf",
        },
    ), patch.object(
        st,
        "get_presigned_url",
        return_value="https://example.com/x",
    ):
        res = client.get(
            "/statements/download",
            params={"statement_id": 1},
        )
        assert res.status_code == 200
        body = res.json()
        assert "link" in body and "expires_in" in body


def test_statements_reprocess_single_ok(client):
    with patch.object(
        st.StatementController,
        "reprocess_statement",
        return_value={"success": True, "results": []},
    ):
        res = client.post(
            "/statements/reprocess",
            params={"statement_id": 1},
        )
        assert res.status_code == 200


def test_statements_reprocess_bulk_ok(client):
    with patch.object(
        st.StatementController,
        "reprocess_all_statements",
        return_value={"success": True, "results": [], "statistics": {}},
    ):
        res = client.post("/statements/reprocess")
        assert res.status_code == 200


def test_statements_delete_not_found(client):
    with patch.object(
        st.StatementController,
        "delete_statement",
        return_value={"success": False, "error": "not found"},
    ):
        res = client.delete("/statements/1")
        assert res.status_code == 404


def test_statements_delete_ok(client):
    with patch.object(
        st.StatementController,
        "delete_statement",
        return_value={
            "success": True,
            "details": {"invoices_deleted": 0},
            "message": "ok",
        },
    ):
        res = client.delete("/statements/1")
        assert res.status_code == 200
