"""add user_overrides partial index

Revision ID: 4c2b9881580d
Revises: 307c23e98f20
Create Date: 2026-04-08 16:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4c2b9881580d'
down_revision = '307c23e98f20'
branch_labels = None
depends_on = None


def upgrade():
    # Adding partial index to optimize join in build_base_filtered_query.
    # This specifically speeds up the LEFT JOIN public.user_overrides o 
    # ON mart.invoice_items_id::text = o.record_id AND o.deleted_at IS NULL
    # by provide a smaller, targeted index for non-deleted overrides.
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_overrides_record_id_active
        ON public.user_overrides (record_id)
        WHERE deleted_at IS NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_user_overrides_record_id_active")
