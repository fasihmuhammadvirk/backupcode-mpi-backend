"""added project_estimate_items table

Revision ID: c057ef28f56a
Revises: f9a8b7c6d5e4
Create Date: 2026-01-30 22:23:31.600510

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c057ef28f56a'
down_revision = 'fcde7a1e3567'
branch_labels = None
depends_on = None

def upgrade():
    # Create the project_estimate_items table
    op.create_table(
        'project_estimate_items',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('price', sa.String(), nullable=True),
        sa.Column('quantity', sa.String(), nullable=True),
    )

def downgrade():
    # Drop the project_estimate_items table
    op.drop_table('project_estimate_items')
