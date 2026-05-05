import logging
from sqlalchemy.orm import Session
from typing import List, Optional

from mpi_backend.database.dao.project_estimate_finish_quick_items_dao import (
    ProjectEstimateFinishQuickItemsDAO,
)
from mpi_backend.database.models.ProjectEstimateFinishQuickItems import (
    ProjectEstimateFinishQuickItems,
)

logger = logging.getLogger(__name__)


class ProjectEstimateFinishQuickItemsController:
    """
    Controller for ProjectEstimateFinishQuickItems.
    Handles validation, logging, and business logic.
    """

    def __init__(self, db: Session):
        self.db = db
        self.dao = ProjectEstimateFinishQuickItemsDAO(db)

    def get_all_items(self) -> List[ProjectEstimateFinishQuickItems]:
        """
        Get all finish quick items.
        """
        try:
            return self.dao.get_all()
        except Exception as e:
            logger.error(f"Error fetching finish quick items: {e}")
            raise

    def get_item_by_id(self, item_id: int) -> ProjectEstimateFinishQuickItems:
        """
        Get finish quick item by ID.
        """
        try:
            item = self.dao.get_by_id(item_id)
            if not item:
                raise ValueError(f"Finish quick item {item_id} not found")
            return item
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching finish quick item {item_id}: {e}")
            raise

    def create_item(self, name: str, price: str) -> ProjectEstimateFinishQuickItems:
        """
        Create finish quick item.
        """
        try:
            return self.dao.create(name, price)
        except Exception as e:
            logger.error(f"Error creating finish quick item: {e}")
            raise

    def update_item(
        self,
        item_id: int,
        name: Optional[str],
        price: Optional[str],
    ) -> ProjectEstimateFinishQuickItems:
        """
        Update finish quick item.
        """
        try:
            updated = self.dao.update(item_id, name, price)
            if not updated:
                raise ValueError(f"Finish quick item {item_id} not found")
            return updated
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error updating finish quick item {item_id}: {e}")
            raise

    def delete_item(self, item_id: int) -> bool:
        """
        Delete finish quick item.
        """
        try:
            success = self.dao.delete(item_id)
            if not success:
                raise ValueError(f"Finish quick item {item_id} not found")
            return success
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting finish quick item {item_id}: {e}")
            raise
            