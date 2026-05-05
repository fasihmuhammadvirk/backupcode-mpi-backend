import logging
from sqlalchemy.orm import Session
from typing import List, Optional

from mpi_backend.database.dao.project_estimate_point_items_dao import ProjectEstimatePointItemsDAO
from mpi_backend.database.models.ProjectEstimatePointItems import ProjectEstimatePointItems

logger = logging.getLogger(__name__)


class ProjectEstimatePointItemsController:
    """
    Controller layer for ProjectEstimatePointItems.

    Handles validation, logging, and business logic while delegating
    database operations to the DAO.
    """

    def __init__(self, db: Session):
        """
        Initialize controller.

        Args:
            db (Session): Database session.
        """
        self.db = db
        self.dao = ProjectEstimatePointItemsDAO(db)

    def get_items_by_project(self, project_estimate_id: int) -> List[ProjectEstimatePointItems]:
        """
        Retrieve point items by project estimate ID.

        Args:
            project_estimate_id (int): Project estimate ID.

        Returns:
            List[ProjectEstimatePointItems]

        Raises:
            ValueError: If no items found for the project.
        """
        try:
            items = self.dao.get_by_project_estimate_id(project_estimate_id)
            if not items:
                raise ValueError(f"No point items found for project {project_estimate_id}")
            return items
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching point items for project {project_estimate_id}: {e}")
            raise

    def get_item_by_id(self, item_id: int) -> ProjectEstimatePointItems:
        """
        Retrieve a point item by ID.

        Args:
            item_id (int): Point item ID.

        Returns:
            ProjectEstimatePointItems

        Raises:
            ValueError: If item not found.
        """
        try:
            item = self.dao.get_by_id(item_id)
            if not item:
                raise ValueError(f"Point item {item_id} not found")
            return item
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching point item {item_id}: {e}")
            raise

    def create_item(
        self,
        name: str,
        pts: str,
        qty: str,
        amount: str,
        project_estimate_id: int,
    ) -> ProjectEstimatePointItems:
        """
        Create a point item.

        Args:
            name (str)
            pts (str)
            qty (str)
            amount (str)
            project_estimate_id (int)

        Returns:
            ProjectEstimatePointItems
        """
        try:
            return self.dao.create(name, pts, qty, amount, project_estimate_id)
        except Exception as e:
            logger.error(f"Error creating point item: {e}")
            raise

    def update_item(
        self,
        item_id: int,
        name: Optional[str],
        pts: Optional[str],
        qty: Optional[str],
        amount: Optional[str],
        project_estimate_id: Optional[int],
    ) -> ProjectEstimatePointItems:
        """
        Update a point item.

        Args:
            item_id (int)
            name (Optional[str])
            pts (Optional[str])
            qty (Optional[str])
            amount (Optional[str])
            project_estimate_id (Optional[int])

        Returns:
            ProjectEstimatePointItems

        Raises:
            ValueError: If item not found.
        """
        try:
            updated = self.dao.update(item_id, name, pts, qty, amount, project_estimate_id)
            if not updated:
                raise ValueError(f"Point item {item_id} not found")
            return updated
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error updating point item {item_id}: {e}")
            raise

    def delete_item(self, item_id: int) -> bool:
        """
        Delete a point item.

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
                raise ValueError(f"Point item {item_id} not found")
            return success
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting point item {item_id}: {e}")
            raise
