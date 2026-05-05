"""fix incorrect tax classification

Revision ID: fix_tax_classification_001
Revises: abc123sheetall
Create Date: 2025-11-19 23:35:00.000000

"""
from alembic import op
from sqlalchemy import text

revision = 'fix_tax_classification_001'
down_revision = 'abc123sheetall'
branch_labels = None
depends_on = None


def upgrade():
    """Correct invoice items incorrectly classified as Tax."""
    connection = op.get_bind()  # type: ignore

    update_query = text("""
        UPDATE invoice_items
        SET mpi_item = 'No Match',
            mpi_description = 'No Match',
            sheet_name = ''
        WHERE item IS NOT NULL
          AND item != ''
          AND description IS NOT NULL
          AND description != ''
          AND description != 'Tax'
          AND sheet_name = '(TAX)'
    """)

    connection.execute(update_query)


def downgrade():
    """
    Attempt to reverse the tax classification fix.

    WARNING: This is an imperfect reversal. The original values of mpi_item
    and mpi_description were not preserved, so this will restore sheet_name
    to '(TAX)' but cannot restore the original MPI values. Items will have:
    - sheet_name = '(TAX)'
    - mpi_item = 'No Match' (may not be original value)
    - mpi_description = 'No Match' (may not be original value)
    """
    connection = op.get_bind()  # type: ignore

    update_query = text("""
        UPDATE invoice_items
        SET sheet_name = '(TAX)'
        WHERE item IS NOT NULL
          AND item != ''
          AND description IS NOT NULL
          AND description != ''
          AND description != 'Tax'
          AND mpi_item = 'No Match'
          AND mpi_description = 'No Match'
          AND sheet_name = ''
    """)

    connection.execute(update_query)
