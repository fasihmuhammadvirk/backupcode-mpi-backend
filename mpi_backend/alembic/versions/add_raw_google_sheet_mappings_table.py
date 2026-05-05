"""Add raw_google_sheet_mappings table for dbt consumption

Revision ID: a1b2c3d4e5f6
Revises: 770d869bb9f1
Create Date: 2025-12-09

This migration creates:
1. The 'raw' schema (if not exists)
2. The raw_google_sheet_mappings table

This table stores extracted Google Sheet data in a format optimized for dbt to consume.
The Python loader script extracts from Google Sheets and loads data here.
dbt then transforms this into permanent/temporary mapping tables.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '770d869bb9f1'
branch_labels = None
depends_on = None


def upgrade():
    # Create the 'raw' schema if it doesn't exist
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")

    # Create the raw_google_sheet_mappings table
    op.create_table(
        'raw_google_sheet_mappings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),

        # Sheet identification
        sa.Column('sheet_title', sa.String(), nullable=False, comment="Category/tab name from Google Sheets (e.g., 'AIR FITTINGS')"),
        sa.Column('google_sheet_name', sa.String(), nullable=True, comment="Name of the Google Sheet file"),
        sa.Column('sheet_id', sa.String(), nullable=True, comment="Google Sheets gid for tracking across renames"),

        # MPI mapping data
        sa.Column('mpi_code', sa.String(), nullable=True, comment="Internal MPI item code (e.g., 'FWCR4030')"),
        sa.Column('description', sa.String(), nullable=True, comment="MPI description (e.g., 'STD CONC REDUCERS')"),

        # Supplier info
        sa.Column('supplier', sa.String(), nullable=True, comment="Supplier name (e.g., 'World Wide Plumbing')"),
        sa.Column('supplier_id', sa.Integer(), nullable=True, comment="Supplier ID (reference only, not FK)"),

        # Supplier item codes (key for joining to invoice_items.item)
        sa.Column('supplier_item_ids', sa.String(), nullable=True, comment="Supplier's item code with suffix (e.g., 'WELC4030-Y')"),
        sa.Column('original_supplier_item_id', sa.String(), nullable=True, comment="Original item code before processing"),

        # Debugging/audit metadata
        sa.Column('row_number', sa.Integer(), nullable=True, comment="Row number in the Google Sheet"),
        sa.Column('column_index', sa.Integer(), nullable=True, comment="Column index in the Google Sheet"),

        # Classification
        sa.Column('mapping_type', sa.String(), nullable=False, comment="permanent, temporary, or invalid"),
        sa.Column('validation_status', sa.String(), nullable=True, comment="Validation result"),

        # Timestamps
        sa.Column('extraction_timestamp', sa.DateTime(), nullable=True, comment="When extracted from Google Sheets"),
        sa.Column('loaded_at', sa.DateTime(), server_default=sa.text('NOW()'), comment="When loaded into this table"),

        sa.PrimaryKeyConstraint('id'),
        schema='raw'
    )

    # Create index on supplier_item_ids for efficient joins
    op.create_index(
        'ix_raw_google_sheet_mappings_supplier_item_ids',
        'raw_google_sheet_mappings',
        ['supplier_item_ids'],
        schema='raw'
    )

    # Create index on mapping_type for filtering
    op.create_index(
        'ix_raw_google_sheet_mappings_mapping_type',
        'raw_google_sheet_mappings',
        ['mapping_type'],
        schema='raw'
    )


def downgrade():
    op.drop_index('ix_raw_google_sheet_mappings_mapping_type', table_name='raw_google_sheet_mappings', schema='raw')
    op.drop_index('ix_raw_google_sheet_mappings_supplier_item_ids', table_name='raw_google_sheet_mappings', schema='raw')
    op.drop_table('raw_google_sheet_mappings', schema='raw')
    # Note: Not dropping the 'raw' schema as other tables might use it
