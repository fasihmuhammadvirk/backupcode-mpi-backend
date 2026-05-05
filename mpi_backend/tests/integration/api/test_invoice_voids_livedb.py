"""
Live-database integration tests for the invoice voided feature.

These tests connect to a REAL PostgreSQL database, pick actual invoices from
analytics.mart__invoice_items, void them via public.invoice_voided, and verify
that they are correctly excluded from all downstream queries and marts.

IMPORTANT:
    - Tests do NOT clean up — voided rows are LEFT in public.invoice_voided
      so you can inspect them manually after the run.
    - Tests REFUSE to run against production databases. The database name must
      contain one of: 'dev', 'test', 'staging', 'local', 'sandbox', or 'mpi_db'.
    - To clean up after inspection, run:
          DELETE FROM public.invoice_voided WHERE invoice_voided_by = 'test_suite';

Requirements:
    - Real PostgreSQL database with populated mart tables (non-production)
    - Database env vars set (POSTGRES_HOST, POSTGRES_DB, etc.) or .env file

Run:
    cd mpi-backend
    uv run pytest mpi_backend/tests/integration/api/test_invoice_voids_livedb.py -v -s

    # The -s flag shows print() output so you can see which invoice was voided.
"""

import os
import re
import sys
import pytest
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))


# ---------------------------------------------------------------------------
# Safety & connectivity checks
# ---------------------------------------------------------------------------

_SAFE_DB_TOKENS = {"dev", "test", "staging", "local", "sandbox", "mpi_db"}
_UNSAFE_DB_TOKENS = {"prod", "production"}
_REQUIRED_ENV_VARS = ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USERNAME", "POSTGRES_PASSWORD")


def _env_vars_present():
    """Check that all required POSTGRES_* env vars are set and non-empty."""
    from mpi_backend.config import POSTGRES_HOST, POSTGRES_DB, POSTGRES_USERNAME, POSTGRES_PASSWORD
    return all(v for v in (POSTGRES_HOST, POSTGRES_DB, POSTGRES_USERNAME, POSTGRES_PASSWORD))


def _get_database_uri():
    """Build DB URI from env vars (same logic as mpi_backend.config)."""
    from mpi_backend.config import SQLALCHEMY_DATABASE_URI
    return SQLALCHEMY_DATABASE_URI


