"""remove total amount and add sub-total in model extraction table

Revision ID: 4890e438ee72
Revises: ce751c27e461
Create Date: 2026-01-06 21:53:37.451264

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4890e438ee72'
down_revision = 'ce751c27e461'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('model_extracted_data', 'total_amount')
    op.add_column('model_extracted_data', sa.Column('sub_total', sa.String(), nullable=True))


def downgrade():
    op.drop_column('model_extracted_data', 'sub_total')
    op.add_column('model_extracted_data', sa.Column('total_amount', sa.String(), nullable=True))