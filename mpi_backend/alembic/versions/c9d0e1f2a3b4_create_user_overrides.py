"""create_user_overrides

Revision ID: c9d0e1f2a3b4
Revises: ab0c8de7731b
Create Date: 2026-02-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'c9d0e1f2a3b4'
down_revision = 'ab0c8de7731b'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    if 'user_overrides' not in existing_tables:
        op.create_table(
            'user_overrides',
            sa.Column('record_id', sa.Text(), nullable=False),
            sa.Column('overrides', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column('overridden_by', postgresql.UUID(), nullable=False),
            sa.Column('overridden_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['overridden_by'], ['users.id']),
            sa.PrimaryKeyConstraint('record_id')
        )
        op.execute(
            "CREATE INDEX user_overrides_overrides_gin_idx ON public.user_overrides USING GIN (overrides)"
        )
        op.create_index('user_overrides_overridden_by_idx', 'user_overrides', ['overridden_by'])
        op.create_index('user_overrides_overridden_at_idx', 'user_overrides', ['overridden_at'])


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    if 'user_overrides' in existing_tables:
        op.drop_index('user_overrides_overridden_at_idx', 'user_overrides')
        op.drop_index('user_overrides_overridden_by_idx', 'user_overrides')
        op.execute("DROP INDEX IF EXISTS user_overrides_overrides_gin_idx")
        op.execute("DROP TABLE user_overrides CASCADE")
