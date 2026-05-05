import logging
from sqlalchemy.orm import Session
from typing import List, Optional

from mpi_backend.database.dao.project_estimate_finish_items_dao import ProjectEstimateFinishItemsDAO
from mpi_backend.database.models.ProjectEstimateFinishItems import ProjectEstimateFinishItems

logger = logging.getLogger(__name__)


class ProjectEstimateFinishItemsController:
    """
    Controller for ProjectEstimateFinishItems.
    Handles business logic, validation, and logging.
    """

    def __init__(self, db: Session):
        self.db = db
        self.dao = ProjectEstimateFinishItemsDAO(db)

    def get_items_by_project(self, project_estimate_id: int) -> List[ProjectEstimateFinishItems]:
        """
        Get finish items by project.
        """
        try:
            items = self.dao.get_by_project_id(project_estimate_id)
            if not items:
                raise ValueError(f"No finish items for project {project_estimate_id}")
            return items
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching finish items for project {project_estimate_id}: {e}")
            raise

    def get_item_by_id(self, item_id: int) -> ProjectEstimateFinishItems:
        """
        Get finish item by ID.
        """
        try:
            item = self.dao.get_by_id(item_id)
            if not item:
                raise ValueError(f"Finish item {item_id} not found")
            return item
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching finish item {item_id}: {e}")
            raise

    def create_item(
        self,
        name: str,
        price: str,
        qty: str,
        amount: str,
        project_estimate_id: int,
    ) -> ProjectEstimateFinishItems:
        """
        Create finish item.
        """
        try:
            return self.dao.create(name, price, qty, amount, project_estimate_id)
        except Exception as e:
            logger.error(f"Error creating finish item: {e}")
            raise

    def update_item(
        self,
        item_id: int,
        name: Optional[str],
        price: Optional[str],
        qty: Optional[str],
        amount: Optional[str],
    ) -> ProjectEstimateFinishItems:
        """
        Update finish item.
        """
        try:
            updated = self.dao.update(item_id, name, price, qty, amount)
            if not updated:
                raise ValueError(f"Finish item {item_id} not found")
            return updated
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error updating finish item {item_id}: {e}")
            raise

    def delete_item(self, item_id: int) -> bool:
        """
        Delete finish item.
        """
        try:
            success = self.dao.delete(item_id)
            if not success:
                raise ValueError(f"Finish item {item_id} not found")
            return success
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting finish item {item_id}: {e}")
            raise