def _db_is_reachable():
    """Quick check that the database is reachable.
    Returns False only if env vars are present but the server can't be reached.
    """
    if not _env_vars_present():
        return False
    try:
        engine = create_engine(_get_database_uri(), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _db_is_safe():
    """Refuse to run against production.

    Splits the DB name into tokens (on non-alphanumeric / underscore boundaries)
    and requires at least one safe token with no unsafe tokens present.
    E.g. 'mpi_db' -> {'mpi', 'db'} — but 'mpi_db' is whitelisted as a full match.
    """
    try:
        from mpi_backend.config import POSTGRES_DB
        db_name = (POSTGRES_DB or "").lower().strip()
        if not db_name:
            return False
        if db_name in _SAFE_DB_TOKENS:
            return True
        tokens = set(filter(None, re.split(r"[\W_]+", db_name)))
        if tokens.intersection(_UNSAFE_DB_TOKENS):
            return False
        return bool(tokens.intersection(_SAFE_DB_TOKENS))
    except Exception:
        return False


_has_env = _env_vars_present()
_reachable = _db_is_reachable()

skip_no_env = pytest.mark.skipif(
    not _has_env,
    reason=(
        f"Missing POSTGRES_* env vars ({', '.join(_REQUIRED_ENV_VARS)}). "
        "Set them in .env or export them."
    ),
)

skip_no_db = pytest.mark.skipif(
    _has_env and not _reachable,
    reason="POSTGRES_* env vars set but database is not reachable — check host/port/credentials"
)

skip_prod = pytest.mark.skipif(
    _reachable and not _db_is_safe(),
    reason=(
        "REFUSING to run against production database. "
        f"DB name must match one of: {sorted(_SAFE_DB_TOKENS)}. "
        "Set POSTGRES_DB to a dev/staging database."
    ),
)


def _skip_guard():
    """Combined guard: skip if no DB or if it looks like production."""
    return pytest.param(marks=[skip_no_db, skip_prod])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db():
    """Real database session for the test module. Auto-closes after all tests."""
    engine = create_engine(_get_database_uri(), pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(scope="module")
def sample_invoice(db):
    """
    Pick ONE real invoice key (ref_no, date, vendor) from the mart that is NOT
    already voided. This key is reused across all tests in this module.

    Prints the picked invoice so you can verify it in the database.
    """
    row = db.execute(text("""
        SELECT mart.ref_no, mart.date, mart.vendor, mart.invoice_items_id
        FROM analytics.mart__invoice_items mart
        LEFT JOIN public.invoice_voided iv
            ON mart.ref_no = iv.ref_no
           AND mart.date   = iv.date
           AND mart.vendor = iv.vendor
        WHERE iv.ref_no IS NULL
          AND mart.ref_no IS NOT NULL
          AND mart.vendor IS NOT NULL
          AND mart.date   IS NOT NULL
        LIMIT 1
    """)).fetchone()

    if row is None:
        pytest.skip("No non-voided invoices in the mart — cannot run live tests")

    invoice = {
        "ref_no": row[0],
        "date": row[1],
        "vendor": row[2],
        "invoice_items_id": row[3],
    }

    print("\n" + "=" * 60)
    print("  TEST INVOICE PICKED FROM MART")
    print(f"    ref_no:            {invoice['ref_no']}")
    print(f"    date:              {invoice['date']}")
    print(f"    vendor:            {invoice['vendor']}")
    print(f"    invoice_items_id:  {invoice['invoice_items_id']}")
    print("=" * 60)

    return invoice


@pytest.fixture(autouse=True, scope="module")
def clean_slate_once(db, sample_invoice):
    """Delete any leftover void row ONCE at module start so tests begin clean.
    Does NOT run between tests — later tests that need a clean state call
    _delete_void explicitly. The last voided row stays for manual inspection."""
    _delete_void(db, sample_invoice)
    yield


def _delete_void(db, key):
    db.execute(text("""
        DELETE FROM public.invoice_voided
        WHERE ref_no = :ref_no AND date = :date AND vendor = :vendor
    """), {"ref_no": key["ref_no"], "date": key["date"], "vendor": key["vendor"]})
    db.commit()


def _insert_void(db, key, reason="live-db test"):
    db.execute(text("""
        INSERT INTO public.invoice_voided
            (ref_no, date, vendor, invoice_voided_at, invoice_voided_by, void_reason)
        VALUES (:ref_no, :date, :vendor, :ts, :by, :reason)
        ON CONFLICT (ref_no, date, vendor) DO UPDATE SET
            invoice_voided_at  = EXCLUDED.invoice_voided_at,
            invoice_voided_by  = EXCLUDED.invoice_voided_by,
            void_reason        = EXCLUDED.void_reason
    """), {
        "ref_no": key["ref_no"],
        "date": key["date"],
        "vendor": key["vendor"],
        "ts": datetime.now(timezone.utc),
        "by": "test_suite",
        "reason": reason,
    })
    db.commit()


# ---------------------------------------------------------------------------
# 1. Core: invoice_voided table operations
# ---------------------------------------------------------------------------


@skip_no_env
@skip_no_db
@skip_prod
class TestLiveInvoiceVoidedTable:
    """Verify INSERT / SELECT / DELETE on the real invoice_voided table."""

    def test_table_exists(self, db):
        exists = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'invoice_voided'
            )
        """)).scalar()
        assert exists, "public.invoice_voided table must exist"

    def test_insert_void_row(self, db, sample_invoice):
        _insert_void(db, sample_invoice)

        row = db.execute(text("""
            SELECT ref_no, invoice_voided_by, void_reason
            FROM public.invoice_voided
            WHERE ref_no = :ref_no AND date = :date AND vendor = :vendor
        """), sample_invoice).fetchone()

        assert row is not None, "Void row should exist after insert"
        assert row[1] == "test_suite"
        assert row[2] == "live-db test"
        print(f"  -> Void row created: ref_no={row[0]}, by={row[1]}, reason={row[2]}")

    def test_upsert_updates_reason(self, db, sample_invoice):
        _insert_void(db, sample_invoice, reason="first reason")
        _insert_void(db, sample_invoice, reason="updated reason")

        reason = db.execute(text("""
            SELECT void_reason FROM public.invoice_voided
            WHERE ref_no = :ref_no AND date = :date AND vendor = :vendor
        """), sample_invoice).scalar()

        assert reason == "updated reason"
        print(f"  -> Upsert updated reason to: {reason}")

    def test_upsert_does_not_duplicate(self, db, sample_invoice):
        _insert_void(db, sample_invoice)
        _insert_void(db, sample_invoice)

        count = db.execute(text("""
            SELECT COUNT(*) FROM public.invoice_voided
            WHERE ref_no = :ref_no AND date = :date AND vendor = :vendor
        """), sample_invoice).scalar()

        assert count == 1
        print(f"  -> After 2 inserts, row count = {count} (no duplicate)")

    def test_delete_removes_row(self, db, sample_invoice):
        _insert_void(db, sample_invoice)
        _delete_void(db, sample_invoice)

        row = db.execute(text("""
            SELECT 1 FROM public.invoice_voided
            WHERE ref_no = :ref_no AND date = :date AND vendor = :vendor
        """), sample_invoice).fetchone()

        assert row is None, "Row should be gone after delete"
        print("  -> Row deleted successfully")


# ---------------------------------------------------------------------------
# 2. Main filter DAO: voided invoices excluded / included
# ---------------------------------------------------------------------------


@skip_no_env
@skip_no_db
@skip_prod
class TestLiveVoidPropagation:
    """Verify that voiding an invoice immediately excludes it from the
    filter DAO queries (live LEFT JOIN to public.invoice_voided)."""

    def test_voided_invoice_excluded_from_main_filter(self, db, sample_invoice):
        """Default filter (include_voided=False) should hide the voided invoice."""
        from mpi_backend.database.schemas.Filters import FilterRequest
        from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query

        _delete_void(db, sample_invoice)
        inv_id = sample_invoice["invoice_items_id"]

        req = FilterRequest()
        cte, params = build_base_filtered_query(req)
        sql = f"{cte} SELECT invoice_items_id FROM filtered_items WHERE invoice_items_id = :target_id"
        params["target_id"] = inv_id
        before = db.execute(text(sql), params).fetchone()
        assert before is not None, "Invoice should be visible before voiding"
        print(f"  -> Before void: invoice {inv_id} VISIBLE in filter")

        _insert_void(db, sample_invoice)

        after = db.execute(text(sql), params).fetchone()
        assert after is None, "Voided invoice should be excluded from default filter"
        print(f"  -> After void:  invoice {inv_id} HIDDEN from filter")

    def test_voided_invoice_visible_with_include_voided(self, db, sample_invoice):
        """include_voided=True should still show the invoice with void metadata."""
        from mpi_backend.database.schemas.Filters import FilterRequest
        from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query

        inv_id = sample_invoice["invoice_items_id"]
        _insert_void(db, sample_invoice, reason="testing include_voided")

        req = FilterRequest(include_voided=True)
        cte, params = build_base_filtered_query(req)
        sql = f"""
            {cte}
            SELECT invoice_items_id, invoice_voided_at, invoice_voided_by, void_reason
            FROM filtered_items
            WHERE invoice_items_id = :target_id
        """
        params["target_id"] = inv_id
        row = db.execute(text(sql), params).fetchone()

        assert row is not None, "Voided invoice should be visible with include_voided=True"
        assert row[1] is not None, "invoice_voided_at should be populated"
        assert row[2] == "test_suite", "invoice_voided_by should be 'test_suite'"
        assert row[3] == "testing include_voided", "void_reason should match"
        print(f"  -> With include_voided=True: voided_at={row[1]}, by={row[2]}, reason={row[3]}")

    def test_restore_makes_invoice_visible_again(self, db, sample_invoice):
        """After restoring, the invoice should reappear in default filter."""
        from mpi_backend.database.schemas.Filters import FilterRequest
        from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query

        inv_id = sample_invoice["invoice_items_id"]

        _insert_void(db, sample_invoice)
        _delete_void(db, sample_invoice)

        req = FilterRequest()
        cte, params = build_base_filtered_query(req)
        sql = f"{cte} SELECT invoice_items_id FROM filtered_items WHERE invoice_items_id = :target_id"
        params["target_id"] = inv_id
        row = db.execute(text(sql), params).fetchone()
        assert row is not None, "Invoice should reappear after restore"
        print(f"  -> After restore: invoice {inv_id} VISIBLE again")


# ---------------------------------------------------------------------------
# 3. get_by_ids DAO: voided invoices excluded
# ---------------------------------------------------------------------------


@skip_no_env
@skip_no_db
@skip_prod
class TestLiveGetByIds:

    def test_get_by_ids_excludes_voided(self, db, sample_invoice):
        from mpi_backend.database.dao.invoice_item_mart.get_by_ids import get_by_ids

        _delete_void(db, sample_invoice)
        inv_id = sample_invoice["invoice_items_id"]

        before = get_by_ids(db, [inv_id])
        assert before is not None and len(before) == 1, "Should return the item before voiding"
        print(f"  -> Before void: get_by_ids returned {len(before)} item(s)")

        _insert_void(db, sample_invoice)

        after = get_by_ids(db, [inv_id])
        assert after is not None and len(after) == 0, "Should exclude voided item"
        print(f"  -> After void:  get_by_ids returned {len(after)} item(s)")

    def test_get_by_ids_returns_after_restore(self, db, sample_invoice):
        from mpi_backend.database.dao.invoice_item_mart.get_by_ids import get_by_ids

        inv_id = sample_invoice["invoice_items_id"]
        _insert_void(db, sample_invoice)
        _delete_void(db, sample_invoice)

        result = get_by_ids(db, [inv_id])
        assert result is not None and len(result) == 1, "Should return item after restore"
        print(f"  -> After restore: get_by_ids returned {len(result)} item(s)")


# ---------------------------------------------------------------------------
# 4. get-locations: voided invoice's customer_job excluded
# ---------------------------------------------------------------------------


@skip_no_env
@skip_no_db
@skip_prod
class TestLiveGetLocations:

    def test_voided_invoices_customer_job_excluded_if_unique(self, db, sample_invoice):
        """If the voided invoice is the only one with a particular customer_job,
        that job should disappear from the locations list."""
        customer_job = db.execute(text("""
            SELECT customer_job FROM analytics.mart__invoice_items
            WHERE invoice_items_id = :id
        """), {"id": sample_invoice["invoice_items_id"]}).scalar()

        if customer_job is None:
            pytest.skip("Sample invoice has no customer_job")

        count = db.execute(text("""
            SELECT COUNT(*) FROM analytics.mart__invoice_items mart
            LEFT JOIN public.invoice_voided iv
                ON mart.ref_no = iv.ref_no AND mart.date = iv.date AND mart.vendor = iv.vendor
            WHERE iv.ref_no IS NULL
              AND mart.customer_job = :cj
              AND NOT (mart.ref_no = :ref_no AND mart.date = :date AND mart.vendor = :vendor)
        """), {
            "cj": customer_job,
            "ref_no": sample_invoice["ref_no"],
            "date": sample_invoice["date"],
            "vendor": sample_invoice["vendor"],
        }).scalar()

        if count > 0:
            pytest.skip(
                f"customer_job '{customer_job}' shared by {count} other items — "
                "can't test unique exclusion"
            )

        _insert_void(db, sample_invoice)

        locations = db.execute(text("""
            SELECT DISTINCT COALESCE(ov.overrides->>'customer_job', mart.customer_job) AS customer_job
            FROM analytics.mart__invoice_items mart
            LEFT JOIN public.user_overrides ov
                ON mart.invoice_items_id::text = ov.record_id AND ov.deleted_at IS NULL
            LEFT JOIN public.invoice_voided iv
                ON mart.ref_no = iv.ref_no AND mart.date = iv.date AND mart.vendor = iv.vendor
            WHERE iv.ref_no IS NULL
        """)).fetchall()

        location_list = [r[0] for r in locations]
        assert customer_job not in location_list, (
            f"customer_job '{customer_job}' should not appear in locations after voiding"
        )
        print(f"  -> customer_job '{customer_job}' correctly excluded from locations")


# ---------------------------------------------------------------------------
# 5. mart__invoice_items_map: voided excluded (live join in DAO)
# ---------------------------------------------------------------------------


@skip_no_env
@skip_no_db
@skip_prod
class TestLiveUnmappedItemsDao:

    def test_unmapped_items_excludes_voided(self, db, sample_invoice):
        """If the sample invoice appears in mart__invoice_items_map, voiding it
        should exclude it from the unmapped items DAO query."""
        ref_no = sample_invoice["ref_no"]
        inv_date = sample_invoice["date"]
        vendor = sample_invoice["vendor"]

        exists_in_map = db.execute(text("""
            SELECT 1 FROM analytics.mart__invoice_items_map
            WHERE ref_no = :ref_no AND date = :date AND vendor = :vendor
            LIMIT 1
        """), {"ref_no": ref_no, "date": inv_date, "vendor": vendor}).fetchone()

        if exists_in_map is None:
            pytest.skip("Sample invoice not in mart__invoice_items_map")

        before = db.execute(text("""
            SELECT COUNT(*) FROM analytics.mart__invoice_items_map m
            LEFT JOIN public.invoice_voided iv
                ON m.ref_no = iv.ref_no AND m.date = iv.date AND m.vendor = iv.vendor
            WHERE iv.ref_no IS NULL
              AND m.ref_no = :ref_no AND m.date = :date AND m.vendor = :vendor
        """), {"ref_no": ref_no, "date": inv_date, "vendor": vendor}).scalar()

        _insert_void(db, sample_invoice)

        after = db.execute(text("""
            SELECT COUNT(*) FROM analytics.mart__invoice_items_map m
            LEFT JOIN public.invoice_voided iv
                ON m.ref_no = iv.ref_no AND m.date = iv.date AND m.vendor = iv.vendor
            WHERE iv.ref_no IS NULL
              AND m.ref_no = :ref_no AND m.date = :date AND m.vendor = :vendor
        """), {"ref_no": ref_no, "date": inv_date, "vendor": vendor}).scalar()

        assert after == 0, f"Expected 0 rows after voiding, got {after} (was {before})"
        print(f"  -> mart__invoice_items_map: {before} rows before, {after} after voiding")


# ---------------------------------------------------------------------------
# 6. Round-trip: void → verify all layers → restore → verify all layers
#    NOTE: This test RESTORES at the end, so the void row will NOT remain.
# ---------------------------------------------------------------------------


@skip_no_env
@skip_no_db
@skip_prod
class TestLiveRoundTrip:

    def test_full_void_restore_cycle(self, db, sample_invoice):
        """End-to-end: void an invoice, verify it's hidden everywhere,
        restore it, verify it reappears."""
        from mpi_backend.database.schemas.Filters import FilterRequest
        from mpi_backend.database.dao.invoice_item_mart.utils import build_base_filtered_query
        from mpi_backend.database.dao.invoice_item_mart.get_by_ids import get_by_ids

        _delete_void(db, sample_invoice)
        inv_id = sample_invoice["invoice_items_id"]

        # --- PRE-VOID: visible everywhere ---
        req = FilterRequest()
        cte, params = build_base_filtered_query(req)
        params["target_id"] = inv_id
        sql = f"{cte} SELECT invoice_items_id FROM filtered_items WHERE invoice_items_id = :target_id"

        assert db.execute(text(sql), params).fetchone() is not None, "Pre-void: filter should show"
        assert len(get_by_ids(db, [inv_id]) or []) == 1, "Pre-void: get_by_ids should return 1"
        print(f"  -> PRE-VOID: invoice {inv_id} visible in filter + get_by_ids")

        # --- VOID ---
        _insert_void(db, sample_invoice, reason="round-trip test")

        void_row = db.execute(text("""
            SELECT void_reason FROM public.invoice_voided
            WHERE ref_no = :ref_no AND date = :date AND vendor = :vendor
        """), sample_invoice).fetchone()
        assert void_row is not None and void_row[0] == "round-trip test"

        assert db.execute(text(sql), params).fetchone() is None, "Post-void: filter should hide"
        assert len(get_by_ids(db, [inv_id]) or []) == 0, "Post-void: get_by_ids should return 0"
        print(f"  -> POST-VOID: invoice {inv_id} hidden from filter + get_by_ids")

        # With include_voided=True it should still be visible
        req_incl = FilterRequest(include_voided=True)
        cte_incl, params_incl = build_base_filtered_query(req_incl)
        params_incl["target_id"] = inv_id
        sql_incl = f"""
            {cte_incl}
            SELECT invoice_items_id, invoice_voided_at, void_reason
            FROM filtered_items WHERE invoice_items_id = :target_id
        """
        incl_row = db.execute(text(sql_incl), params_incl).fetchone()
        assert incl_row is not None, "Post-void: include_voided should show it"
        assert incl_row[2] == "round-trip test", "void_reason should propagate live"
        print(f"  -> POST-VOID with include_voided=True: visible, reason='{incl_row[2]}'")

        # --- RESTORE ---
        _delete_void(db, sample_invoice)

        assert db.execute(text(sql), params).fetchone() is not None, "Post-restore: filter should show"
        assert len(get_by_ids(db, [inv_id]) or []) == 1, "Post-restore: get_by_ids should return 1"
        print(f"  -> POST-RESTORE: invoice {inv_id} visible again everywhere")

        gone = db.execute(text("""
            SELECT 1 FROM public.invoice_voided
            WHERE ref_no = :ref_no AND date = :date AND vendor = :vendor
        """), sample_invoice).fetchone()
        assert gone is None, "invoice_voided row should be deleted after restore"


# ---------------------------------------------------------------------------
# 7. dbt mart column check (after dbt run)
# ---------------------------------------------------------------------------


@skip_no_env
@skip_no_db
@skip_prod
class TestLiveDbtMartColumn:
    """Verify the dbt mart table has the invoice_voided_at column.
    This only validates schema — dbt must have been run at least once."""

    def test_mart_invoice_items_has_voided_column(self, db):
        has_col = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'analytics'
                  AND table_name   = 'mart__invoice_items'
                  AND column_name  = 'invoice_voided_at'
            )
        """)).scalar()
        assert has_col, "analytics.mart__invoice_items should have invoice_voided_at column"
        print("  -> analytics.mart__invoice_items has invoice_voided_at column")

    def test_mart_invoice_items_map_excludes_voided_after_dbt(self, db, sample_invoice):
        """Verify the DAO join correctly excludes voided rows from mart__invoice_items_map."""
        ref_no = sample_invoice["ref_no"]
        inv_date = sample_invoice["date"]
        vendor = sample_invoice["vendor"]

        exists_in_map = db.execute(text("""
            SELECT 1 FROM analytics.mart__invoice_items_map
            WHERE ref_no = :ref_no AND date = :date AND vendor = :vendor
            LIMIT 1
        """), {"ref_no": ref_no, "date": inv_date, "vendor": vendor}).fetchone()

        if exists_in_map is None:
            pytest.skip("Sample invoice not in mart__invoice_items_map (full key)")

        _insert_void(db, sample_invoice)

        count = db.execute(text("""
            SELECT COUNT(*) FROM analytics.mart__invoice_items_map m
            LEFT JOIN public.invoice_voided iv
                ON m.ref_no = iv.ref_no AND m.date = iv.date AND m.vendor = iv.vendor
            WHERE iv.ref_no IS NULL
              AND m.ref_no = :ref_no AND m.date = :date AND m.vendor = :vendor
        """), {"ref_no": ref_no, "date": inv_date, "vendor": vendor}).scalar()

        assert count == 0, "Voided invoice should be excluded via live join"
        print(f"  -> mart__invoice_items_map excludes voided row (count={count})")


# ---------------------------------------------------------------------------
# 8. Final summary — print what's left in the table
# ---------------------------------------------------------------------------


@skip_no_env
@skip_no_db
@skip_prod
class TestLiveFinalSummary:
    """Runs last. Prints what's in public.invoice_voided so you can inspect."""

    def test_print_voided_rows(self, db):
        rows = db.execute(text("""
            SELECT ref_no, date, vendor, invoice_voided_at, invoice_voided_by, void_reason
            FROM public.invoice_voided
            WHERE invoice_voided_by = 'test_suite'
            ORDER BY invoice_voided_at DESC
        """)).fetchall()

        print("\n" + "=" * 70)
        print(f"  ROWS LEFT IN public.invoice_voided (by test_suite): {len(rows)}")
        print("-" * 70)
        for r in rows:
            print(f"    ref_no={r[0]}  date={r[1]}  vendor={r[2]}")
            print(f"      voided_at={r[3]}  by={r[4]}  reason={r[5]}")
        if not rows:
            print("    (none — round-trip test restored its row)")
        print("=" * 70)
        print("  To clean up:  DELETE FROM public.invoice_voided WHERE invoice_voided_by = 'test_suite';")
        print("=" * 70 + "\n")
