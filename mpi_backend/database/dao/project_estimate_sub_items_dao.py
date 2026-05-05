from sqlalchemy.orm import Session
from typing import List, Optional
from mpi_backend.database.models.ProjectEstimateSubItem import ProjectEstimateSubItem, EstimateType
import enum

class ProjectEstimateSubItemDAO:
    """
    Data Access Object (DAO) for interacting with the ProjectEstimateSubItem model.

    Provides methods for CRUD operations on the 'project_estimate_sub_items' table.
    """

    def __init__(self, db_session: Session):
        """
        Initializes the DAO with the database session.

        Args:
            db_session (Session): The database session for making queries.
        """
        self.db_session = db_session

    def get_all(self) -> List[ProjectEstimateSubItem]:
        """
        Fetches all project estimate sub items from the database.

        Returns:
            List[ProjectEstimateSubItem]: A list of all project estimate sub items.
        """
        return self.db_session.query(ProjectEstimateSubItem).all()

    def get_by_project_estimate_id(self, project_estimate_id: int) -> List[ProjectEstimateSubItem]:
        """
        Fetches project estimate sub items by their associated project_estimate_id.

        Args:
            project_estimate_id (int): The project estimate ID to retrieve related sub items.

        Returns:
            List[ProjectEstimateSubItem]: A list of project estimate sub items associated with the given project_estimate_id.
        """
        return self.db_session.query(ProjectEstimateSubItem).filter(ProjectEstimateSubItem.project_estimate_id == project_estimate_id).all()

    def get_by_id(self, item_id: int) -> Optional[ProjectEstimateSubItem]:
        """
        Fetches a project estimate sub item by its ID.

        Args:
            item_id (int): The ID of the project estimate sub item to retrieve.

        Returns:
            Optional[ProjectEstimateSubItem]: The project estimate sub item, or None if not found.
        """
        return self.db_session.query(ProjectEstimateSubItem).filter(ProjectEstimateSubItem.id == item_id).first()

    def create(self, name: str, price: str, type: EstimateType, project_estimate_id: int) -> ProjectEstimateSubItem:
        """
        Creates a new project estimate sub item and saves it to the database.

        Args:
            name (str): The name of the project estimate sub item.
            price (str): The price of the project estimate sub item.
            type (EstimateType): The type (LABOR_ONLY, LABOR_AND_MATERIAL).
            project_estimate_id (int): The foreign key for the related project estimation.

        Returns:
            ProjectEstimateSubItem: The created project estimate sub item.
        """
        new_item = ProjectEstimateSubItem(
            name=name, 
            price=price,
            type=type,
            project_estimate_id=project_estimate_id
        )
        self.db_session.add(new_item)
        self.db_session.commit()
        self.db_session.refresh(new_item)
        return new_item

    def update(self, item_id: int, name: Optional[str], price: Optional[str], type: Optional[EstimateType], project_estimate_id: Optional[int]) -> Optional[ProjectEstimateSubItem]:
        """
        Updates an existing project estimate sub item.

        Args:
            item_id (int): The ID of the project estimate sub item to update.
            name (Optional[str]): The new name (optional).
            price (Optional[str]): The new price (optional).
            type (Optional[EstimateType]): The new type (optional).
            project_estimate_id (Optional[int]): The new project estimation ID (optional).

        Returns:
            Optional[ProjectEstimateSubItem]: The updated project estimate sub item, or None if not found.
        """
        item = self.get_by_id(item_id)
        if item:
            if name is not None:
                item.name = name
            if price is not None:
                item.price = price
            if type is not None:
                item.type = type
            if project_estimate_id is not None:
                item.project_estimate_id = project_estimate_id
            self.db_session.commit()
            self.db_session.refresh(item)
            return item
        return None

    def delete(self, item_id: int) -> bool:
        """
        Deletes a project estimate sub item by its ID.

        Args:
            item_id (int): The ID of the project estimate sub item to delete.

        Returns:
            bool: True if the item was deleted, False if it was not found.
        """
        item = self.get_by_id(item_id)
        if item:
            self.db_session.delete(item)
            self.db_session.commit()
            return True
        return False
