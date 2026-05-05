"""add_prompt_hash_to_model_extracted_data

Revision ID: 9261edd2dbd0
Revises: b98adc9d2a7b
Create Date: 2026-01-12 21:05:00.864364

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9261edd2dbd0'
down_revision = 'b98adc9d2a7b'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'model_extracted_data',
        sa.Column('prompt_hash', sa.String(12), nullable=True)
    )
    # Optional: index for querying by hash
    op.create_index(
        'ix_model_extracted_data_prompt_hash',
        'model_extracted_data',
        ['prompt_hash']
    )


def downgrade():
    op.drop_index('ix_model_extracted_data_prompt_hash', 'model_extracted_data')
    op.drop_column('model_extracted_data', 'prompt_hash')
