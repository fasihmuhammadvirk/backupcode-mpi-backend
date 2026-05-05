"""create mappings review table

Revision ID: 1b7fd7e85a93
Revises: 3efba300f068
Create Date: 2026-03-25 11:37:35.359750

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1b7fd7e85a93'
down_revision = '3efba300f068'
branch_labels = None
depends_on = None


def upgrade():
    # Create mappings_review_items table in public schema
    op.create_table(
        'mappings_review_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('vendor', sa.String(), nullable=False),
        sa.Column('item_id', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('map_to_item', sa.String(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('public.users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema='public'
    )

    # 2. Add indexes for faster search and filtering
    op.create_index(
        'idx_mappings_review_items_vendor_item_id',
        'mappings_review_items',
        ['vendor', 'item_id'],
        unique=False,
        schema='public'
    )
    # Create index for faster lookups by user and item_id
    op.create_index(
        'idx_mappings_review_items_user_id',
        'mappings_review_items',
        ['user_id'],
        unique=False,
        schema='public'
    )


def downgrade():
    # Drop table
    op.drop_table('mappings_review_items', schema='public')
