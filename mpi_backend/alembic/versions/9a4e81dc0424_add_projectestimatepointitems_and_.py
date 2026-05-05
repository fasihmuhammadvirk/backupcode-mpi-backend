"""Add ProjectEstimatePointItems and ProjectEstimatePointQuickItems tables

Revision ID: 9a4e81dc0424
Revises: 88497d39d3c9
Create Date: 2026-02-04 04:11:30.581206

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9a4e81dc0424'
down_revision = '88497d39d3c9'
branch_labels = None
depends_on = None


def upgrade():
    # Create the project_estimate_point_items table
    op.create_table(
        'project_estimate_point_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('pts', sa.String(), nullable=False),
        sa.Column('qty', sa.String(), nullable=False),
        sa.Column('amount', sa.String(), nullable=False),
        sa.Column('project_estimate_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['project_estimate_id'], ['project_estimation.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Create the project_estimate_point_quick_items table
    op.create_table(
        'project_estimate_point_quick_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    # Drop the project_estimate_point_items and project_estimate_point_quick_items tables
    op.drop_table('project_estimate_point_items')
    op.drop_table('project_estimate_point_quick_items')