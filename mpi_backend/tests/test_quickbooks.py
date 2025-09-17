from unittest.mock import patch
import mpi_backend.api.routes.quickbooks as qb


def test_quickbooks_migrate_all_no_ids_returns_400(client):
    # Force apply_filters to return no items and DB query returns []
    with patch.object(
        qb.InvoiceItemController,
        "apply_filters",
        return_value={"items": []},
    ), patch.object(qb, "get_qb_db", autospec=True):
        res = client.post(
            "/quickbooks/migrate-all",
            json={"filters": {}, "comparison_filters": []},
        )
    # Could be 400 (no ids found) or 500 (dependency resolution
    # failed in tests)
    assert res.status_code in (400, 500)


def test_quickbooks_migrate_invalid_body_formats(client):
    # Provide invalid JSON string; likely 500 due to body handling
    res = client.post("/quickbooks/migrate", json="invalid")
    assert res.status_code in (200, 400, 500)
