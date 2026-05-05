"""added project_estimation table

Revision ID: d1e5dbaaee18
Revises: c057ef28f56a
Create Date: 2026-01-30 23:04:26.465197

"""
from alembic import op
from sqlalchemy.dialects.postgresql import UUID
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1e5dbaaee18'
down_revision = 'c057ef28f56a'
branch_labels = None
depends_on = None


def upgrade():
    # Create the project_estimation table with user_id as UUID
    op.create_table(
        'project_estimation',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('contract_value', sa.String(), nullable=True),
        sa.Column('budget_allocation', sa.String(), nullable=True),
        sa.Column('labor_percentage', sa.String(), nullable=True),
        sa.Column('material_percentage', sa.String(), nullable=True),
        sa.Column('dollar_point', sa.String(), nullable=True),
        sa.Column('budget_limit', sa.String(), nullable=True),
        sa.Column('labor_rem', sa.String(), nullable=True),
        sa.Column('material_rem', sa.String(), nullable=True),
        sa.Column('finishing', sa.String(), nullable=True),
        sa.Column('point_value', sa.String(), nullable=True),
        sa.Column('target_value', sa.String(), nullable=True),
        
        # Add user_id field with UUID
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True)
    )
    

def downgrade():
    # Drop the project_estimation table
    op.drop_table('project_estimation')