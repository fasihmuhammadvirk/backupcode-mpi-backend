"""Create ProjectEstimateFixedQuickItems table

Revision ID: 8d570ce4add1
Revises: e1ca9c2e0a73
Create Date: 2026-02-04 00:09:59.813166

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8d570ce4add1'
down_revision = 'e1ca9c2e0a73'
branch_labels = None
depends_on = None


def upgrade():
    # Create the project_estimate_fixed_quick_items table
    op.create_table(
        'project_estimate_fixed_quick_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    # Drop the project_estimate_fixed_quick_items table
    op.drop_table('project_estimate_fixed_quick_items')