from sqlalchemy.orm import Session
from typing import List, Optional
from mpi_backend.database.models.ProjectEstimateFixedQuickItems import ProjectEstimateFixedQuickItems

class ProjectEstimateFixedQuickItemsDAO:
    """
    Data Access Object (DAO) for interacting with the ProjectEstimateFixedQuickItems model.
    
    Provides methods for CRUD operations on the 'project_estimate_fixed_quick_items' table.
    """

    def __init__(self, db_session: Session):
        """
        Initializes the DAO with the database session.

        Args:
            db_session (Session): The database session for making queries.
        """
        self.db_session = db_session

    def get_all(self) -> List[ProjectEstimateFixedQuickItems]:
        """
        Fetches all project estimate fixed quick items from the database.

        Returns:
            List[ProjectEstimateFixedQuickItems]: A list of all project estimate fixed quick items.
        """
        return self.db_session.query(ProjectEstimateFixedQuickItems).all()

    def get_by_id(self, item_id: int) -> Optional[ProjectEstimateFixedQuickItems]:
        """
        Fetches a project estimate fixed quick item by its ID.

        Args:
            item_id (int): The ID of the project estimate fixed quick item to retrieve.

        Returns:
            Optional[ProjectEstimateFixedQuickItems]: The project estimate fixed quick item, or None if not found.
        """
        return self.db_session.query(ProjectEstimateFixedQuickItems).filter(ProjectEstimateFixedQuickItems.id == item_id).first()

    def create(self, name: str, amount: int) -> ProjectEstimateFixedQuickItems:
        """
        Creates a new project estimate fixed quick item and saves it to the database.

        Args:
            name (str): The name of the quick item.
            amount (int): The amount of the quick item.

        Returns:
            ProjectEstimateFixedQuickItems: The created project estimate fixed quick item.
        """
        new_item = ProjectEstimateFixedQuickItems(name=name, amount=amount)
        self.db_session.add(new_item)
        self.db_session.commit()
        self.db_session.refresh(new_item)
        return new_item

    def update(self, item_id: int, name: Optional[str], amount: Optional[int]) -> Optional[ProjectEstimateFixedQuickItems]:
        """
        Updates an existing project estimate fixed quick item with the provided values.

        Args:
            item_id (int): The ID of the project estimate fixed quick item to update.
            name (Optional[str]): The new name for the item (optional).
            amount (Optional[int]): The new amount for the item (optional).

        Returns:
            Optional[ProjectEstimateFixedQuickItems]: The updated project estimate fixed quick item, or None if not found.
        """
        item = self.get_by_id(item_id)
        if item:
            if name:
                item.name = name
            if amount is not None:
                item.amount = amount
            self.db_session.commit()
            self.db_session.refresh(item)
            return item
        return None

    def delete(self, item_id: int) -> bool:
        """
        Deletes a project estimate fixed quick item by its ID.

        Args:
            item_id (int): The ID of the project estimate fixed quick item to delete.

        Returns:
            bool: True if the item was deleted, False if it was not found.
        """
        item = self.get_by_id(item_id)
        if item:
            self.db_session.delete(item)
            self.db_session.commit()
            return True
        return False
