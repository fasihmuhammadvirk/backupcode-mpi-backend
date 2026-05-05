"""Add validation bypass log table for audit trail

Revision ID: 5a2c8d9e0f1b
Revises: 46924d57a2b9
Create Date: 2026-04-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '5a2c8d9e0f1b'
down_revision = '815f9b63f4a5'
branch_labels = None
depends_on = None


def upgrade():
    # Create validation_bypass_log table in public schema
    op.create_table(
        'validation_bypass_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('pdf_extraction_queue_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('model_extracted_data_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bypassed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('previous_validation_score', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['pdf_extraction_queue_id'], ['raw.pdf_extraction_queue.id'], ),
        sa.ForeignKeyConstraint(['model_extracted_data_id'], ['raw.model_extracted_data.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['public.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )

    # Create indexes for faster lookups
    op.create_index(
        'ix_vbl_pdf_id',
        'validation_bypass_log',
        ['pdf_extraction_queue_id'],
        schema='public'
    )
    op.create_index(
        'ix_vbl_user_id',
        'validation_bypass_log',
        ['user_id'],
        schema='public'
    )


def downgrade():
    op.execute('DROP TABLE IF EXISTS public.validation_bypass_log CASCADE')
