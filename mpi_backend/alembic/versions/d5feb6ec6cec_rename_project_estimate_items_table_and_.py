"""Rename project_estimate_items table and remove quantity column

Revision ID: d5feb6ec6cec
Revises: d1e5dbaaee18
Create Date: 2026-02-02 22:04:49.997443

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5feb6ec6cec'
down_revision = 'd1e5dbaaee18'
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table('project_estimate_items', 'project_estimate_fixed_items')
    op.drop_column('project_estimate_fixed_items', 'quantity')


def downgrade():
    op.rename_table('project_estimate_fixed_items', 'project_estimate_items')
    op.add_column('project_estimate_items', sa.Column('quantity', sa.String(), nullable=True))

