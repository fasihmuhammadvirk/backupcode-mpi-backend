from sqlalchemy.orm import Session
from mpi_backend.database.models.ProjectEstimateFixedItems import ProjectEstimateFixedItems
from typing import List, Optional

class ProjectEstimateFixedItemsDAO:
    """
    Data Access Object (DAO) for interacting with the ProjectEstimateFixedItems model.

    Provides methods for CRUD (Create, Read, Update, Delete) operations on the 'project_estimate_fixed_items' table.
    """

    def __init__(self, db_session: Session):
        """
        Initializes the DAO with the database session.

        Args:
            db_session (Session): The database session for making queries.
        """
        self.db_session = db_session

    def get_all(self) -> List[ProjectEstimateFixedItems]:
        """
        Fetches all project estimate fixed items from the database.

        Returns:
            List[ProjectEstimateFixedItems]: A list of all project estimate fixed items.
        """
        return self.db_session.query(ProjectEstimateFixedItems).all()

    def get_by_id(self, item_id: int) -> Optional[ProjectEstimateFixedItems]:
        """
        Fetches a project estimate item by its ID.

        Args:
            item_id (int): The ID of the project estimate item to retrieve.

        Returns:
            Optional[ProjectEstimateFixedItems]: The project estimate fixed item, or None if not found.
        """
        return self.db_session.query(ProjectEstimateFixedItems).filter(ProjectEstimateFixedItems.id == item_id).first()

    def get_by_project_id(self, project_id: int) -> List[ProjectEstimateFixedItems]:
        """
        Fetches project estimate fixed items by their associated project ID.

        Args:
            project_id (int): The ID of the project to retrieve the associated fixed items.

        Returns:
            List[ProjectEstimateFixedItems]: A list of project estimate fixed items associated with the provided project ID.
        """
        return self.db_session.query(ProjectEstimateFixedItems).filter(ProjectEstimateFixedItems.project_estimation_id == project_id).all()

    
    def create(self, name: str, price: str, project_estimation_id: int) -> ProjectEstimateFixedItems:
        """
        Creates a new project estimate item and saves it to the database.

        Args:
            name (str): The name of the project estimate item.
            price (str): The price of the project estimate item.
            project_estimation_id (int): The foreign key for the related ProjectEstimation.

        Returns:
            ProjectEstimateFixedItems: The created project estimate fixed item.
        """
        new_item = ProjectEstimateFixedItems(
            name=name, 
            price=price,
            project_estimation_id=project_estimation_id
        )
        self.db_session.add(new_item)
        self.db_session.commit()
        self.db_session.refresh(new_item)
        return new_item

    def update(self, item_id: int, name: Optional[str], price: Optional[str], project_estimation_id: Optional[int]) -> Optional[ProjectEstimateFixedItems]:
        """
        Updates an existing project estimate item with the provided values.

        Args:
            item_id (int): The ID of the project estimate item to update.
            name (Optional[str]): The new name for the item (optional).
            price (Optional[str]): The new price for the item (optional).
            project_estimation_id (Optional[int]): The new project estimation ID (optional).

        Returns:
            Optional[ProjectEstimateFixedItems]: The updated project estimate item, or None if not found.
        """
        item = self.get_by_id(item_id)
        if item:
            if name:
                item.name = name
            if price:
                item.price = price
            if project_estimation_id is not None:
                item.project_estimation_id = project_estimation_id
            self.db_session.commit()
            self.db_session.refresh(item)
            return item
        return None

    def delete(self, item_id: int) -> bool:
        """
        Deletes a project estimate item by its ID.

        Args:
            item_id (int): The ID of the project estimate item to delete.

        Returns:
            bool: True if the item was deleted, False if it was not found.
        """
        item = self.get_by_id(item_id)
        if item:
            self.db_session.delete(item)
            self.db_session.commit()
            return True
        return False
