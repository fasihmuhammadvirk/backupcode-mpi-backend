import logging
from sqlalchemy.orm import Session
from typing import List, Optional

from mpi_backend.database.dao.project_estimate_fixed_quick_items_dao import (
    ProjectEstimateFixedQuickItemsDAO,
)
from mpi_backend.database.models.ProjectEstimateFixedQuickItems import (
    ProjectEstimateFixedQuickItems,
)

logger = logging.getLogger(__name__)


class ProjectEstimateFixedQuickItemsController:
    """
    Controller layer for ProjectEstimateFixedQuickItems.

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
        self.dao = ProjectEstimateFixedQuickItemsDAO(db)

    def create_item(self, name: str, amount: int) -> ProjectEstimateFixedQuickItems:
        """
        Create a new quick item.

        Args:
            name (str): Item name.
            amount (int): Item amount.

        Returns:
            ProjectEstimateFixedQuickItems: Created item.
        """
        try:
            return self.dao.create(name, amount)
        except Exception as e:
            logger.error(f"Error creating quick item: {e}")
            raise

    def get_all_items(self) -> List[ProjectEstimateFixedQuickItems]:
        """
        Fetch all quick items.

        Returns:
            List[ProjectEstimateFixedQuickItems]
        """
        try:
            return self.dao.get_all()
        except Exception as e:
            logger.error(f"Error fetching quick items: {e}")
            raise

    def get_item_by_id(self, item_id: int) -> ProjectEstimateFixedQuickItems:
        """
        Fetch quick item by ID.

        Args:
            item_id (int): Item ID.

        Returns:
            ProjectEstimateFixedQuickItems

        Raises:
            ValueError: If item not found.
        """
        try:
            item = self.dao.get_by_id(item_id)
            if not item:
                raise ValueError(f"Item {item_id} not found")
            return item
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching quick item {item_id}: {e}")
            raise

    def update_item(
        self,
        item_id: int,
        name: Optional[str],
        amount: Optional[int],
    ) -> ProjectEstimateFixedQuickItems:
        """
        Update a quick item.

        Args:
            item_id (int): Item ID
            name (Optional[str]): New name
            amount (Optional[int]): New amount

        Returns:
            ProjectEstimateFixedQuickItems

        Raises:
            ValueError: If item not found.
        """
        try:
            updated = self.dao.update(item_id, name, amount)
            if not updated:
                raise ValueError(f"Item {item_id} not found")
            return updated
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error updating quick item {item_id}: {e}")
            raise

    def delete_item(self, item_id: int) -> bool:
        """
        Delete a quick item.

        Args:
            item_id (int): Item ID

        Returns:
            bool

        Raises:
            ValueError: If item not found.
        """
        try:
            success = self.dao.delete(item_id)
            if not success:
                raise ValueError(f"Item {item_id} not found")
            return success
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting quick item {item_id}: {e}")
            raise
