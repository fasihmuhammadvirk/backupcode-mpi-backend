import logging
from sqlalchemy.orm import Session
from typing import List, Optional

from mpi_backend.database.dao.project_estimate_fixed_items_dao import ProjectEstimateFixedItemsDAO
from mpi_backend.database.models.ProjectEstimateFixedItems import ProjectEstimateFixedItems

logger = logging.getLogger(__name__)


class ProjectEstimateFixedItemsController:
    """
    Controller layer for ProjectEstimateFixedItems.

    This class acts as the business-logic layer between the FastAPI routes
    and the DAO. It is responsible for validation, logging, and raising
    meaningful exceptions while delegating database operations to the DAO.
    """

    def __init__(self, db: Session):
        """
        Initialize controller with database session.

        Args:
            db (Session): SQLAlchemy database session.
        """
        self.db = db
        self.dao = ProjectEstimateFixedItemsDAO(db)

    def create_item(
        self,
        name: str,
        price: str,
        project_estimation_id: int,
    ) -> ProjectEstimateFixedItems:
        """
        Create a new project estimate fixed item.

        Args:
            name (str): Name of the fixed item.
            price (str): Price of the fixed item.
            project_estimation_id (int): Associated project estimation ID.

        Returns:
            ProjectEstimateFixedItems: The created fixed item.

        Raises:
            Exception: If creation fails.
        """
        try:
            return self.dao.create(name, price, project_estimation_id)
        except Exception as e:
            logger.error(f"Error creating fixed item: {e}")
            raise

    def get_item_by_id(self, item_id: int) -> ProjectEstimateFixedItems:
        """
        Retrieve a fixed item by its ID.

        Args:
            item_id (int): ID of the fixed item.

        Returns:
            ProjectEstimateFixedItems: The requested fixed item.

        Raises:
            ValueError: If item is not found.
            Exception: If database error occurs.
        """
        try:
            item = self.dao.get_by_id(item_id)
            if not item:
                raise ValueError(f"Item with id {item_id} not found")
            return item
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching item {item_id}: {e}")
            raise

    def get_items_by_project(self, project_id: int) -> List[ProjectEstimateFixedItems]:
        """
        Retrieve all fixed items for a specific project estimation.

        Args:
            project_id (int): Project estimation ID.

        Returns:
            List[ProjectEstimateFixedItems]: List of related fixed items.

        Raises:
            ValueError: If no items found.
            Exception: If database error occurs.
        """
        try:
            items = self.dao.get_by_project_id(project_id)
            return items
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching items for project {project_id}: {e}")
            raise

    def update_item(
        self,
        item_id: int,
        name: Optional[str],
        price: Optional[str],
        project_estimation_id: Optional[int],
    ) -> ProjectEstimateFixedItems:
        """
        Update an existing project estimate fixed item.

        Args:
            item_id (int): ID of the item to update.
            name (Optional[str]): New name (optional).
            price (Optional[str]): New price (optional).
            project_estimation_id (Optional[int]): New project estimation ID (optional).

        Returns:
            ProjectEstimateFixedItems: Updated item.

        Raises:
            ValueError: If item not found.
            Exception: If update fails.
        """
        try:
            updated = self.dao.update(item_id, name, price, project_estimation_id)
            if not updated:
                raise ValueError(f"Item with id {item_id} not found")
            return updated
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error updating item {item_id}: {e}")
            raise

    def delete_item(self, item_id: int) -> bool:
        """
        Delete a project estimate fixed item by ID.

        Args:
            item_id (int): ID of the item to delete.

        Returns:
            bool: True if deletion was successful.

        Raises:
            ValueError: If item not found.
            Exception: If deletion fails.
        """
        try:
            success = self.dao.delete(item_id)
            if not success:
                raise ValueError(f"Item with id {item_id} not found")
            return success
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting item {item_id}: {e}")
            raise
