"""DESTRUCTIVE_truncate_model_extracted_data

Existing records reference deprecated `public.invoices` instead of `raw.pdf_extraction_queue`.
DATA IS NOT RECOVERABLE.

Requires: ALLOW_DESTRUCTIVE_MIGRATION=true

Revision ID: b98adc9d2a7b
Revises: b13400779e95
Create Date: 2026-01-12 17:58:43.393789

"""
import os
import inspect
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'b98adc9d2a7b'
down_revision = 'b13400779e95'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    result = conn.execute(text("SELECT COUNT(*) FROM public.model_extracted_data"))
    row_count = result.scalar()

    if row_count > 0 and os.getenv("ALLOW_DESTRUCTIVE_MIGRATION", "").lower() != "true":
        raise RuntimeError(
            inspect.cleandoc(f""" 
                WARNING: DEVS, THIS IS A DESTRUCTIVE MIGRATION
                This will truncate `model_extracted_data` ({row_count} rows) because we have deprecated the table
                `invoices` which `model_extracted_data` references in favor of `raw.pdf_extraction_queue_id`.

                For details, see https://github.com/Mpi-plumbing/mpi-backend/issues/378

                Set ALLOW_DESTRUCTIVE_MIGRATION=true to proceed.
                Or run `ALLOW_DESTRUCTIVE_MIGRATION=true uv run alembic upgrade head`
            """)
        )

    op.execute("TRUNCATE TABLE public.model_extracted_data;")


def downgrade():
    pass  # Data cannot be restored

