from mpi_backend.database.models import TempItemMapping
import pandas as pd
from typing import Dict, List, Any
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


class TemporaryItemMappingController:
    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self) -> Session:
        """Get a database session object, whether db_context is a factory or 
        session."""
        # Check if it is already a session instance (has query, add, commit
        # methods)
        if (hasattr(self.db_context, 'query') and
                hasattr(self.db_context, 'commit')):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

    def create_temporary_mapping(
        self,
        original_item: str,
        original_description: str,
        sheet_name: str
    ) -> bool:
        """
        Create a new temporary mapping.

        Args:
            original_item: The original item code/identifier
            original_description: Description of the item
            sheet_name: Name of the sheet this mapping belongs to

        Returns:
            bool: True if successfully created, False otherwise
        """
        try:
            db = self._get_db_session()

            # Check if mapping already exists
            existing_mapping = db.query(TempItemMapping).filter(
                TempItemMapping.original_item == original_item,
                TempItemMapping.sheet_name == sheet_name
            ).first()

            if existing_mapping:
                # Update existing mapping
                existing_mapping.original_description = original_description
                logger.debug(
                    f"Updated existing temporary mapping: "
                    f"{original_item} -> {sheet_name}"
                )
            else:
                # Create new mapping
                temp_mapping = TempItemMapping(
                    original_item=original_item,
                    original_description=original_description,
                    sheet_name=sheet_name
                )
                db.add(temp_mapping)
                logger.debug(
                    f"Created new temporary mapping: "
                    f"{original_item} -> {sheet_name}"
                )

            db.commit()
            return True

        except Exception as e:
            logger.error(
                f"Error creating temporary mapping: {str(e)}"
            )
            try:
                db.rollback()
            except Exception:
                pass
            return False

    def get_temp_items_mappings(self):
        """
        Get all temporary item mappings.

        Returns:
            DataFrame with temporary mappings
        """
        db = self._get_db_session()
        query_result = db.query(TempItemMapping).all()

        data = [
            (item.original_item,
             item.original_description,
             item.sheet_name)
            for item in query_result
        ]
        columns = ['original_item', 'original_description', 'sheet_name']
        temp_items_mappings = pd.DataFrame(data, columns=columns)
        return temp_items_mappings

    def get_temp_mappings_by_sheet(self, sheet_name: str) -> List[
        Dict[str, Any]
    ]:
        """
        Get temporary mappings for a specific sheet.

        Args:
            sheet_name: Name of the sheet to filter by

        Returns:
            List of temporary mapping dictionaries
        """
        db = self._get_db_session()
        query_result = db.query(TempItemMapping).filter(
            TempItemMapping.sheet_name == sheet_name
        ).all()

        return [
            {
                "id": item.id,
                "original_item": item.original_item,
                "original_description": item.original_description,
                "sheet_name": item.sheet_name,
                "created_at": item.created_at,
                "updated_at": item.updated_at
            }
            for item in query_result
        ]

    def clear_temp_mappings_by_sheet(self, sheet_name: str) -> int:
        """
        Clear temporary mappings for a specific sheet.

        Args:
            sheet_name: Name of the sheet to clear mappings for

        Returns:
            Number of mappings deleted
        """
        db = self._get_db_session()
        deleted_count = db.query(TempItemMapping).filter(
            TempItemMapping.sheet_name == sheet_name
        ).delete()

        db.commit()
        logger.info(
            f"Cleared {deleted_count} temporary mappings for "
            f"sheet: {sheet_name}"
        )
        return deleted_count

    def get_mapping_stats(self) -> Dict[str, Any]:
        """
        Get statistics about temporary mappings.

        Returns:
            Dictionary with mapping statistics
        """
        db = self._get_db_session()
        total_mappings = db.query(TempItemMapping).count()

        # Get unique sheet names
        sheet_names = db.query(TempItemMapping.sheet_name).distinct().all()
        unique_sheets = [name[0] for name in sheet_names if name[0]]

        # Get mappings per sheet
        sheet_counts = {}
        for sheet_name in unique_sheets:
            count = db.query(TempItemMapping).filter(
                TempItemMapping.sheet_name == sheet_name
            ).count()
            sheet_counts[sheet_name] = count
        return {
            "total_mappings": total_mappings,
            "unique_sheets": len(unique_sheets),
            "sheet_names": unique_sheets,
            "mappings_per_sheet": sheet_counts
        }
