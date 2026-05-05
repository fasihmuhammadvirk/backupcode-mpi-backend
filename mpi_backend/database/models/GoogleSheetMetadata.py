from sqlalchemy import Column, String, Integer, DateTime, UniqueConstraint, Index
from mpi_backend.database import Base
from datetime import datetime


class GoogleSheetMetadata(Base):
    """
    Stores metadata about Google Sheets to maintain canonical sheet names.
    This allows us to track sheet renames and maintain consistent naming across the application.
    """
    __tablename__ = 'google_sheet_metadata'

    id = Column(Integer, primary_key=True)
    sheet_id = Column(String, nullable=False)  # The Google Sheets gid
    sheet_name = Column(String, nullable=False)  # Current canonical name
    spreadsheet_id = Column(String, nullable=False)  # Parent Google Sheet ID
    last_synced_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('spreadsheet_id', 'sheet_id', name='uq_spreadsheet_sheet'),
        Index('idx_sheet_id', 'sheet_id'),
        Index('idx_spreadsheet_id', 'spreadsheet_id'),
    )

    def __repr__(self):
        return f"<GoogleSheetMetadata(sheet_id='{self.sheet_id}', sheet_name='{self.sheet_name}')>"

