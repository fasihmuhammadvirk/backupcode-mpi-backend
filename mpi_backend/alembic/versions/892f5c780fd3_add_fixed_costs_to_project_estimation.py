"""Add fixed_costs to project_estimation

Revision ID: 892f5c780fd3
Revises: 3151c3a0ed37
Create Date: 2026-03-11 09:43:12.966754

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '892f5c780fd3'
down_revision = '3151c3a0ed37'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add the nullable column
    op.add_column('project_estimation', sa.Column('fixed_costs', sa.String(), nullable=True))
    
    # 2. Backfill existing data
    connection = op.get_bind()
    
    # Fetch all fixed items grouped by project_estimation_id
    results = connection.execute(sa.text(
        "SELECT project_estimation_id, price FROM project_estimate_fixed_items"
    )).fetchall()
    
    # Calculate totals per project_estimation_id
    project_totals = {}
    for row in results:
        pid = row.project_estimation_id
        price_val = row.price
        
        if price_val:
            try:
                clean_price = str(price_val).replace(',', '')
                price = float(clean_price)
            except (ValueError, TypeError):
                price = 0.0
        else:
            price = 0.0
            
        project_totals[pid] = project_totals.get(pid, 0.0) + price
    
    # Update project_estimation rows with the calculated totals
    for pid, total in project_totals.items():
        connection.execute(
            sa.text("UPDATE project_estimation SET fixed_costs = :total WHERE id = :pid"),
            {"total": str(total), "pid": pid}
        )

def downgrade():
    op.drop_column('project_estimation', 'fixed_costs')

