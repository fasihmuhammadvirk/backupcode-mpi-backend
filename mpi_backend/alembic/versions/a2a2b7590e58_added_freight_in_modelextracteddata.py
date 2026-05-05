"""Added freight in ModelExtractedData

Revision ID: a2a2b7590e58
Revises: 4890e438ee72
Create Date: 2026-01-06 20:22:22.336221

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2a2b7590e58'
down_revision = '4890e438ee72'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('model_extracted_data', sa.Column('freight', sa.String(), nullable=True))


def downgrade():
    op.drop_column('model_extracted_data', 'freight')

