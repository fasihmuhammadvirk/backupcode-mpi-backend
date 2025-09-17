"""merge migration heads

Revision ID: 8fb3a028a35e
Revises: 68cf285abcde, optimize_performance_2024
Create Date: 2025-07-01 08:22:13.822168

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8fb3a028a35e'
down_revision = ('68cf285abcde', 'optimize_performance_2024')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
