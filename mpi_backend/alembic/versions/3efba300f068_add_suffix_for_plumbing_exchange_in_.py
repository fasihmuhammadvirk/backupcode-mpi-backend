"""add suffix for plumbing exchange in supplier table

Revision ID: 3efba300f068
Revises: 68bd04c21007
Create Date: 2026-03-13 18:15:38.288603

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3efba300f068'
down_revision = '68bd04c21007'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE suppliers SET suffix = 'PE' WHERE supplier_name = 'Plumbing Exchange'")


def downgrade():
    op.execute("UPDATE suppliers SET suffix = NULL WHERE supplier_name = 'Plumbing Exchange' AND suffix = 'PE'")
