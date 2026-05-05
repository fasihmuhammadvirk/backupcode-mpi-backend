"""Create public.invoice_voided table

Revision ID: create_invoice_voided
Revises: 3efba300f068
Create Date: 2026-03-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import logging

logger = logging.getLogger(__name__)

revision = 'create_invoice_voided'
down_revision = '3efba300f068'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names(schema='public')

    if 'invoice_voided' not in existing_tables:
        op.create_table(
            'invoice_voided',
            sa.Column('ref_no', sa.Text(), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('vendor', sa.Text(), nullable=False),
            sa.Column('invoice_voided_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.Column('invoice_voided_by', sa.Text(), nullable=True),
            sa.Column('void_reason', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('ref_no', 'date', 'vendor'),
            schema='public',
        )
        logger.info("Created public.invoice_voided table")
    else:
        logger.info("public.invoice_voided already exists — skipping")

    try:
        inspector_analytics = sa.inspect(connection)
        columns = [c['name'] for c in inspector_analytics.get_columns('mart__invoice_items', schema='analytics')]
        if 'invoice_voided_at' not in columns:
            op.add_column(
                'mart__invoice_items',
                sa.Column('invoice_voided_at', sa.DateTime(timezone=True), nullable=True),
                schema='analytics',
            )
            logger.info("Added invoice_voided_at column to analytics.mart__invoice_items")
        else:
            logger.info("analytics.mart__invoice_items.invoice_voided_at already exists — skipping")
    except Exception as e:
        logger.warning(f"Could not add column to analytics.mart__invoice_items: {e}")


def downgrade():
    op.drop_table('invoice_voided', schema='public')
    try:
        op.drop_column('mart__invoice_items', 'invoice_voided_at', schema='analytics')
    except Exception:
        pass
