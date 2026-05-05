"""Added ProjectEstimateFinishQuickItems Table

Revision ID: 78e08818550d
Revises: 15e013399a6f
Create Date: 2026-02-04 22:07:06.125008

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '78e08818550d'
down_revision = '15e013399a6f'
branch_labels = None
depends_on = None



def upgrade():
    # Create the project_estimate_finish_quick_items table
    op.create_table(
        'project_estimate_finish_quick_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    # Drop the project_estimate_finish_quick_items table
    op.drop_table('project_estimate_finish_quick_items')
