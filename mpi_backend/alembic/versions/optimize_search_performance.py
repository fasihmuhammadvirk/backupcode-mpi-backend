"""Optimize search performance for by-column-paginated endpoint

Revision ID: optimize_search_performance
Revises: optimize_invoice_items_performance
Create Date: 2024-12-19 15:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'optimize_search_performance'
down_revision = 'optimize_invoice_items_performance'
branch_labels = None
depends_on = None


def upgrade():
    """Add search-optimized indexes for ultra-fast search performance"""
    
    # Add GIN indexes for text search columns (PostgreSQL specific)
    # These indexes dramatically improve ILIKE performance for search queries
    
    # GIN index for vendor column with trigram support
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_vendor_gin 
        ON invoice_items USING GIN (vendor gin_trgm_ops)
    """)
    
    # GIN index for item column with trigram support
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_item_gin 
        ON invoice_items USING GIN (item gin_trgm_ops)
    """)
    
    # GIN index for description column with trigram support
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_description_gin 
        ON invoice_items USING GIN (description gin_trgm_ops)
    """)
    
    # GIN index for ref_no column with trigram support
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_ref_no_gin 
        ON invoice_items USING GIN (ref_no gin_trgm_ops)
    """)
    
    # GIN index for customer_job column with trigram support
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_customer_job_gin 
        ON invoice_items USING GIN (customer_job gin_trgm_ops)
    """)
    
    # GIN index for po_number column with trigram support
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_po_number_gin 
        ON invoice_items USING GIN (po_number gin_trgm_ops)
    """)
    
    # Composite indexes for common search combinations
    # These indexes optimize the most common search patterns
    
    # Index for active items with vendor search
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_active_vendor_search
        ON invoice_items (is_active, vendor) 
        WHERE is_active IS TRUE
    """)
    
    # Index for active items with item search
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_active_item_search
        ON invoice_items (is_active, item) 
        WHERE is_active IS TRUE
    """)
    
    # Index for active items with ref_no search
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_active_ref_no_search
        ON invoice_items (is_active, ref_no) 
        WHERE is_active IS TRUE
    """)
    
    # Index for active items with customer_job search
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_active_customer_job_search
        ON invoice_items (is_active, customer_job) 
        WHERE is_active IS TRUE
    """)
    
    # Partial indexes for non-null search columns
    # These indexes only include rows where the search column has data
    
    # Partial index for vendor with data
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_vendor_partial
        ON invoice_items (vendor) 
        WHERE vendor IS NOT NULL AND vendor != ''
    """)
    
    # Partial index for item with data
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_item_partial
        ON invoice_items (item) 
        WHERE item IS NOT NULL AND item != ''
    """)
    
    # Partial index for ref_no with data
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_ref_no_partial
        ON invoice_items (ref_no) 
        WHERE ref_no IS NOT NULL AND ref_no != ''
    """)
    
    # Partial index for customer_job with data
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoice_items_customer_job_partial
        ON invoice_items (customer_job) 
        WHERE customer_job IS NOT NULL AND customer_job != ''
    """)
    
    # Enable trigram extension if not already enabled
    # This is required for GIN trigram indexes
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade():
    """Remove search-optimized indexes"""
    
    # Drop GIN indexes
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_vendor_gin")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_item_gin")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_description_gin")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_ref_no_gin")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_customer_job_gin")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_po_number_gin")
    
    # Drop composite indexes
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_active_vendor_search")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_active_item_search")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_active_ref_no_search")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_active_customer_job_search")
    
    # Drop partial indexes
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_vendor_partial")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_item_partial")
    op.execute("DROP INDEX IF EXISTS ix_invoice_items_ref_no_partial")
    op.execute(
        "DROP INDEX IF EXISTS ix_invoice_items_customer_job_partial"
    )
