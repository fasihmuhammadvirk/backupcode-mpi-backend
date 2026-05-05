"""Created table  ProjectEstimateSubItem

Revision ID: 88497d39d3c9
Revises: 8d570ce4add1
Create Date: 2026-02-04 02:01:39.960774

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '88497d39d3c9'
down_revision = '8d570ce4add1'
branch_labels = None
depends_on = None


def upgrade():
    # Create the project_estimate_sub_items table
    op.create_table(
        'project_estimate_sub_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('price', sa.String(), nullable=True),
        sa.Column('type', sa.Enum('LABOR_ONLY', 'LABOR_AND_MATERIAL', name='estimattype'), nullable=False),
        sa.Column('project_estimate_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['project_estimate_id'], ['project_estimation.id']),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade():
    # Drop the project_estimate_sub_items table
    op.drop_table('project_estimate_sub_items')
