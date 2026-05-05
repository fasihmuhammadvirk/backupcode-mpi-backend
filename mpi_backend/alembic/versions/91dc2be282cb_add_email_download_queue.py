"""add email download queue

Revision ID: add_email_download_queue
Revises: optimize_search_performance
Create Date: 2026-01-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '91dc2be282cb'
down_revision = 'a2a2b7590e58'
branch_labels = None
depends_on = None


def upgrade():
    """Create email_download_queue table for bulk email download tracking"""
    # Ensure gen_random_uuid() is available (built-in for Postgres 13+, pgcrypto for older versions)
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    # Create trigger function for updated_at auto-update
    op.execute("""
        CREATE OR REPLACE FUNCTION raw.update_email_download_queue_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.create_table(
        'email_download_queue',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('email_uid', sa.String(100), nullable=False, unique=True),
        sa.Column('message_id', sa.String(255), nullable=True),
        sa.Column('sender', sa.String(255), nullable=False),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('email_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('s3_keys', postgresql.JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column('attachment_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('in_email_pdf_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        schema='raw'
    )

    # Create trigger for updated_at auto-update on row modification
    op.execute("""
        CREATE TRIGGER trg_email_download_queue_updated_at
        BEFORE UPDATE ON raw.email_download_queue
        FOR EACH ROW
        EXECUTE FUNCTION raw.update_email_download_queue_updated_at();
    """)

    # Create indexes for query performance
    op.create_index('idx_email_queue_status', 'email_download_queue', ['status'], schema='raw')
    op.create_index('idx_email_queue_email_date', 'email_download_queue', ['email_date'], schema='raw')
    op.create_index('idx_email_queue_sender', 'email_download_queue', ['sender'], schema='raw')


def downgrade():
    """Drop email_download_queue table"""
    # Drop trigger first
    op.execute("DROP TRIGGER IF EXISTS trg_email_download_queue_updated_at ON raw.email_download_queue;")

    op.drop_index('idx_email_queue_sender', table_name='email_download_queue', schema='raw')
    op.drop_index('idx_email_queue_email_date', table_name='email_download_queue', schema='raw')
    op.drop_index('idx_email_queue_status', table_name='email_download_queue', schema='raw')
    op.drop_table('email_download_queue', schema='raw')

    # Drop trigger function after table is dropped
    op.execute("DROP FUNCTION IF EXISTS raw.update_email_download_queue_updated_at();")
