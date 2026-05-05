"""merge three heads into single lineage

Revision ID: c22ad1076339
Revises: 4b59cc4e0ba8, 77182ed42dac, create_invoice_voided
Create Date: 2026-03-30 16:14:12.015566

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c22ad1076339'
down_revision = ('4b59cc4e0ba8', '77182ed42dac', 'create_invoice_voided')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
