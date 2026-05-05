"""fix pipe joining materials typo

Revision ID: 46924d57a2b9
Revises: e5f6a7b8c9d0
Create Date: 2026-04-13 11:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '46924d57a2b9'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    # Update the item classification to fix the singular/plural typo
    op.execute("""
        UPDATE item_classification 
        SET item = '(PIPE JOINING MATERIALS)' 
        WHERE item = '(PIPE JOINING MATERIAL)'
    """)


def downgrade():
    # Revert the item classification to the singular form
    op.execute("""
        UPDATE item_classification 
        SET item = '(PIPE JOINING MATERIAL)' 
        WHERE item = '(PIPE JOINING MATERIALS)'
    """)
