"""add sheet name synchronization system

Revision ID: abc123sheetall
Revises: 77b1822a68aa
Create Date: 2025-10-21 00:00:00.000000

This migration adds the complete sheet name synchronization system:
1. Adds sheet_id column to supplier_item_mappings table
2. Adds sheet_id column to temporary_item_mappings table
3. Creates google_sheet_metadata table for canonical name tracking
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'abc123sheetall'
down_revision = '77b1822a68aa'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add sheet name synchronization system.
    """
    # 1. Add sheet_id to supplier_item_mappings
    op.add_column(
        'supplier_item_mappings',
        sa.Column('sheet_id', sa.String(), nullable=True)
    )
    op.create_index(
        'idx_supplier_item_mappings_sheet_id',
        'supplier_item_mappings',
        ['sheet_id'],
        unique=False
    )

    # 2. Add sheet_id to temporary_item_mappings
    op.add_column(
        'temporary_item_mappings',
        sa.Column('sheet_id', sa.String(), nullable=True)
    )
    op.create_index(
        'idx_temporary_item_mappings_sheet_id',
        'temporary_item_mappings',
        ['sheet_id'],
        unique=False
    )

    # 3. Create google_sheet_metadata table
    op.create_table(
        'google_sheet_metadata',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sheet_id', sa.String(), nullable=False),
        sa.Column('sheet_name', sa.String(), nullable=False),
        sa.Column('spreadsheet_id', sa.String(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'spreadsheet_id',
            'sheet_id',
            name='uq_spreadsheet_sheet'
        )
    )
    op.create_index(
        'idx_sheet_id',
        'google_sheet_metadata',
        ['sheet_id'],
        unique=False
    )
    op.create_index(
        'idx_spreadsheet_id',
        'google_sheet_metadata',
        ['spreadsheet_id'],
        unique=False
    )


def downgrade():
    """
    Remove sheet name synchronization system.
    """
    # Drop google_sheet_metadata table and its indexes
    op.drop_index('idx_spreadsheet_id', table_name='google_sheet_metadata')
    op.drop_index('idx_sheet_id', table_name='google_sheet_metadata')
    op.drop_table('google_sheet_metadata')

    # Remove sheet_id from temporary_item_mappings
    op.drop_index(
        'idx_temporary_item_mappings_sheet_id',
        table_name='temporary_item_mappings'
    )
    op.drop_column('temporary_item_mappings', 'sheet_id')

    # Remove sheet_id from supplier_item_mappings
    op.drop_index(
        'idx_supplier_item_mappings_sheet_id',
        table_name='supplier_item_mappings'
    )
    op.drop_column('supplier_item_mappings', 'sheet_id')

