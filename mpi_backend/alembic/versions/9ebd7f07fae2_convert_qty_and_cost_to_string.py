"""convert_qty_and_cost_to_string

Revision ID: 9ebd7f07fae2
Revises: da12b9d067ee
Create Date: 2026-01-15 00:13:48.155662

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9ebd7f07fae2'
down_revision = 'da12b9d067ee'
branch_labels = None
depends_on = None


def upgrade():
    """Convert qty from Integer to String and cost from Float to String with data migration."""
    # Drop the DBT-managed view that depends on these columns
    # Note: DBT will recreate this view on next dbt run
    op.execute("DROP VIEW IF EXISTS analytics_staging.stg__model_extracted_data CASCADE")

    # Convert qty column: Integer -> String
    # Using CAST to convert existing integer values to strings
    op.execute("""
        ALTER TABLE model_extracted_data
        ALTER COLUMN qty TYPE VARCHAR USING CAST(qty AS VARCHAR)
    """)

    # Convert cost column: Float -> String
    # Using CAST to convert existing float values to strings
    op.execute("""
        ALTER TABLE model_extracted_data
        ALTER COLUMN cost TYPE VARCHAR USING CAST(cost AS VARCHAR)
    """)


def downgrade():
    """Revert qty and cost back to numeric types."""
    # Drop the DBT-managed view if it exists
    op.execute("DROP VIEW IF EXISTS analytics_staging.stg__model_extracted_data CASCADE")

    # Revert cost column: String -> Float
    # Handle potential null/empty strings by converting to NULL first
    op.execute("""
        ALTER TABLE model_extracted_data
        ALTER COLUMN cost TYPE FLOAT USING
            CASE
                WHEN cost = '' OR cost IS NULL THEN NULL
                ELSE CAST(cost AS FLOAT)
            END
    """)

    # Revert qty column: String -> Integer
    # Handle potential null/empty strings by converting to NULL first
    op.execute("""
        ALTER TABLE model_extracted_data
        ALTER COLUMN qty TYPE INTEGER USING
            CASE
                WHEN qty = '' OR qty IS NULL THEN NULL
                ELSE CAST(qty AS INTEGER)
            END
    """)
