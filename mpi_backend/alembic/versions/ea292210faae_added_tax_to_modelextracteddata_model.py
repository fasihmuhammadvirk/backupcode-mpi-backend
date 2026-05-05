"""Added tax to ModelExtractedData Model

Revision ID: ea292210faae
Revises: db9bfef58c7f
Create Date: 2025-12-26 15:38:02.539174

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ea292210faae'
down_revision = 'db9bfef58c7f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('model_extracted_data', sa.Column('tax', sa.String(), nullable=True))


def downgrade():
    op.drop_column('model_extracted_data', 'tax')
