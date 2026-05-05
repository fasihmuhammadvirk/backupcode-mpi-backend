"""
Raw Google Sheet Mapping Model

This table stores the raw extracted data from Google Sheets for item mappings.
It serves as the source of truth for dbt to consume and transform into the
permanent/temporary mapping models.

Design decisions:
- Uses 'raw' schema to separate from transactional tables
- Includes all metadata for debugging and auditing (row_number, column_index, etc.)
- Does NOT use a foreign key to suppliers table (raw data shouldn't have constraints)
- mapping_type allows dbt to filter into permanent vs temporary mappings
- supplier_item_ids is the key column for joining to invoice_items.item
"""

from sqlalchemy import Column, Integer, String, DateTime, text
from sqlalchemy.sql import func
from mpi_backend.database import Base


class GoogleSheetMappingRaw(Base):
    """
    Raw extracted data from Google Sheets item mapping spreadsheet.

    This is a staging table that dbt reads from to create:
    - int__permanent_mappings (mapping_type = 'permanent')
    - int__temporary_mappings (mapping_type = 'temporary')

    The table is truncated and reloaded on each sync to ensure clean data.
    """
    __tablename__ = 'raw_google_sheet_mappings'
    __table_args__ = {'schema': 'raw'}

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Sheet identification
    sheet_title = Column(String, nullable=False, comment="Category/tab name from Google Sheets (e.g., 'AIR FITTINGS')")
    google_sheet_name = Column(String, nullable=True, comment="Name of the Google Sheet file")
    sheet_id = Column(String, nullable=True, comment="Google Sheets gid for tracking across renames")

    # MPI mapping data (the core mapping info)
    mpi_code = Column(String, nullable=True, comment="Internal MPI item code (e.g., 'FWCR4030')")
    description = Column(String, nullable=True, comment="MPI description (e.g., 'STD CONC REDUCERS')")

    # Supplier info
    supplier = Column(String, nullable=True, comment="Supplier name (e.g., 'World Wide Plumbing')")
    supplier_id = Column(Integer, nullable=True, comment="Supplier ID (reference only, not FK)")

    # Supplier item codes (the key for joining)
    supplier_item_ids = Column(String, nullable=True, comment="Supplier's item code with suffix (e.g., 'WELC4030-Y')")
    original_supplier_item_id = Column(String, nullable=True, comment="Original item code before processing")

    # Debugging/audit metadata
    row_number = Column(Integer, nullable=True, comment="Row number in the Google Sheet")
    column_index = Column(Integer, nullable=True, comment="Column index in the Google Sheet")

    # Classification
    mapping_type = Column(String, nullable=False, comment="permanent, temporary, or invalid")
    validation_status = Column(String, nullable=True, comment="Validation result (valid_permanent, valid_temporary, etc.)")

    # Timestamps
    extraction_timestamp = Column(DateTime, nullable=True, comment="When the data was extracted from Google Sheets")
    loaded_at = Column(DateTime, server_default=func.now(), comment="When the data was loaded into this table")

    def __repr__(self):
        return f"<GoogleSheetMappingRaw(mpi_code='{self.mpi_code}', supplier_item='{self.supplier_item_ids}', type='{self.mapping_type}')>"
