"""linked fix table with overview

Revision ID: e1ca9c2e0a73
Revises: d5feb6ec6cec
Create Date: 2026-02-03 23:50:28.885407

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1ca9c2e0a73'
down_revision = 'd5feb6ec6cec'
branch_labels = None
depends_on = None


def upgrade():
    # Add the foreign key column to 'project_estimate_fixed_items'
    op.add_column('project_estimate_fixed_items', sa.Column('project_estimation_id', sa.Integer(), nullable=True))
    
    # Create the foreign key constraint linking 'project_estimate_fixed_items.project_estimation_id' to 'project_estimation.id'
    op.create_foreign_key(
        'fk_project_estimate_fixed_items_project_estimation', 
        'project_estimate_fixed_items', 
        'project_estimation', 
        ['project_estimation_id'], 
        ['id']
    )


def downgrade():
    # Drop the foreign key and the column
    op.drop_constraint('fk_project_estimate_fixed_items_project_estimation', 'project_estimate_fixed_items', type_='foreignkey')
    op.drop_column('project_estimate_fixed_items', 'project_estimation_id')
