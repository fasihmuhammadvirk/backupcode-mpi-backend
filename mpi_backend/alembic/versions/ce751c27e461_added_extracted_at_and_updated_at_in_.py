"""Added extracted_at and updated_at in ModelExtractedData

Revision ID: ce751c27e461
Revises: ea292210faae
Create Date: 2025-12-31 14:29:20.726276

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ce751c27e461'
down_revision = 'ea292210faae'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('model_extracted_data', sa.Column('extracted_at', sa.DateTime(), nullable=True))
    op.add_column('model_extracted_data', sa.Column('updated_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('model_extracted_data', 'extracted_at')
    op.drop_column('model_extracted_data', 'updated_at')