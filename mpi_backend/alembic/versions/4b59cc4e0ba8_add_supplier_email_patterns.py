"""Add supplier email patterns table and is_subject_resolved column (issue 559).

Revision ID: 4b59cc4e0ba8
Revises: 3efba300f068
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "4b59cc4e0ba8"
down_revision = "3efba300f068"
branch_labels = None
depends_on = None

_SEED_ROWS = [
    ("@positive.tech", "Positive Tech", False),
    ("@mpiplumbingcorp.com", "MPI Plumbing Corp", False),
    ("invoicefwdmpi@gmail.com", None, True),
    ("bmwpsupply@gmail.com", "BMW Plumbing Supplies", True),
    ("@wwps.co", "World Wide Plumbing", True),
    ("@ysplumbing.com", "Y & S Plumbing Supply", True),
    ("@supremeplumbingnj.com", "Supreme Plumbing Supply", True),
    ("@pyramidps.com", "Pyramid Plumbing", True),
    ("@opusoperations.com", "ABC Opus Services", False),
    ("@parkplumbingsupply.com", "Park Plumbing Supply", True),
    ("@flowmarksupply.com", "Flow Mark Plumbing Supply", True),
    ("@afsupply.com", "AF Supply", True),
    ("@gothampipesupply.com", "Gotham Plumbing Supply", True),
    ("@brucesupply.net", "Bruce Supply Corp.", True),
    ("@theplumbingexchange.com", "Plumbing Exchange", True),
]


def upgrade():
    """Add is_subject_resolved to suppliers, create supplier_email_patterns, seed data."""
    conn = op.get_bind()

    # ======================================================================
    # 1. Read legacy data (TABLE, VIEW, or MATVIEW) for migration
    # ======================================================================
    legacy = conn.execute(
        text(
            "SELECT c.relkind FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'analytics' AND c.relname = 'email_vendor_mapping'"
        )
    ).fetchone()

    rows = []
    if legacy and legacy[0] in ("r", "v", "m"):
        rows = conn.execute(
            text("SELECT sender_pattern, vendor_name, is_active FROM analytics.email_vendor_mapping")
        ).fetchall()
    if not rows:
        rows = _SEED_ROWS

    # ======================================================================
    # 2. Add is_subject_resolved column to suppliers
    # ======================================================================
    op.add_column(
        "suppliers",
        sa.Column(
            "is_subject_resolved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(
        text(
            "CREATE UNIQUE INDEX uq_suppliers_subject_resolved_true "
            "ON public.suppliers (is_subject_resolved) "
            "WHERE is_subject_resolved = true"
        )
    )

    # ======================================================================
    # 3. Create supplier_email_patterns table
    # ======================================================================
    op.create_table(
        "supplier_email_patterns",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("sender_pattern", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sender_pattern", name="uq_supplier_email_patterns_sender_pattern"),
    )
    op.create_index("ix_supplier_email_patterns_supplier_id", "supplier_email_patterns", ["supplier_id"])

    # ======================================================================
    # 4. Seed supplier_email_patterns from legacy data or defaults
    # ======================================================================
    for sender_pattern, vendor_name, is_active in rows:
        sp = sender_pattern.strip().lower()
        subject = vendor_name is None or (isinstance(vendor_name, str) and vendor_name.strip() == "")

        if subject:
            # Get or create the subject-resolved supplier
            row = conn.execute(
                text("SELECT id FROM public.suppliers WHERE is_subject_resolved = true LIMIT 1")
            ).fetchone()
            if row:
                sid = row[0]
            else:
                sid = conn.execute(
                    text(
                        "INSERT INTO public.suppliers (supplier_name, is_subject_resolved) "
                        "VALUES ('Subject-Resolved Inbox', true) RETURNING id"
                    )
                ).fetchone()[0]
        else:
            # Get or create a named supplier
            vn = vendor_name.strip()
            row = conn.execute(
                text("SELECT id FROM public.suppliers WHERE supplier_name = :name LIMIT 1"),
                {"name": vn},
            ).fetchone()
            if row:
                sid = row[0]
            else:
                sid = conn.execute(
                    text("INSERT INTO public.suppliers (supplier_name) VALUES (:name) RETURNING id"),
                    {"name": vn},
                ).fetchone()[0]

        conn.execute(
            text(
                "INSERT INTO public.supplier_email_patterns (supplier_id, sender_pattern, is_active) "
                "VALUES (:sid, :sp, :ia) ON CONFLICT (sender_pattern) DO NOTHING"
            ),
            {"sid": sid, "sp": sp, "ia": bool(is_active)},
        )

    # ======================================================================
    # 5. Drop legacy analytics.email_vendor_mapping (TABLE, VIEW, or MATVIEW)
    # ======================================================================
    kind_row = conn.execute(
        text(
            "SELECT c.relkind FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'analytics' AND c.relname = 'email_vendor_mapping'"
        )
    ).fetchone()
    if kind_row:
        kind = kind_row[0]
        if kind == "r":
            op.execute(text("DROP TABLE analytics.email_vendor_mapping CASCADE"))
        elif kind == "v":
            op.execute(text("DROP VIEW analytics.email_vendor_mapping CASCADE"))
        elif kind == "m":
            op.execute(text("DROP MATERIALIZED VIEW analytics.email_vendor_mapping CASCADE"))


def downgrade():
    """Backfill analytics.email_vendor_mapping, then drop new table and column."""
    conn = op.get_bind()

    # ======================================================================
    # 1. Recreate analytics.email_vendor_mapping from current data
    # ======================================================================
    has_patterns = conn.execute(
        text("SELECT to_regclass('public.supplier_email_patterns') IS NOT NULL")
    ).scalar()

    if has_patterns:
        op.execute(text("CREATE SCHEMA IF NOT EXISTS analytics"))
        op.execute(text(
            "CREATE TABLE IF NOT EXISTS analytics.email_vendor_mapping ("
            "  sender_pattern VARCHAR(255) PRIMARY KEY,"
            "  vendor_name VARCHAR,"
            "  is_active BOOLEAN NOT NULL DEFAULT true"
            ")"
        ))
        op.execute(text("TRUNCATE TABLE analytics.email_vendor_mapping"))

        has_subject_col = conn.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.columns "
                "  WHERE table_schema = 'public' AND table_name = 'suppliers' "
                "  AND column_name = 'is_subject_resolved'"
                ")"
            )
        ).scalar()

        if has_subject_col:
            op.execute(text(
                "INSERT INTO analytics.email_vendor_mapping (sender_pattern, vendor_name, is_active) "
                "SELECT p.sender_pattern, "
                "  CASE WHEN s.is_subject_resolved THEN NULL ELSE s.supplier_name END, "
                "  p.is_active "
                "FROM public.supplier_email_patterns p "
                "JOIN public.suppliers s ON s.id = p.supplier_id"
            ))
        else:
            op.execute(text(
                "INSERT INTO analytics.email_vendor_mapping (sender_pattern, vendor_name, is_active) "
                "SELECT p.sender_pattern, s.supplier_name, p.is_active "
                "FROM public.supplier_email_patterns p "
                "JOIN public.suppliers s ON s.id = p.supplier_id"
            ))

    # ======================================================================
    # 2. Drop supplier_email_patterns table
    # ======================================================================
    op.execute(text("DROP TABLE IF EXISTS public.supplier_email_patterns CASCADE"))

    # ======================================================================
    # 3. Drop partial unique index and is_subject_resolved column from suppliers
    # ======================================================================
    op.execute(text("DROP INDEX IF EXISTS public.uq_suppliers_subject_resolved_true"))
    op.execute(text("ALTER TABLE public.suppliers DROP COLUMN IF EXISTS is_subject_resolved CASCADE"))
