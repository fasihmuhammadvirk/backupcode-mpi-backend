"""Create ModelExtractedData Model

Revision ID: 65e12e91361b
Revises: 770d869bb9f1
Create Date: 2025-12-12 00:50:54.738876

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '65e12e91361b'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None



def upgrade():
    op.create_table(
        'model_extracted_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('model_name', sa.String(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('item', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('qty', sa.Integer(), nullable=True),
        sa.Column('cost', sa.Float(), nullable=True),
        sa.Column('amount', sa.String(), nullable=True),
        sa.Column('date', sa.Date(), nullable=True),
        sa.Column('ref_no', sa.String(), nullable=True),
        sa.Column('po_number', sa.String(), nullable=True),
        sa.Column('customer_job', sa.String(), nullable=True),
        sa.Column('bill', sa.String(), nullable=True),
        sa.Column('vendor', sa.String(), nullable=True),
        sa.Column('class_', sa.String(), nullable=True),
        sa.Column('memo', sa.String(), nullable=True),
        sa.Column('buyer', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True, server_default='human_review_required'),
        sa.Column('file_path', sa.String(), nullable=True),
        sa.Column('s3_file_key', sa.String(), nullable=True),
        sa.Column('invoice_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_foreign_key(
        'model_extracted_data_invoice_id_fkey',
        'model_extracted_data',  
        'invoices',              
        ['invoice_id'],   
        ['id']
    )

def downgrade():
    op.drop_table('model_extracted_data')
