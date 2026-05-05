"""integrate_email_queue_with_pdf_extraction

Revision ID: b13400779e95
Revises: 91dc2be282cb
Create Date: 2026-01-11 01:02:49.122862

This migration combines three logical changes for the email-to-extraction pipeline:
1. Create pdf_extraction_queue table with auto-populate trigger
2. Rename invoice_id -> pdf_extraction_queue_id in model_extracted_data
3. Add email_queue_id column to model_extracted_data for direct email linkage
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'b13400779e95'
down_revision = '91dc2be282cb'
branch_labels = None
depends_on = None


def upgrade():
    # ==========================================================================
    # 1. Create pdf_extraction_queue table
    # ==========================================================================
    op.create_table(
        'pdf_extraction_queue',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('email_queue_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('raw.email_download_queue.id'), nullable=False),
        sa.Column('s3_key', sa.Text(), nullable=False),
        sa.Column('supplier_name', sa.String(255), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('email_queue_id', 's3_key', name='uq_pdf_extraction_queue_email_s3key'),
        schema='raw'
    )

    op.create_index('idx_pdf_extraction_queue_status', 'pdf_extraction_queue', ['status'], schema='raw')
    op.create_index('idx_pdf_extraction_queue_email_id', 'pdf_extraction_queue', ['email_queue_id'], schema='raw')

    # Create trigger function: auto-populate extraction queue when email download completes
    op.execute("""
        CREATE OR REPLACE FUNCTION raw.populate_extraction_queue_fn() RETURNS TRIGGER AS $$
        BEGIN
            -- Only fire when status changes TO 'DOWNLOADED' and s3_keys is not empty
            IF NEW.status = 'DOWNLOADED' AND NEW.s3_keys IS NOT NULL AND jsonb_array_length(NEW.s3_keys) > 0 THEN
                INSERT INTO raw.pdf_extraction_queue (email_queue_id, s3_key)
                SELECT NEW.id, jsonb_array_elements_text(NEW.s3_keys)
                ON CONFLICT (email_queue_id, s3_key) DO NOTHING;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create trigger: fires after email_download_queue row is updated to DOWNLOADED
    op.execute("""
        CREATE TRIGGER trg_populate_extraction_queue
        AFTER UPDATE ON raw.email_download_queue
        FOR EACH ROW
        WHEN (NEW.status = 'DOWNLOADED' AND OLD.status != 'DOWNLOADED')
        EXECUTE FUNCTION raw.populate_extraction_queue_fn();
    """)

    # Create trigger: fires after insert with status already DOWNLOADED
    op.execute("""
        CREATE TRIGGER trg_populate_extraction_queue_insert
        AFTER INSERT ON raw.email_download_queue
        FOR EACH ROW
        WHEN (NEW.status = 'DOWNLOADED')
        EXECUTE FUNCTION raw.populate_extraction_queue_fn();
    """)

    # ==========================================================================
    # 2. Rename invoice_id -> pdf_extraction_queue_id in model_extracted_data
    # ==========================================================================
    # Drop the old FK constraint to invoices table
    op.drop_constraint(
        'model_extracted_data_invoice_id_fkey',
        'model_extracted_data',
        type_='foreignkey',
        schema='public'
    )

    # Rename the column
    op.alter_column(
        'model_extracted_data',
        'invoice_id',
        new_column_name='pdf_extraction_queue_id',
        schema='public'
    )

    # Add new FK constraint to pdf_extraction_queue
    op.create_foreign_key(
        'model_extracted_data_pdf_extraction_queue_id_fkey',
        'model_extracted_data',
        'pdf_extraction_queue',
        ['pdf_extraction_queue_id'],
        ['id'],
        source_schema='public',
        referent_schema='raw'
    )

    # ==========================================================================
    # 3. Add email_queue_id column to model_extracted_data
    # ==========================================================================
    op.add_column(
        'model_extracted_data',
        sa.Column(
            'email_queue_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('raw.email_download_queue.id'),
            nullable=True
        ),
        schema='public'
    )

    op.create_index(
        'idx_model_extracted_data_email_queue_id',
        'model_extracted_data',
        ['email_queue_id'],
        schema='public'
    )


def downgrade():
    # ==========================================================================
    # 3. Remove email_queue_id column from model_extracted_data
    # ==========================================================================
    op.drop_index(
        'idx_model_extracted_data_email_queue_id',
        table_name='model_extracted_data',
        schema='public'
    )

    op.drop_column('model_extracted_data', 'email_queue_id', schema='public')

    # ==========================================================================
    # 2. Rename pdf_extraction_queue_id -> invoice_id in model_extracted_data
    # ==========================================================================
    # Drop FK to pdf_extraction_queue
    op.drop_constraint(
        'model_extracted_data_pdf_extraction_queue_id_fkey',
        'model_extracted_data',
        type_='foreignkey',
        schema='public'
    )

    # Rename column back
    op.alter_column(
        'model_extracted_data',
        'pdf_extraction_queue_id',
        new_column_name='invoice_id',
        schema='public'
    )

    # NOTE: Cannot restore FK to invoices table as data may reference pdf_extraction_queue IDs
    # In production, you would need to handle data migration before restoring this constraint

    # ==========================================================================
    # 1. Drop pdf_extraction_queue table and triggers
    # ==========================================================================
    op.execute("DROP TRIGGER IF EXISTS trg_populate_extraction_queue ON raw.email_download_queue;")
    op.execute("DROP TRIGGER IF EXISTS trg_populate_extraction_queue_insert ON raw.email_download_queue;")
    op.execute("DROP FUNCTION IF EXISTS raw.populate_extraction_queue_fn();")

    op.drop_index('idx_pdf_extraction_queue_email_id', table_name='pdf_extraction_queue', schema='raw')
    op.drop_index('idx_pdf_extraction_queue_status', table_name='pdf_extraction_queue', schema='raw')

    op.drop_table('pdf_extraction_queue', schema='raw')
