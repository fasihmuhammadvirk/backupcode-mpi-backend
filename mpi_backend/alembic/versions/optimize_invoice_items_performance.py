"""Optimize invoice items performance

Revision ID: optimize_performance_2024
Revises: 601fd59ac6d6
Create Date: 2024-12-19 10:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'optimize_performance_2024'
down_revision = '601fd59ac6d6'
branch_labels = None
depends_on = None


def upgrade():
    """Add performance indexes for invoice_items table"""
    
    # Add indexes for commonly filtered columns
    op.create_index('ix_invoice_items_vendor', 'invoice_items', ['vendor'])
    op.create_index('ix_invoice_items_customer_job', 'invoice_items', 
                    ['customer_job'])
    op.create_index('ix_invoice_items_date', 'invoice_items', ['date'])
    op.create_index('ix_invoice_items_item', 'invoice_items', ['item'])
    op.create_index('ix_invoice_items_export_status', 'invoice_items', 
                    ['export_status'])
    op.create_index('ix_invoice_items_class', 'invoice_items', ['class_'])
    op.create_index('ix_invoice_items_is_active', 'invoice_items', 
                    ['is_active'])
    op.create_index('ix_invoice_items_account', 'invoice_items', ['account'])
    op.create_index('ix_invoice_items_ref_no', 'invoice_items', ['ref_no'])
    
    # Add composite indexes for common filter combinations
    op.create_index('ix_invoice_items_vendor_date', 'invoice_items', 
                    ['vendor', 'date'])
    op.create_index('ix_invoice_items_customer_job_date', 'invoice_items', 
                    ['customer_job', 'date'])
    op.create_index('ix_invoice_items_is_active_vendor', 'invoice_items', 
                    ['is_active', 'vendor'])
    op.create_index('ix_invoice_items_is_active_date', 'invoice_items', 
                    ['is_active', 'date'])
    
    # Add indexes for numeric filtering
    op.create_index('ix_invoice_items_cost', 'invoice_items', ['cost'])
    op.create_index('ix_invoice_items_qty', 'invoice_items', ['qty'])
    
    # Add partial index for active items only (most common case)
    op.execute("""
        CREATE INDEX ix_invoice_items_active_vendor_date 
        ON invoice_items (vendor, date) 
        WHERE is_active = true OR is_active IS NULL
    """)

    # Functional indexes to support lower(trim(...)) comparisons used in filters
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_items_vendor_norm ON invoice_items (lower(trim(vendor)))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_items_item_norm ON invoice_items (lower(trim(item)))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_items_ref_no_norm ON invoice_items (lower(trim(ref_no)))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_items_customer_job_norm ON invoice_items (lower(trim(customer_job)))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_items_class_norm ON invoice_items (lower(trim(class_)))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_items_account_norm ON invoice_items (lower(trim(account)))")


def downgrade():
    """Remove performance indexes"""
    
    # Drop all the indexes we created
    op.drop_index('ix_invoice_items_vendor', table_name='invoice_items')
    op.drop_index('ix_invoice_items_customer_job', table_name='invoice_items')
    op.drop_index('ix_invoice_items_date', table_name='invoice_items')
    op.drop_index('ix_invoice_items_item', table_name='invoice_items')
    op.drop_index('ix_invoice_items_export_status', table_name='invoice_items')
    op.drop_index('ix_invoice_items_class', table_name='invoice_items')
    op.drop_index('ix_invoice_items_is_active', table_name='invoice_items')
    op.drop_index('ix_invoice_items_account', table_name='invoice_items')
    op.drop_index('ix_invoice_items_ref_no', table_name='invoice_items')
    
    # Drop composite indexes
    op.drop_index('ix_invoice_items_vendor_date', 
                  table_name='invoice_items')
    op.drop_index('ix_invoice_items_customer_job_date', 
                  table_name='invoice_items')
    op.drop_index('ix_invoice_items_is_active_vendor', 
                  table_name='invoice_items')
    op.drop_index('ix_invoice_items_is_active_date', 
                  table_name='invoice_items')
    
    # Drop numeric indexes
    op.drop_index('ix_invoice_items_cost', table_name='invoice_items')
    op.drop_index('ix_invoice_items_qty', table_name='invoice_items')
    
    # Drop partial index
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_active_vendor_date") 
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_vendor_norm")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_item_norm")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_ref_no_norm")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_customer_job_norm")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_class_norm")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_account_norm")