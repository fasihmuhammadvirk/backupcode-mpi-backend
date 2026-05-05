import logging
from sqlalchemy.orm import Session
from typing import List, Optional

from mpi_backend.database.dao.project_estimate_point_quick_items import (
    ProjectEstimatePointQuickItemsDAO,
)
from mpi_backend.database.models.ProjectEstimatePointQuickItems import (
    ProjectEstimatePointQuickItems,
)

logger = logging.getLogger(__name__)


class ProjectEstimatePointQuickItemsController:
    """
    Controller for ProjectEstimatePointQuickItems.
    Handles validation, logging, and business logic.
    """

    def __init__(self, db: Session):
        self.db = db
        self.dao = ProjectEstimatePointQuickItemsDAO(db)

    def get_all_items(self) -> List[ProjectEstimatePointQuickItems]:
        """
        Get all quick point items.
        """
        try:
            return self.dao.get_all()
        except Exception as e:
            logger.error(f"Error fetching quick point items: {e}")
            raise

    def get_item_by_id(self, item_id: int) -> ProjectEstimatePointQuickItems:
        """
        Get item by ID.
        """
        try:
            item = self.dao.get_by_id(item_id)
            if not item:
                raise ValueError(f"Quick item {item_id} not found")
            return item
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching quick point item {item_id}: {e}")
            raise

    def create_item(self, name: str, amount: str) -> ProjectEstimatePointQuickItems:
        """
        Create quick point item.
        """
        try:
            return self.dao.create(name, amount)
        except Exception as e:
            logger.error(f"Error creating quick point item: {e}")
            raise

    def update_item(
        self,
        item_id: int,
        name: Optional[str],
        amount: Optional[str],
    ) -> ProjectEstimatePointQuickItems:
        """
        Update quick point item.
        """
        try:
            updated = self.dao.update(item_id, name, amount)
            if not updated:
                raise ValueError(f"Quick item {item_id} not found")
            return updated
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error updating quick point item {item_id}: {e}")
            raise

    def delete_item(self, item_id: int) -> bool:
        """
        Delete quick point item.
        """
        try:
            success = self.dao.delete(item_id)
            if not success:
                raise ValueError(f"Quick item {item_id} not found")
            return success
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting quick point item {item_id}: {e}")
            raise
