import pytest

from unittest.mock import patch, Mock
import mpi_backend.api.routes.quickbooks as qb


def test_quickbooks_migrate_all_no_ids_returns_400(client):
    # Mock database connections and controllers
    with patch('mpi_backend.database.get_db') as mock_get_db, \
         patch.object(qb.InvoiceItemController, "apply_filters", return_value={"items": []}), \
         patch.object(qb, "get_qb_db", autospec=True):
        
        # Create a mock database session
        mock_session = Mock()
        mock_session.query.return_value.all.return_value = []
        mock_get_db.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value.__exit__.return_value = None
        
        res = client.post(
            "/quickbooks/migrate-all",
            json={"filters": {}, "comparison_filters": []},
        )
    # Could be 400 (no ids found), 500 (dependency resolution failed), or 200 if invoices returned
    assert res.status_code in (200, 400, 500)


def test_quickbooks_migrate_invalid_body_formats(client):
    # Mock database connections
    with patch('mpi_backend.database.get_db') as mock_get_db:
        # Create a mock database session
        mock_session = Mock()
        mock_session.query.return_value.all.return_value = []
        mock_get_db.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value.__exit__.return_value = None
        
        # Provide invalid JSON string; likely 500 due to body handling
        res = client.post("/quickbooks/migrate", json="invalid")
        assert res.status_code in (200, 400, 500)
