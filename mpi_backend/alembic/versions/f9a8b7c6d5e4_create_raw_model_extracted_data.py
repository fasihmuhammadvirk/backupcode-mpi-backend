"""Create raw.model_extracted_data table for normalized extraction architecture

This migration creates a new table in the raw schema to store one row per extraction
attempt (not per line item). All invoice data including line items are stored in a
JSONB column, with dbt handling the parsing and transformation.

This is Phase 1 of the model_extracted_data refactor - see docs/architecture/model_extracted_data_refactor_plan.md

Revision ID: f9a8b7c6d5e4
Revises: 818417352234
Create Date: 2026-01-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f9a8b7c6d5e4'
down_revision = '818417352234'
branch_labels = None
depends_on = None


def upgrade():
    # Ensure raw schema exists (it should, but be safe)
    op.execute('CREATE SCHEMA IF NOT EXISTS raw')

    # Create new normalized table - one row per extraction attempt
    op.create_table(
        'model_extracted_data',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('s3_file_key', sa.String(), nullable=False),
        sa.Column('pdf_extraction_queue_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('email_queue_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('model_name', sa.String(100), nullable=False),
        sa.Column('prompt_hash', sa.String(12), nullable=True),
        sa.Column('status', sa.String(50), server_default='human_review_required'),
        sa.Column('validation_score', sa.Float(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('raw_data', postgresql.JSONB(), nullable=False),
        sa.Column('extracted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deletion_reason', sa.String(500), nullable=True),
        schema='raw'
    )

    # Create indexes for common query patterns
    op.create_index(
        'ix_med_raw_s3_file_key',
        'model_extracted_data',
        ['s3_file_key'],
        schema='raw'
    )
    op.create_index(
        'ix_med_raw_extracted_at',
        'model_extracted_data',
        ['extracted_at'],
        schema='raw'
    )
    op.create_index(
        'ix_med_raw_pdf_queue_id',
        'model_extracted_data',
        ['pdf_extraction_queue_id'],
        schema='raw'
    )
    op.create_index(
        'ix_med_raw_status',
        'model_extracted_data',
        ['status'],
        schema='raw'
    )
    op.create_index(
        'ix_med_raw_deleted_at',
        'model_extracted_data',
        ['deleted_at'],
        schema='raw'
    )
    # Composite index for deduplication queries
    op.create_index(
        'ix_med_raw_dedup',
        'model_extracted_data',
        ['s3_file_key', 'model_name', 'extracted_at'],
        schema='raw'
    )

    # Add GIN index for JSONB queries (efficient for path queries like raw_data->'line_items')
    op.execute('''
        CREATE INDEX ix_med_raw_data_gin ON raw.model_extracted_data
        USING GIN (raw_data jsonb_path_ops)
    ''')

    # Unique constraint on extraction key columns for idempotent backfill/inserts
    # This allows ON CONFLICT (extraction key) DO NOTHING in the backfill script
    op.create_unique_constraint(
        'uq_med_raw_extraction_key',
        'model_extracted_data',
        ['s3_file_key', 'pdf_extraction_queue_id', 'email_queue_id', 'model_name', 'prompt_hash', 'extracted_at'],
        schema='raw'
    )


def downgrade():
    # Drop unique constraint first
    op.drop_constraint('uq_med_raw_extraction_key', 'model_extracted_data', schema='raw')

    # Drop GIN index (created via raw SQL)
    op.execute('DROP INDEX IF EXISTS raw.ix_med_raw_data_gin')

    # Drop other indexes
    op.drop_index('ix_med_raw_dedup', table_name='model_extracted_data', schema='raw')
    op.drop_index('ix_med_raw_deleted_at', table_name='model_extracted_data', schema='raw')
    op.drop_index('ix_med_raw_status', table_name='model_extracted_data', schema='raw')
    op.drop_index('ix_med_raw_pdf_queue_id', table_name='model_extracted_data', schema='raw')
    op.drop_index('ix_med_raw_extracted_at', table_name='model_extracted_data', schema='raw')
    op.drop_index('ix_med_raw_s3_file_key', table_name='model_extracted_data', schema='raw')

    # Drop table
    op.drop_table('model_extracted_data', schema='raw')
