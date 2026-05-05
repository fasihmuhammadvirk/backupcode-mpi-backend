"""add user uploaded pdfs table

Revision ID: 77182ed42dac
Revises: 3efba300f068
Create Date: 2026-03-02 14:16:07.214484

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '77182ed42dac'
down_revision = '3efba300f068'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create user_uploaded_pdfs table
    op.create_table(
        'user_uploaded_pdfs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('s3_file_key', sa.Text(), nullable=False),
        sa.Column('supplier_id', sa.Integer(), sa.ForeignKey('public.suppliers.id'), nullable=False),
        sa.Column('supplier_name', sa.String(255), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('public.users.id'), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deletion_reason', sa.String(500), nullable=True),
        schema='raw'
    )

    # 2. Alter pdf_extraction_queue
    # Add user_upload_id
    op.add_column(
        'pdf_extraction_queue',
        sa.Column('user_upload_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('raw.user_uploaded_pdfs.id'),
                  nullable=True),
        schema='raw'
    )
    op.create_index(
        'idx_pdf_extraction_queue_user_upload_id',
        'pdf_extraction_queue',
        ['user_upload_id'],
        unique=False,
        schema='raw'
    )

    # Make email_queue_id nullable
    op.alter_column('pdf_extraction_queue', 'email_queue_id', existing_type=postgresql.UUID(), nullable=True,
                    schema='raw')

    op.create_check_constraint(
        'ck_pdf_extraction_queue_exactly_one_source',
        'pdf_extraction_queue',
        "(email_queue_id IS NOT NULL AND user_upload_id IS NULL) OR "
        "(email_queue_id IS NULL AND user_upload_id IS NOT NULL)",
        schema='raw'
    )

    # 3. Create trigger function for user uploads
    op.execute("""
               CREATE OR REPLACE FUNCTION raw.populate_extraction_queue_user_upload_fn() RETURNS TRIGGER AS
               $$
               BEGIN
                   INSERT INTO raw.pdf_extraction_queue (user_upload_id, s3_key, supplier_name)
                   VALUES (NEW.id, NEW.s3_file_key, NEW.supplier_name);
                   RETURN NEW;
               END;
               $$ LANGUAGE plpgsql;
               """)

    # 4. Create trigger
    op.execute("""
               CREATE TRIGGER trg_populate_extraction_queue_user_upload
                   AFTER INSERT
                   ON raw.user_uploaded_pdfs
                   FOR EACH ROW
               EXECUTE FUNCTION raw.populate_extraction_queue_user_upload_fn();
               """)


def downgrade():
    # 1. Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS trg_populate_extraction_queue_user_upload ON raw.user_uploaded_pdfs;")
    op.execute("DROP FUNCTION IF EXISTS raw.populate_extraction_queue_user_upload_fn();")

    # 2. Revert pdf_extraction_queue changes
    op.execute("ALTER TABLE raw.pdf_extraction_queue DROP CONSTRAINT IF EXISTS ck_pdf_extraction_queue_exactly_one_source")
    op.execute("DROP INDEX IF EXISTS raw.idx_pdf_extraction_queue_user_upload_id")
    
    # Remove rows introduced by user-upload flow before restoring NOT NULL constraint
    op.execute("DELETE FROM raw.pdf_extraction_queue WHERE email_queue_id IS NULL;")
    
    op.alter_column('pdf_extraction_queue', 'email_queue_id', existing_type=postgresql.UUID(), nullable=False,
                    schema='raw')
    op.drop_column('pdf_extraction_queue', 'user_upload_id', schema='raw')

    # 3. Drop user_uploaded_pdfs table
    op.execute("DROP TABLE IF EXISTS raw.user_uploaded_pdfs CASCADE;")
