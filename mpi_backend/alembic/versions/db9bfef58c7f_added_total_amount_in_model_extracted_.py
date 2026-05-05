"""added total amount in model_extracted_data

Revision ID: db9bfef58c7f
Revises: a0f3cc1d582b
Create Date: 2025-12-20 05:33:55.658540

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'db9bfef58c7f'
down_revision = 'a0f3cc1d582b'

branch_labels = None
depends_on = None


def upgrade():
    op.add_column('model_extracted_data', sa.Column('total_amount', sa.String(), nullable=True))


def downgrade():
    op.drop_column('model_extracted_data', 'total_amount')
