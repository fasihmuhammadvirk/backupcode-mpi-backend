"""add_suffix_column_to_suppliers

Revision ID: 770d869bb9f1
Revises: fix_tax_classification_001
Create Date: 2025-11-21 21:56:10.330499

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '770d869bb9f1'
down_revision = 'fix_tax_classification_001'
branch_labels = None
depends_on = None


def upgrade():
    # Add suffix column to suppliers table
    op.add_column('suppliers', sa.Column('suffix', sa.String(), nullable=True))
    
    # Populate suffix column with default values
    # Note: Only updating suppliers that exist in the database (IDs 1-13)
    # Bruce (14) and Ferguson (15) do not exist in public.suppliers table
    op.execute("""
        UPDATE suppliers SET suffix = 'B' WHERE id = 1;  -- BMW Plumbing Supplies
        UPDATE suppliers SET suffix = 'W' WHERE id = 2;  -- World Wide Plumbing
        UPDATE suppliers SET suffix = 'Y' WHERE id = 3;  -- Y & S Plumbing Supply
        UPDATE suppliers SET suffix = 'S' WHERE id = 4;  -- Supreme Plumbing Supply
        UPDATE suppliers SET suffix = 'P' WHERE id = 5;  -- Pyramid Plumbing
        UPDATE suppliers SET suffix = 'A' WHERE id = 6;  -- ABC Opus Services
        UPDATE suppliers SET suffix = 'P' WHERE id = 7;  -- Park Plumbing Supply
        UPDATE suppliers SET suffix = 'G' WHERE id = 8;  -- Gotham Plumbing Supply
        UPDATE suppliers SET suffix = 'F' WHERE id = 9;  -- FW Webb Plumbing Supply
        UPDATE suppliers SET suffix = 'F' WHERE id = 10; -- Flow Mark Plumbing Supply
        UPDATE suppliers SET suffix = NULL WHERE id = 11; -- Plumbing Exchange (no suffix)
        UPDATE suppliers SET suffix = 'A' WHERE id = 12; -- AF Supply
        UPDATE suppliers SET suffix = NULL WHERE id = 13; -- Lion Hvac Supplies (no suffix)
    """)


def downgrade():
    # Remove suffix column from suppliers table
    op.drop_column('suppliers', 'suffix')
