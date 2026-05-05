"""add status column in mappings_review_items table

Revision ID: 526e1d7b8bb0
Revises: 5a2c8d9e0f1b
Create Date: 2026-04-17 17:20:46.689499

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '526e1d7b8bb0'
down_revision = '5a2c8d9e0f1b'
branch_labels = None
depends_on = None


def upgrade():
    # Add status column to mappings_review_items table
    op.add_column(
        'mappings_review_items',
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        schema='public'
    )

    # Create index on status column
    op.create_index('ix_mappings_review_items_status', 'mappings_review_items', ['status'], schema='public')


def downgrade():
    # Remove index on status column
    op.drop_index('ix_mappings_review_items_status', table_name='mappings_review_items', schema='public')
    # Remove status column from mappings_review_items table
    op.drop_column('mappings_review_items', 'status', schema='public')
