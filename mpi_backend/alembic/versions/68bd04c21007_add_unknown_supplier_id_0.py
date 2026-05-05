"""Add Unknown Supplier with ID 0

Revision ID: 68bd04c21007
Revises: 3151c3a0ed37
Create Date: 2025-01-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '68bd04c21007'
down_revision = '892f5c780fd3'
branch_labels = None
depends_on = None


def upgrade():
    # Insert Unknown Supplier with ID 0
    # Using raw SQL to set explicit ID value
    op.execute("""
        INSERT INTO suppliers (id, supplier_name, suffix)
        VALUES (0, 'Unknown Supplier', NULL)
        ON CONFLICT (id) DO NOTHING;
    """)


def downgrade():
    conn = op.get_bind()

    # Dynamically discover all tables with FK constraints referencing suppliers.id.
    # No hardcoded table list -- future FKs are automatically picked up.
    fk_references = conn.execute(sa.text("""
        SELECT DISTINCT kcu.table_schema, kcu.table_name, kcu.column_name
        FROM information_schema.referential_constraints rc
        JOIN information_schema.key_column_usage kcu
            ON rc.constraint_name = kcu.constraint_name
            AND rc.constraint_schema = kcu.constraint_schema
        JOIN information_schema.key_column_usage kcu2
            ON rc.unique_constraint_name = kcu2.constraint_name
            AND rc.unique_constraint_schema = kcu2.constraint_schema
        WHERE kcu2.table_name = 'suppliers'
            AND kcu2.column_name = 'id'
    """)).fetchall()

    for schema, table, col in fk_references:
        qualified = f'"{schema}"."{table}"'
        has_refs = conn.execute(
            sa.text(f"SELECT EXISTS(SELECT 1 FROM {qualified} WHERE {col} = 0)")
        ).scalar()
        if has_refs:
            raise RuntimeError(
                f"Cannot remove Unknown Supplier (id=0): "
                f"rows in '{schema}.{table}' still reference {col}=0. "
                f"Reassign or delete those rows first."
            )

    op.execute("""
        DELETE FROM suppliers
        WHERE id = 0 AND supplier_name = 'Unknown Supplier';
    """)
