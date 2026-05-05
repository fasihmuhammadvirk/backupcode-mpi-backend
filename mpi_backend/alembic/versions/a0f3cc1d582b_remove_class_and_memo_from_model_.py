"""remove class and memo from model_extracted_data

Revision ID: a0f3cc1d582b
Revises: 65e12e91361b
Create Date: 2025-12-20 04:12:29.779741

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a0f3cc1d582b'
down_revision = '65e12e91361b'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('model_extracted_data', 'class_')
    op.drop_column('model_extracted_data', 'memo')


def downgrade():
    op.add_column('model_extracted_data', sa.Column('class_', sa.String(), nullable=True))
    op.add_column('model_extracted_data', sa.Column('memo', sa.String(), nullable=True))
