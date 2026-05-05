"""
Controller for managing Google Sheet metadata.

This controller provides CRUD operations for the GoogleSheetMetadata model,
allowing us to track sheet IDs and their canonical names.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from mpi_backend.database.models.GoogleSheetMetadata import (
    GoogleSheetMetadata
)

logger = logging.getLogger(__name__)


class GoogleSheetMetadataController:
    """Controller for Google Sheet metadata operations."""

    def __init__(self, db_session: Session):
        """
        Initialize the controller with a database session.

        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session

    def upsert_sheet_metadata(
        self,
        sheet_id: str,
        sheet_name: str,
        spreadsheet_id: str
    ) -> GoogleSheetMetadata:
        """
        Insert or update a single sheet metadata record.

        Args:
            sheet_id: Google Sheets gid
            sheet_name: Current canonical name of the sheet
            spreadsheet_id: Parent Google Sheet ID

        Returns:
            The created or updated GoogleSheetMetadata instance
        """
        try:
            # Use PostgreSQL INSERT ... ON CONFLICT for efficient upsert
            stmt = insert(GoogleSheetMetadata).values(
                sheet_id=sheet_id,
                sheet_name=sheet_name,
                spreadsheet_id=spreadsheet_id,
                last_synced_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            ).on_conflict_do_update(
                constraint='uq_spreadsheet_sheet',
                set_={
                    'sheet_name': sheet_name,
                    'last_synced_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                }
            ).returning(GoogleSheetMetadata)

            result = self.db.execute(stmt)
            self.db.commit()
            
            metadata = result.scalar_one()
            logger.info(f"Upserted sheet metadata: {sheet_id} -> {sheet_name}")
            return metadata

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error upserting sheet metadata for {sheet_id}: {str(e)}")
            raise

    def bulk_upsert_sheets(
        self,
        sheets_list: List[Dict[str, str]],
        spreadsheet_id: str
    ) -> int:
        """
        Bulk upsert multiple sheet metadata records.

        Args:
            sheets_list: List of dictionaries with 'title' and 'gid' keys
            spreadsheet_id: Parent Google Sheet ID

        Returns:
            Number of records upserted
        """
        try:
            count = 0
            for sheet in sheets_list:
                sheet_id = sheet.get('gid')
                sheet_name = sheet.get('title')
                
                if not sheet_id or not sheet_name:
                    logger.warning(f"Skipping invalid sheet entry: {sheet}")
                    continue

                self.upsert_sheet_metadata(
                    sheet_id=sheet_id,
                    sheet_name=sheet_name,
                    spreadsheet_id=spreadsheet_id
                )
                count += 1

            logger.info(f"Bulk upserted {count} sheet metadata records")
            return count

        except Exception as e:
            logger.error(f"Error in bulk upsert: {str(e)}")
            raise

    def get_canonical_name(self, sheet_id: str) -> Optional[str]:
        """
        Look up the current canonical name for a sheet ID.

        Args:
            sheet_id: Google Sheets gid

        Returns:
            The canonical sheet name, or None if not found
        """
        try:
            metadata = self.db.query(GoogleSheetMetadata).filter(
                GoogleSheetMetadata.sheet_id == sheet_id
            ).first()

            if metadata:
                return metadata.sheet_name
            else:
                logger.warning(f"No metadata found for sheet_id: {sheet_id}")
                return None

        except Exception as e:
            logger.error(f"Error getting canonical name for {sheet_id}: {str(e)}")
            return None

    def get_all_sheet_mappings(
        self,
        spreadsheet_id: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Get all sheet ID to name mappings.

        Args:
            spreadsheet_id: Optional filter by spreadsheet ID

        Returns:
            Dictionary mapping sheet_id to sheet_name
        """
        try:
            query = self.db.query(GoogleSheetMetadata)
            
            if spreadsheet_id:
                query = query.filter(
                    GoogleSheetMetadata.spreadsheet_id == spreadsheet_id
                )

            results = query.all()
            
            mappings = {
                metadata.sheet_id: metadata.sheet_name
                for metadata in results
            }

            logger.info(f"Retrieved {len(mappings)} sheet mappings")
            return mappings

        except Exception as e:
            logger.error(f"Error getting all sheet mappings: {str(e)}")
            return {}

    def get_by_sheet_id(self, sheet_id: str) -> Optional[GoogleSheetMetadata]:
        """
        Get a GoogleSheetMetadata record by sheet ID.

        Args:
            sheet_id: Google Sheets gid

        Returns:
            GoogleSheetMetadata instance or None
        """
        try:
            return self.db.query(GoogleSheetMetadata).filter(
                GoogleSheetMetadata.sheet_id == sheet_id
            ).first()

        except Exception as e:
            logger.error(f"Error getting metadata by sheet_id {sheet_id}: {str(e)}")
            return None

    def delete_sheet_metadata(self, sheet_id: str, spreadsheet_id: str) -> bool:
        """
        Delete a sheet metadata record.

        Args:
            sheet_id: Google Sheets gid
            spreadsheet_id: Parent Google Sheet ID

        Returns:
            True if deleted, False otherwise
        """
        try:
            result = self.db.query(GoogleSheetMetadata).filter(
                GoogleSheetMetadata.sheet_id == sheet_id,
                GoogleSheetMetadata.spreadsheet_id == spreadsheet_id
            ).delete()

            self.db.commit()
            
            if result > 0:
                logger.info(f"Deleted sheet metadata for {sheet_id}")
                return True
            else:
                logger.warning(f"No metadata found to delete for {sheet_id}")
                return False

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting sheet metadata for {sheet_id}: {str(e)}")
            return False

    def get_all_by_spreadsheet(
        self,
        spreadsheet_id: str
    ) -> List[GoogleSheetMetadata]:
        """
        Get all sheet metadata for a specific spreadsheet.

        Args:
            spreadsheet_id: Parent Google Sheet ID

        Returns:
            List of GoogleSheetMetadata instances
        """
        try:
            return self.db.query(GoogleSheetMetadata).filter(
                GoogleSheetMetadata.spreadsheet_id == spreadsheet_id
            ).order_by(GoogleSheetMetadata.sheet_name).all()

        except Exception as e:
            logger.error(
                f"Error getting all metadata for spreadsheet {spreadsheet_id}: {str(e)}"
            )
            return []

