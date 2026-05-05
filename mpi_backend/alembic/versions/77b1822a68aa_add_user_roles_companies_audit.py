"""add_user_roles_companies_audit

Revision ID: 77b1822a68aa
Revises: 44ee3b8f22f2
Create Date: 2025-10-03 00:16:57.370279

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '77b1822a68aa'
down_revision = 'fd1e638d81f0'
branch_labels = None
depends_on = None


def upgrade():
    # Get database connection and inspector
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Get existing tables
    existing_tables = inspector.get_table_names()

    # 1. Create companies table if it doesn't exist
    if 'companies' not in existing_tables:
        op.create_table(
            'companies',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name')
        )
        op.create_index('ix_companies_name', 'companies', ['name'])

    # 2. Add columns to users table if they don't exist
    if 'users' in existing_tables:
        users_columns = [col['name'] for col in inspector.get_columns('users')]

        if 'email' not in users_columns:
            op.add_column('users', sa.Column('email', sa.String(), nullable=True))

        if 'role' not in users_columns:
            op.add_column('users', sa.Column('role', sa.String(), server_default='standard', nullable=False))

        # Add company_id column before creating indexes
        if 'company_id' not in users_columns:
            op.add_column('users', sa.Column('company_id', sa.Integer(), nullable=True))

        if 'is_active' not in users_columns:
            op.add_column('users', sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False))

        if 'created_at' not in users_columns:
            op.add_column('users', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))

        if 'updated_at' not in users_columns:
            op.add_column('users', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

        # 3. Create foreign key constraint if it doesn't exist
        users_fks = [fk['name'] for fk in inspector.get_foreign_keys('users')]
        if 'fk_users_company' not in users_fks:
            op.create_foreign_key('fk_users_company', 'users', 'companies', ['company_id'], ['id'])

        # 4. Add indexes if they don't exist
        users_indexes = [idx['name'] for idx in inspector.get_indexes('users')]

        if 'ix_users_role' not in users_indexes:
            op.create_index('ix_users_role', 'users', ['role'])

        if 'ix_users_company_id' not in users_indexes:
            op.create_index('ix_users_company_id', 'users', ['company_id'])

        if 'ix_users_is_active' not in users_indexes:
            op.create_index('ix_users_is_active', 'users', ['is_active'])

        # 5. Add unique constraint if it doesn't exist
        users_constraints = [constraint['name'] for constraint in inspector.get_unique_constraints('users')]
        if 'uq_users_email' not in users_constraints:
            op.create_unique_constraint('uq_users_email', 'users', ['email'])

    # 6. Create user_audit_logs table if it doesn't exist
    if 'user_audit_logs' not in existing_tables:
        op.create_table(
            'user_audit_logs',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('user_id', postgresql.UUID(), nullable=False),
            sa.Column('action', sa.String(), nullable=False),
            sa.Column('changed_by', postgresql.UUID(), nullable=False),
            sa.Column('old_values', sa.JSON(), nullable=True),
            sa.Column('new_values', sa.JSON(), nullable=True),
            sa.Column('ip_address', sa.String(), nullable=True),
            sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['changed_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_audit_user_id', 'user_audit_logs', ['user_id'])
        op.create_index('ix_audit_timestamp', 'user_audit_logs', ['timestamp'])


def downgrade():
    # Get database connection and inspector
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Get existing tables
    existing_tables = inspector.get_table_names()

    # Drop user_audit_logs table if it exists
    if 'user_audit_logs' in existing_tables:
        op.drop_index('ix_audit_timestamp', 'user_audit_logs')
        op.drop_index('ix_audit_user_id', 'user_audit_logs')
        op.drop_table('user_audit_logs')

    # Remove users table modifications if they exist
    if 'users' in existing_tables:
        users_columns = [col['name'] for col in inspector.get_columns('users')]
        users_indexes = [idx['name'] for idx in inspector.get_indexes('users')]
        users_constraints = [constraint['name'] for constraint in inspector.get_unique_constraints('users')]
        users_fks = [fk['name'] for fk in inspector.get_foreign_keys('users')]

        # Drop unique constraint if it exists
        if 'uq_users_email' in users_constraints:
            op.drop_constraint('uq_users_email', 'users', type_='unique')

        # Drop indexes if they exist
        if 'ix_users_is_active' in users_indexes:
            op.drop_index('ix_users_is_active', 'users')

        if 'ix_users_company_id' in users_indexes:
            op.drop_index('ix_users_company_id', 'users')

        if 'ix_users_role' in users_indexes:
            op.drop_index('ix_users_role', 'users')

        # Drop foreign key if it exists
        if 'fk_users_company' in users_fks:
            op.drop_constraint('fk_users_company', 'users', type_='foreignkey')

        # Drop columns if they exist
        if 'updated_at' in users_columns:
            op.drop_column('users', 'updated_at')

        if 'created_at' in users_columns:
            op.drop_column('users', 'created_at')

        if 'is_active' in users_columns:
            op.drop_column('users', 'is_active')

        if 'company_id' in users_columns:
            op.drop_column('users', 'company_id')

        if 'role' in users_columns:
            op.drop_column('users', 'role')

        if 'email' in users_columns:
            op.drop_column('users', 'email')

    # Drop companies table if it exists
    if 'companies' in existing_tables:
        op.drop_index('ix_companies_name', 'companies')
        op.drop_table('companies')
