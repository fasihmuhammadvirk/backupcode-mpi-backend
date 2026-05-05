"""update username to use citext instead of string

Migration that makes username case insensitive when it was case sensitive

Revision ID: fd1e638d81f0
Revises: 44ee3b8f22f2
Create Date: 2025-10-09 22:43:01.584900

"""
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fd1e638d81f0'
down_revision = '44ee3b8f22f2'
branch_labels = None
depends_on = None

def upgrade():
    # Check for conflicts
    connection = op.get_bind()
    result = connection.execute(sa.text("""
      SELECT LOWER(username) as lower_username,
             array_agg(username) as usernames,
             COUNT(1) as count
      FROM users
      GROUP BY LOWER(username)
      HAVING COUNT(1) > 1
    """))

    conflicts = result.fetchall()
    if conflicts:
      conflict_details = "\n".join([
          f"  - {row.lower_username}: {row.usernames}"
          for row in conflicts
      ])
      raise Exception(
          f"Cannot migrate: Found case-insensitive duplicate usernames:\n"
          f"{conflict_details}\n"
          f"Please resolve these conflicts manually before running migration."
      )

    # Check for NULL usernames
    result = connection.execute(sa.text("""
      SELECT COUNT(1)
      FROM users
      WHERE username IS NULL
    """))

    null_username_count = result.scalar_one()
    if null_username_count > 0:
        raise Exception(f"Cannot migrate: Found {null_username_count} NULL usernames")

    op.execute('CREATE EXTENSION IF NOT EXISTS citext')
    op.alter_column('users', 'username',
                    type_=CITEXT,
                    existing_type=sa.String(),
                    existing_nullable=True,
                    nullable=False)

def downgrade():
    op.alter_column('users', 'username',
                type_=sa.String(),
                existing_type=CITEXT,
                existing_nullable=True,
                nullable=True)
    # Leave citext extension installed

