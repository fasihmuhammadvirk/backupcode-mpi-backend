"""Auto Populate Mappings Table

Revision ID: c1540cbb8540
Revises: a1770d74c417
Create Date: 2024-03-25 16:42:58.840986

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
import json
from pathlib import Path
from typing import Dict, List
import logging


# revision identifiers, used by Alembic.
revision = 'c1540cbb8540'
down_revision = 'a1770d74c417'
branch_labels = None
depends_on = None


logger = logging.getLogger('alembic.runtime.migration')

BATCH_SIZE = 1000

PROCESSABLE_SUPPLIERS = [
    'BMW Plumbing Supplies', 'World Wide Plumbing',
    'Y & S Plumbing Supply', 'Supreme Plumbing Supply',
    'Pyramid Plumbing', 'ABC Opus Services',
    'Park Plumbing Supply', 'Gotham Plumbing Supply',
    'FW Webb Plumbing Supply', 'Flow Mark Plumbing Supply',
    'Plumbing Exchange', 'AF Supply', 'Lion Hvac Supplies'
]


def get_base_path() -> Path:
    """Get the base path for fixture files relative to project root."""
    current_dir = Path(__file__).resolve().parent.parent.parent
    fixture_path = current_dir / 'mpi_backend' / 'storage' / 'fixtures'

    if fixture_path.exists():
        return fixture_path

    return Path('mpi_backend/storage/fixtures')


def read_mapping_file(filename: str) -> dict:
    """Read and parse JSON mapping file with error handling."""
    try:
        base_path = get_base_path()
        file_path = base_path / filename

        with open(file_path, 'r', encoding='utf-8') as json_file:
            return json.load(json_file)
    except FileNotFoundError:
        logger.warning(f"Fixture file not found: {filename}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {filename}: {e}")
        raise


def discover_suppliers_from_mappings(
    mappings: List[dict]
) -> Dict[int, str]:
    """
    Discover all unique suppliers from mapping data with their IDs.

    Returns:
        Dict mapping supplier_id to supplier_name
    """
    suppliers_by_id = {}

    for mapping in mappings:
        supplier_id = mapping.get('supplier_id')
        supplier_name = mapping.get('supplier', '').strip()

        if supplier_id and supplier_name:
            if (supplier_id in suppliers_by_id and
                    suppliers_by_id[supplier_id] != supplier_name):
                logger.warning(
                    f"Conflicting supplier names for ID {supplier_id}: "
                    f"'{suppliers_by_id[supplier_id]}' vs '{supplier_name}'"
                )
            suppliers_by_id[supplier_id] = supplier_name

    return suppliers_by_id


def populate_suppliers(bind, suppliers_by_id: Dict[int, str]) -> None:
    """
    Populate suppliers table with discovered suppliers from mappings.
    Uses explicit IDs to match the mapping references.
    Handles cases where some suppliers already exist.
    """
    # Get existing suppliers
    result = bind.execute(text("SELECT id, supplier_name FROM suppliers"))
    existing_suppliers = {row[0]: row[1] for row in result}

    # Find missing suppliers
    missing_suppliers = {}
    for supplier_id, supplier_name in suppliers_by_id.items():
        if supplier_id not in existing_suppliers:
            missing_suppliers[supplier_id] = supplier_name
        elif existing_suppliers[supplier_id] != supplier_name:
            logger.warning(
                f"Supplier ID {supplier_id} exists with different name: "
                f"'{existing_suppliers[supplier_id]}' vs '{supplier_name}'"
            )

    if not missing_suppliers:
        logger.info("All required suppliers already exist in database")
        return

    # Insert missing suppliers
    for supplier_id in sorted(missing_suppliers.keys()):
        supplier_name = missing_suppliers[supplier_id]
        try:
            bind.execute(
                text(
                    "INSERT INTO suppliers (id, supplier_name) "
                    "VALUES (:id, :name)"
                ),
                {"id": supplier_id, "name": supplier_name}
            )
            logger.info(
                f"Inserted supplier: ID {supplier_id} = '{supplier_name}'"
            )
        except Exception as e:
            logger.error(
                f"Failed to insert supplier ID {supplier_id} "
                f"'{supplier_name}': {e}"
            )
            raise

    logger.info(
        f"Successfully inserted {len(missing_suppliers)} missing suppliers"
    )


def batch_insert(
    bind, table_name: str, columns: List[str], records: List[dict]
) -> None:
    """
    Execute batch insert for large datasets.

    Args:
        bind: SQLAlchemy connection
        table_name: Target table name
        columns: List of column names
        records: List of dictionaries with record data
    """
    if not records:
        logger.warning(f"No records to insert into {table_name}")
        return

    placeholders = ', '.join(f':{col}' for col in columns)
    columns_str = ', '.join(columns)
    query_str = (
        f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"
    )
    query = text(query_str)

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        bind.execute(query, batch)

    logger.info(f"Inserted {len(records)} records into {table_name}")


def validate_suppliers_exist(bind, required_supplier_ids: List[int]) -> None:
    """
    Validate that all required supplier IDs exist in the database.
    Raises an exception if any are missing.
    """
    result = bind.execute(text("SELECT id FROM suppliers"))
    existing_ids = {row[0] for row in result}

    missing_ids = set(required_supplier_ids) - existing_ids
    if missing_ids:
        raise ValueError(
            f"Missing suppliers with IDs: {sorted(missing_ids)}. "
            f"Available supplier IDs: {sorted(existing_ids)}"
        )

    logger.info(f"All {len(required_supplier_ids)} required suppliers exist")


def populate_item_mappings(bind, mappings: List[dict]) -> None:
    """Populate supplier item mappings table from fixture data."""
    valid_mappings = []
    required_supplier_ids = set()

    for mapping in mappings:
        supplier_id = mapping.get('supplier_id')
        if not supplier_id:
            continue

        required_supplier_ids.add(supplier_id)
        valid_mappings.append({
            'google_sheet_name': mapping.get('google_sheet_name', ''),
            'mpi_code': mapping.get('mpi_code', ''),
            'description': mapping.get('description', ''),
            'supplier_item_ids': mapping.get('supplier_item_ids', ''),
            'supplier_id': supplier_id
        })

    # Validate all required suppliers exist before inserting mappings
    validate_suppliers_exist(bind, list(required_supplier_ids))

    batch_insert(
        bind,
        'supplier_item_mappings',
        ['google_sheet_name', 'mpi_code', 'description',
         'supplier_item_ids', 'supplier_id'],
        valid_mappings
    )


def populate_temporary_mappings(bind, mappings: List[dict]) -> None:
    """Populate temp item mappings table with backward-compatible schema."""
    temp_mappings = []

    for mapping in mappings:
        original_item = mapping.get(
            'original_item', mapping.get('original_item_number', '')
        )
        description = mapping.get(
            'original_description', mapping.get('description', '')
        )
        temp_item = mapping.get(
            'sheet_name', mapping.get('temporary_item_number', '')
        )

        temp_mappings.append({
            'original_item_number': original_item,
            'description': description,
            'temporary_item_number': temp_item
        })

    batch_insert(
        bind,
        'temporary_item_mappings',
        ['original_item_number', 'description', 'temporary_item_number'],
        temp_mappings
    )


def populate_customer_job_mappings(bind, mappings: List[dict]) -> None:
    """Populate customer job mappings table."""
    customer_mappings = [
        {
            'customer_job': mapping.get('customer_job', ''),
            'updated_customer_job': mapping.get('updated_customer_job', '')
        }
        for mapping in mappings
    ]

    batch_insert(
        bind,
        'customer_job_mappings',
        ['customer_job', 'updated_customer_job'],
        customer_mappings
    )


def upgrade():
    """Execute schema creation and data population."""
    bind = op.get_bind()

    # Create mapping tables with original schema for backward compatibility
    op.create_table(
        'customer_job_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_job', sa.String(), nullable=True),
        sa.Column('updated_customer_job', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'temporary_item_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('original_item_number', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('temporary_item_number', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'supplier_item_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('google_sheet_name', sa.String(), nullable=True),
        sa.Column('mpi_code', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('supplier_item_ids', sa.String(), nullable=True),
        sa.Column('supplier_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Populate data from fixture files
    try:
        item_mapping_data = read_mapping_file('item-mapping.json')

        if (isinstance(item_mapping_data, dict) and
                'permanent_mappings' in item_mapping_data):
            permanent_mappings = item_mapping_data['permanent_mappings']
        elif isinstance(item_mapping_data, list):
            permanent_mappings = item_mapping_data
        else:
            permanent_mappings = []

        if permanent_mappings:
            # Discover all suppliers from mappings (IDs 14, 15, etc.)
            suppliers_by_id = discover_suppliers_from_mappings(
                permanent_mappings
            )
            logger.info(
                f"Discovered {len(suppliers_by_id)} unique suppliers "
                "from mappings"
            )

            populate_suppliers(bind, suppliers_by_id)
            populate_item_mappings(bind, permanent_mappings)
        else:
            logger.warning(
                "No mappings found, using default PROCESSABLE_SUPPLIERS"
            )
            default_suppliers = {
                idx: name
                for idx, name in enumerate(PROCESSABLE_SUPPLIERS, start=1)
            }
            populate_suppliers(bind, default_suppliers)

    except FileNotFoundError:
        logger.warning(
            "Item mapping fixture not found, "
            "using default PROCESSABLE_SUPPLIERS"
        )
        default_suppliers = {
            idx: name
            for idx, name in enumerate(PROCESSABLE_SUPPLIERS, start=1)
        }
        populate_suppliers(bind, default_suppliers)
    except Exception as e:
        logger.error(f"Error populating item mappings: {e}")
        raise

    try:
        temp_mapping_data = read_mapping_file('temp-item-mapping.json')
        if isinstance(temp_mapping_data, list):
            populate_temporary_mappings(bind, temp_mapping_data)
    except FileNotFoundError:
        logger.warning("Temporary mapping fixture not found, skipping")
    except Exception as e:
        logger.error(f"Error populating temporary mappings: {e}")

    try:
        customer_job_data = read_mapping_file('customer-job-mapping.json')
        if isinstance(customer_job_data, list):
            populate_customer_job_mappings(bind, customer_job_data)
    except FileNotFoundError:
        logger.warning("Customer job mapping fixture not found, skipping")
    except Exception as e:
        logger.error(f"Error populating customer job mappings: {e}")


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('supplier_item_mappings')
    op.drop_table('temporary_item_mappings')
    op.drop_table('customer_job_mappings')
    # ### end Alembic commands ###
