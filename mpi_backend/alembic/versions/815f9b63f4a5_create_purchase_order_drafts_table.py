"""create purchase_order_drafts table

Revision ID: 815f9b63f4a5
Revises: 46924d57a2b9
Create Date: 2026-04-27

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '815f9b63f4a5'
down_revision = '46924d57a2b9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'purchase_order_drafts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('from_date', sa.Date(), nullable=True),
        sa.Column('to_date', sa.Date(), nullable=True),
        sa.Column('items_count', sa.Integer(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('saved_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('public.users.id'), nullable=False),
        schema='public'
    )
    op.create_index(
        'ix_purchase_order_drafts_id',
        'purchase_order_drafts',
        ['id'],
        unique=False,
        schema='public'
    )


def downgrade():
    op.drop_table('purchase_order_drafts', schema='public')
