"""create_quickbooks_items_table

Revision ID: fcde7a1e3567
Revises: f9a8b7c6d5e4
Create Date: 2026-02-12 12:40:52.518051

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = 'fcde7a1e3567'
down_revision = 'f9a8b7c6d5e4'
branch_labels = None
depends_on = None


def upgrade():
    """Create the quickbooks_items table for tracking exported items"""
    op.create_table(
        'quickbooks_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('invoice_items_id', sa.BigInteger(), nullable=False),
        sa.Column('invoice_id', UUID(as_uuid=True), nullable=False),
        sa.Column('ref_no', sa.String(), nullable=True),
        sa.Column('vendor', sa.String(), nullable=True),
        sa.Column('date', sa.Date(), nullable=True),
        sa.Column('exported_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )
    
    # Create indexes for better query performance
    op.create_index(
        'ix_quickbooks_items_id',
        'quickbooks_items',
        ['id'],
        schema='public'
    )
    op.create_index(
        'ix_quickbooks_items_invoice_items_id',
        'quickbooks_items',
        ['invoice_items_id'],
        schema='public'
    )
    op.create_index(
        'ix_quickbooks_items_invoice_id',
        'quickbooks_items',
        ['invoice_id'],
        schema='public'
    )
    op.create_index(
        'ix_quickbooks_items_exported_at',
        'quickbooks_items',
        ['exported_at'],
        schema='public'
    )


def downgrade():
    """Drop the quickbooks_items table"""
    op.drop_table('quickbooks_items', schema='public')
