"""add soft delete columns to queue tables

Add deleted_at and deletion_reason to model_extracted_data, email_download_queue,
and pdf_extraction_queue to support cascading soft deletes across the data pipeline.

Revision ID: 818417352234
Revises: 9ebd7f07fae2
Create Date: 2026-01-16 15:32:07.101657

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '818417352234'
down_revision = '9ebd7f07fae2'
branch_labels = None
depends_on = None


def upgrade():
    # Add soft delete columns to model_extracted_data
    op.add_column('model_extracted_data', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('model_extracted_data', sa.Column('deletion_reason', sa.String(500), nullable=True))

    # Add soft delete columns to email_download_queue
    op.add_column('email_download_queue', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True), schema='raw')
    op.add_column('email_download_queue', sa.Column('deletion_reason', sa.String(500), nullable=True), schema='raw')

    # Add soft delete columns to pdf_extraction_queue
    op.add_column('pdf_extraction_queue', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True), schema='raw')
    op.add_column('pdf_extraction_queue', sa.Column('deletion_reason', sa.String(500), nullable=True), schema='raw')


def downgrade():
    # Remove soft delete columns from pdf_extraction_queue
    op.drop_column('pdf_extraction_queue', 'deletion_reason', schema='raw')
    op.drop_column('pdf_extraction_queue', 'deleted_at', schema='raw')

    # Remove soft delete columns from email_download_queue
    op.drop_column('email_download_queue', 'deletion_reason', schema='raw')
    op.drop_column('email_download_queue', 'deleted_at', schema='raw')

    # Remove soft delete columns from model_extracted_data
    op.drop_column('model_extracted_data', 'deletion_reason')
    op.drop_column('model_extracted_data', 'deleted_at')
