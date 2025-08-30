from mpi_backend.database.models import TempItemMapping
import pandas as pd
from typing import Dict, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import logging
from mpi_backend.utils.mapping_stats_manager import MappingStatsManager

logger = logging.getLogger(__name__)


class TemporaryItemMappingController:
    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self) -> AsyncSession:
        """Get a database session object, whether db_context is a factory or 
        session."""
        # Check if it is already a session instance (has query, add, commit
        # methods)
        if (hasattr(self.db_context, 'query') and
                hasattr(self.db_context, 'commit')):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

    async def create_temporary_mapping(
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
            result = await db.execute(
                select(TempItemMapping).where(
                    TempItemMapping.original_item == original_item,
                    TempItemMapping.sheet_name == sheet_name
                )
            )
            existing_mapping = result.scalar_one_or_none()

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

            await db.commit()
            return True

        except Exception as e:
            logger.error(
                f"Error creating temporary mapping: {str(e)}"
            )
            try:
                await db.rollback()
            except Exception:
                pass
            return False

    async def get_temp_items_mappings(self):
        """
        Get all temporary item mappings.

        Returns:
            DataFrame with temporary mappings
        """
        db = self._get_db_session()
        result = await db.execute(select(TempItemMapping))
        query_result = result.scalars().all()

        data = [
            (item.original_item,
             item.original_description,
             item.sheet_name)
            for item in query_result
        ]
        columns = ['original_item', 'original_description', 'sheet_name']
        temp_items_mappings = pd.DataFrame(data, columns=columns)
        return temp_items_mappings

    async def get_temp_mappings_by_sheet(self, sheet_name: str) -> List[
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
        result = await db.execute(
            select(TempItemMapping).where(
                TempItemMapping.sheet_name == sheet_name
            )
        )
        query_result = result.scalars().all()

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

    async def clear_temp_mappings_by_sheet(self, sheet_name: str) -> int:
        """
        Clear temporary mappings for a specific sheet.

        Args:
            sheet_name: Name of the sheet to clear mappings for

        Returns:
            Number of mappings deleted
        """
        db = self._get_db_session()
        result = await db.execute(
            select(TempItemMapping).where(
                TempItemMapping.sheet_name == sheet_name
            )
        )
        deleted_count = len(result.scalars().all())
        
        # Delete the mappings
        await db.execute(
            delete(TempItemMapping).where(
                TempItemMapping.sheet_name == sheet_name
            )
        )

        await db.commit()
        logger.info(
            f"Cleared {deleted_count} temporary mappings for "
            f"sheet: {sheet_name}"
        )
        return deleted_count

    async def get_mapping_stats(self) -> Dict[str, Any]:
        """
        Get statistics about temporary mappings.

        Returns:
            Dictionary with mapping statistics
        """
        db = self._get_db_session()
        result = await db.execute(select(TempItemMapping))
        total_mappings = len(result.scalars().all())

        # Get unique sheet names
        result = await db.execute(
            select(TempItemMapping.sheet_name).distinct()
        )
        sheet_names = result.scalars().all()
        unique_sheets = [name for name in sheet_names if name]

        # Get mappings per sheet
        sheet_counts = {}
        for sheet_name in unique_sheets:
            result = await db.execute(
                select(TempItemMapping).where(
                    TempItemMapping.sheet_name == sheet_name
                )
            )
            count = len(result.scalars().all())
            sheet_counts[sheet_name] = count

        stats = {
            "total_mappings": total_mappings,
            "unique_sheets": len(unique_sheets),
            "sheet_names": unique_sheets,
            "mappings_per_sheet": sheet_counts
        }

        # Update stats in the JSON file
        stats_manager = MappingStatsManager()
        stats_manager.update_temp_mapping_stats(stats)

        return stats
