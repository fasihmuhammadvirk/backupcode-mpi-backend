import logging
from sqlalchemy.orm import Session
from typing import List, Optional

from mpi_backend.database.dao.project_estimate_sub_items_dao import ProjectEstimateSubItemDAO
from mpi_backend.database.models.ProjectEstimateSubItem import ProjectEstimateSubItem
from mpi_backend.database.dao.project_estimate_sub_items_dao import EstimateType

logger = logging.getLogger(__name__)


class ProjectEstimateSubItemController:
    """
    Controller layer for ProjectEstimateSubItem.

    Handles business logic, validation, and logging while delegating
    database operations to the DAO.
    """

    def __init__(self, db: Session):
        """
        Initialize controller.

        Args:
            db (Session): Database session.
        """
        self.db = db
        self.dao = ProjectEstimateSubItemDAO(db)

    def get_items_by_project(self, project_estimate_id: int) -> List[ProjectEstimateSubItem]:
        """
        Retrieve sub items by project estimation ID.

        Args:
            project_estimate_id (int)

        Returns:
            List[ProjectEstimateSubItem]
        """
        try:
            return self.dao.get_by_project_estimate_id(project_estimate_id)
        except Exception as e:
            logger.error(f"Error fetching sub items for project {project_estimate_id}: {e}")
            raise

    def get_item_by_id(self, item_id: int) -> ProjectEstimateSubItem:
        """
        Retrieve a sub item by ID.

        Args:
            item_id (int)

        Returns:
            ProjectEstimateSubItem

        Raises:
            ValueError: If item not found.
        """
        try:
            item = self.dao.get_by_id(item_id)
            if not item:
                raise ValueError(f"Sub item {item_id} not found")
            return item
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching sub item {item_id}: {e}")
            raise

    def create_item(
        self,
        name: str,
        price: str,
        type: EstimateType,
        project_estimate_id: int,
    ) -> ProjectEstimateSubItem:
        """
        Create a new sub item.

        Args:
            name (str)
            price (str)
            type (EstimateType)
            project_estimate_id (int)

        Returns:
            ProjectEstimateSubItem
        """
        try:
            return self.dao.create(name, price, type, project_estimate_id)
        except Exception as e:
            logger.error(f"Error creating sub item: {e}")
            raise

    def update_item(
        self,
        item_id: int,
        name: Optional[str],
        price: Optional[str],
        type: Optional[EstimateType],
        project_estimate_id: Optional[int],
    ) -> ProjectEstimateSubItem:
        """
        Update a sub item.

        Args:
            item_id (int)
            name (Optional[str])
            price (Optional[str])
            type (Optional[EstimateType])
            project_estimate_id (Optional[int])

        Returns:
            ProjectEstimateSubItem

        Raises:
            ValueError: If item not found.
        """
        try:
            updated = self.dao.update(item_id, name, price, type, project_estimate_id)
            if not updated:
                raise ValueError(f"Sub item {item_id} not found")
            return updated
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error updating sub item {item_id}: {e}")
            raise

    def delete_item(self, item_id: int) -> bool:
        """
        Delete a sub item.

        Args:
            item_id (int)

        Returns:
            bool

        Raises:
            ValueError: If item not found.
        """
        try:
            success = self.dao.delete(item_id)
            if not success:
                raise ValueError(f"Sub item {item_id} not found")
            return success
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting sub item {item_id}: {e}")
            raise
