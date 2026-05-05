"""
End-to-end tests for the invoice void / restore flow.

Covers:
  1. POST /invoice/void-by-key   – void an invoice
  2. POST /invoice/restore-by-key – restore a voided invoice
  3. ORM model and Pydantic schema validation
  4. Filter DAO live-join logic (exclude / include voided)
  5. Round-trip via TestClient against the real FastAPI app with mocked DB
"""

import pytest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VOID_URL = "/invoice/void-by-key"
RESTORE_URL = "/invoice/restore-by-key"

SAMPLE_KEY = {
    "ref_no": "INV-TEST-001",
    "date": "2025-06-15",
    "vendor": "Test Plumbing Supplies",
}


def _make_user(email="tester@example.com", role="admin"):
    from mpi_backend.database.models.User import User

    return User(
        id=uuid4(),
        username="tester",
        email=email,
        role=role,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# 1. POST /invoice/void-by-key
# ---------------------------------------------------------------------------


class TestVoidByKeyEndpoint:

    def test_void_returns_200_with_status(
        self, client, override_get_current_user
    ):
        user = _make_user()
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                res = client.post(VOID_URL, json=SAMPLE_KEY)
                assert res.status_code == 200
                assert res.json()["status"] == "voided"
            finally:
                app.dependency_overrides.pop(get_db, None)

    def test_void_with_reason(self, client, override_get_current_user):
        user = _make_user()
        payload = {**SAMPLE_KEY, "reason": "Duplicate entry"}
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                res = client.post(VOID_URL, json=payload)
                assert res.status_code == 200
                assert res.json()["status"] == "voided"
            finally:
                app.dependency_overrides.pop(get_db, None)

    def test_void_executes_upsert_sql(self, client, override_get_current_user):
        """The endpoint must execute an INSERT … ON CONFLICT against invoice_voided."""
        user = _make_user()
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client.post(VOID_URL, json=SAMPLE_KEY)

                executed_sql = mock_db.execute.call_args_list[0][0][0].text
                assert "INSERT INTO public.invoice_voided" in executed_sql
                assert "ON CONFLICT" in executed_sql
                mock_db.commit.assert_called_once()
            finally:
                app.dependency_overrides.pop(get_db, None)

    def test_void_requires_ref_no(self, client, override_get_current_user):
        user = _make_user()
        with override_get_current_user(user):
            res = client.post(VOID_URL, json={"date": "2025-06-15", "vendor": "V"})
            assert res.status_code == 422

    def test_void_requires_date(self, client, override_get_current_user):
        user = _make_user()
        with override_get_current_user(user):
            res = client.post(VOID_URL, json={"ref_no": "X", "vendor": "V"})
            assert res.status_code == 422

    def test_void_requires_vendor(self, client, override_get_current_user):
        user = _make_user()
        with override_get_current_user(user):
            res = client.post(VOID_URL, json={"ref_no": "X", "date": "2025-06-15"})
            assert res.status_code == 422

    def test_void_rolls_back_on_db_error(self, client, override_get_current_user):
        user = _make_user()
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            mock_db.execute.side_effect = Exception("connection lost")
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                res = client.post(VOID_URL, json=SAMPLE_KEY)
                assert res.status_code == 500
                mock_db.rollback.assert_called_once()
            finally:
                app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 2. POST /invoice/restore-by-key
# ---------------------------------------------------------------------------


class TestRestoreByKeyEndpoint:

    def test_restore_returns_200(self, client, override_get_current_user):
        user = _make_user()
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            mock_result = MagicMock()
            mock_result.rowcount = 1
            mock_db.execute.return_value = mock_result
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                res = client.post(RESTORE_URL, json=SAMPLE_KEY)
                assert res.status_code == 200
                assert res.json()["status"] == "restored"
            finally:
                app.dependency_overrides.pop(get_db, None)

    def test_restore_executes_delete_sql(self, client, override_get_current_user):
        """The endpoint must execute a DELETE FROM invoice_voided."""
        user = _make_user()
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            mock_result = MagicMock()
            mock_result.rowcount = 1
            mock_db.execute.return_value = mock_result
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                client.post(RESTORE_URL, json=SAMPLE_KEY)

                executed_sql = mock_db.execute.call_args_list[0][0][0].text
                assert "DELETE FROM public.invoice_voided" in executed_sql
                mock_db.commit.assert_called_once()
            finally:
                app.dependency_overrides.pop(get_db, None)

    def test_restore_not_found_returns_404(self, client, override_get_current_user):
        user = _make_user()
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            mock_result = MagicMock()
            mock_result.rowcount = 0
            mock_db.execute.return_value = mock_result
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                res = client.post(RESTORE_URL, json=SAMPLE_KEY)
                assert res.status_code == 404
                assert "No void record" in res.json()["detail"]
            finally:
                app.dependency_overrides.pop(get_db, None)

    def test_restore_requires_all_key_fields(self, client, override_get_current_user):
        user = _make_user()
        with override_get_current_user(user):
            res = client.post(RESTORE_URL, json={"ref_no": "X"})
            assert res.status_code == 422

    def test_restore_rolls_back_on_db_error(self, client, override_get_current_user):
        user = _make_user()
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            mock_db.execute.side_effect = Exception("timeout")
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                res = client.post(RESTORE_URL, json=SAMPLE_KEY)
                assert res.status_code == 500
                mock_db.rollback.assert_called_once()
            finally:
                app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 3. ORM Model
# ---------------------------------------------------------------------------


class TestInvoiceVoidModel:

    def test_table_name(self):
        from mpi_backend.database.models.InvoiceVoid import InvoiceVoid

        assert InvoiceVoid.__tablename__ == "invoice_voided"

    def test_primary_key_columns(self):
        from mpi_backend.database.models.InvoiceVoid import InvoiceVoid

        pk_cols = [c.name for c in InvoiceVoid.__table__.columns if c.primary_key]
        assert set(pk_cols) == {"ref_no", "date", "vendor"}

    def test_has_all_required_columns(self):
        from mpi_backend.database.models.InvoiceVoid import InvoiceVoid

        col_names = {c.name for c in InvoiceVoid.__table__.columns}
        assert col_names == {
            "ref_no", "date", "vendor",
            "invoice_voided_at", "invoice_voided_by", "void_reason",
        }

    def test_voided_at_not_nullable(self):
        from mpi_backend.database.models.InvoiceVoid import InvoiceVoid

        col = InvoiceVoid.__table__.c.invoice_voided_at
        assert col.nullable is False


class TestInvoiceItemMartVoidColumn:

    def test_mart_has_voided_at(self):
        from mpi_backend.database.models.InvoiceItemMart import InvoiceItemMart

        col_names = {c.name for c in InvoiceItemMart.__table__.columns}
        assert "invoice_voided_at" in col_names

    def test_mart_voided_at_is_nullable(self):
        from mpi_backend.database.models.InvoiceItemMart import InvoiceItemMart

        col = InvoiceItemMart.__table__.c.invoice_voided_at
        assert col.nullable is True


# ---------------------------------------------------------------------------
# 4. Pydantic Schemas
# ---------------------------------------------------------------------------


class TestPydanticSchemas:

    def test_void_request_valid(self):
        from mpi_backend.database.schemas.InvoiceVoid import VoidByKeyRequest

        req = VoidByKeyRequest(ref_no="R1", date=date(2025, 1, 1), vendor="V1")
        assert req.ref_no == "R1"
        assert req.reason is None

    def test_void_request_with_reason(self):
        from mpi_backend.database.schemas.InvoiceVoid import VoidByKeyRequest

        req = VoidByKeyRequest(ref_no="R1", date=date(2025, 1, 1), vendor="V1", reason="dup")
        assert req.reason == "dup"

    def test_restore_request_valid(self):
        from mpi_backend.database.schemas.InvoiceVoid import RestoreByKeyRequest

        req = RestoreByKeyRequest(ref_no="R1", date=date(2025, 1, 1), vendor="V1")
        assert req.vendor == "V1"

    def test_response_allows_nulls(self):
        from mpi_backend.database.schemas.InvoiceVoid import InvoiceVoidResponse

        resp = InvoiceVoidResponse(ref_no="R1", date=date(2025, 1, 1), vendor="V1")
        assert resp.invoice_voided_at is None
        assert resp.invoice_voided_by is None
        assert resp.void_reason is None

    def test_response_with_all_fields(self):
        from mpi_backend.database.schemas.InvoiceVoid import InvoiceVoidResponse

        now = datetime.now(timezone.utc)
        resp = InvoiceVoidResponse(
            ref_no="R1", date=date(2025, 1, 1), vendor="V1",
            invoice_voided_at=now, invoice_voided_by="admin@test.com",
            void_reason="test reason",
        )
        assert resp.invoice_voided_at == now
        assert resp.invoice_voided_by == "admin@test.com"
        assert resp.void_reason == "test reason"


# ---------------------------------------------------------------------------
# 5. FilterRequest include_voided field
# ---------------------------------------------------------------------------


class TestFilterRequestIncludeVoided:

    def test_default_is_false(self):
        from mpi_backend.database.schemas.Filters import FilterRequest

        req = FilterRequest()
        assert req.include_voided is False

    def test_can_set_true(self):
        from mpi_backend.database.schemas.Filters import FilterRequest

        req = FilterRequest(include_voided=True)
        assert req.include_voided is True

    def test_serialization_round_trip(self):
        from mpi_backend.database.schemas.Filters import FilterRequest

        data = {"include_voided": True, "filters": {"vendor": ["Acme"]}}
        req = FilterRequest(**data)
        assert req.include_voided is True
        assert req.filters == {"vendor": ["Acme"]}


# ---------------------------------------------------------------------------
# 6. DAO live-join logic
# ---------------------------------------------------------------------------


class TestBuildBaseFilteredQueryVoidLogic:

    def test_joins_invoice_voided_table(self):
        from mpi_backend.database.schemas.Filters import FilterRequest
        from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query

        req = FilterRequest()
        cte, _ = build_base_filtered_query(req)
        assert "public.invoice_voided" in cte

    def test_excludes_voided_by_default(self):
        from mpi_backend.database.schemas.Filters import FilterRequest
        from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query

        req = FilterRequest()
        cte, _ = build_base_filtered_query(req)
        assert "iv.ref_no IS NULL" in cte

    def test_includes_voided_when_requested(self):
        from mpi_backend.database.schemas.Filters import FilterRequest
        from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query

        req = FilterRequest(include_voided=True)
        cte, _ = build_base_filtered_query(req)
        assert "iv.ref_no IS NULL" not in cte

    def test_exposes_live_void_columns(self):
        from mpi_backend.database.schemas.Filters import FilterRequest
        from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query

        req = FilterRequest(include_voided=True)
        cte, _ = build_base_filtered_query(req)
        assert "invoice_voided_at" in cte
        assert "invoice_voided_by" in cte
        assert "void_reason" in cte

    def test_join_matches_on_ref_no_date_vendor(self):
        from mpi_backend.database.schemas.Filters import FilterRequest
        from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query

        req = FilterRequest()
        cte, _ = build_base_filtered_query(req)
        assert "mart.ref_no = iv.ref_no" in cte
        assert "mart.date   = iv.date" in cte
        assert "mart.vendor = iv.vendor" in cte

    def test_void_filter_combines_with_other_filters(self):
        from mpi_backend.database.schemas.Filters import FilterRequest, ComparisonFilter
        from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query

        req = FilterRequest(
            comparison_filters=[ComparisonFilter(column="date", operator="gte", value="2025-01-01")],
            include_voided=False,
        )
        cte, params = build_base_filtered_query(req)
        assert "iv.ref_no IS NULL" in cte
        assert "mart.date >= :date_0" in cte
        assert params["date_0"] == "2025-01-01"


# ---------------------------------------------------------------------------
# 7. Round-trip: void → verify → restore → verify  (TestClient, mock DB)
# ---------------------------------------------------------------------------


class TestVoidRestoreRoundTrip:
    """Full flow through the API using TestClient and a mock DB session."""

    def test_void_then_restore(self, client, override_get_current_user):
        user = _make_user()
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            mock_delete_result = MagicMock()
            mock_delete_result.rowcount = 1
            app.dependency_overrides[get_db] = lambda: mock_db

            try:
                # Step 1: Void
                res = client.post(VOID_URL, json=SAMPLE_KEY)
                assert res.status_code == 200
                assert res.json()["status"] == "voided"

                # Step 2: Restore
                mock_db.reset_mock()
                mock_db.execute.return_value = mock_delete_result

                res = client.post(RESTORE_URL, json=SAMPLE_KEY)
                assert res.status_code == 200
                assert res.json()["status"] == "restored"
            finally:
                app.dependency_overrides.pop(get_db, None)

    def test_double_void_is_idempotent(self, client, override_get_current_user):
        """Voiding the same key twice should succeed (upsert)."""
        user = _make_user()
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            app.dependency_overrides[get_db] = lambda: mock_db

            try:
                res1 = client.post(VOID_URL, json=SAMPLE_KEY)
                res2 = client.post(VOID_URL, json=SAMPLE_KEY)
                assert res1.status_code == 200
                assert res2.status_code == 200
                assert mock_db.execute.call_count == 2
                assert mock_db.commit.call_count == 2
            finally:
                app.dependency_overrides.pop(get_db, None)

    def test_restore_without_prior_void_returns_404(self, client, override_get_current_user):
        user = _make_user()
        with override_get_current_user(user):
            from mpi_backend.main import app
            from mpi_backend.database import get_db

            mock_db = MagicMock()
            mock_result = MagicMock()
            mock_result.rowcount = 0
            mock_db.execute.return_value = mock_result
            app.dependency_overrides[get_db] = lambda: mock_db

            try:
                res = client.post(RESTORE_URL, json=SAMPLE_KEY)
                assert res.status_code == 404
            finally:
                app.dependency_overrides.pop(get_db, None)
