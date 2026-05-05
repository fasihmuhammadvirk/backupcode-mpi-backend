"""Added ProjectEstimateFinishItems Table

Revision ID: 15e013399a6f
Revises: 9a4e81dc0424
Create Date: 2026-02-04 21:53:41.313575

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '15e013399a6f'
down_revision = '9a4e81dc0424'
branch_labels = None
depends_on = None


def upgrade():
    # Create the project_estimate_finish_items table
    op.create_table(
        'project_estimate_finish_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('price', sa.String(), nullable=False),
        sa.Column('qty', sa.String(), nullable=False),
        sa.Column('amount', sa.String(), nullable=False),
        sa.Column('project_estimate_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['project_estimate_id'], ['project_estimation.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    # Drop the project_estimate_finish_items table
    op.drop_table('project_estimate_finish_items')
