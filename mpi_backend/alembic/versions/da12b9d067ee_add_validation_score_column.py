"""add validation_score column

Revision ID: da12b9d067ee
Revises: 9261edd2dbd0
Create Date: 2025-01-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'da12b9d067ee'
down_revision = '9261edd2dbd0'
branch_labels = None
depends_on = None


def upgrade():
    """Add validation_score column to model_extracted_data table."""
    op.add_column('model_extracted_data', sa.Column('validation_score', sa.Float(), nullable=True))


def downgrade():
    """Remove validation_score column from model_extracted_data table."""
    op.drop_column('model_extracted_data', 'validation_score')
