"""add_dbt_runs_table

Revision ID: 3151c3a0ed37
Revises: fcde7a1e3567
Create Date: 2026-02-25 00:10:38.098403

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3151c3a0ed37'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('dbt_run_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('execution_time', sa.Float(), nullable=True),
        sa.Column('run_type', sa.String(), nullable=True, server_default='regular'),
        sa.Column('triggered_by', sa.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('dbt_run_log')
