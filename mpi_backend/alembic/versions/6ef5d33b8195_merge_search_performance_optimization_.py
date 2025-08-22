"""merge search performance optimization with existing head

Revision ID: 6ef5d33b8195
Revises: d8dc9f5e8414, optimize_search_performance
Create Date: 2025-08-22 16:16:04.317558

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6ef5d33b8195'
down_revision = ('d8dc9f5e8414', 'optimize_search_performance')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
