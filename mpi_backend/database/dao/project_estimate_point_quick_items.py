from sqlalchemy.orm import Session
from typing import List, Optional
from mpi_backend.database.models.ProjectEstimatePointQuickItems import ProjectEstimatePointQuickItems

class ProjectEstimatePointQuickItemsDAO:
    def __init__(self, db_session: Session):
        self.db_session = db_session

    def get_all(self) -> List[ProjectEstimatePointQuickItems]:
        """
        Fetch all ProjectEstimatePointQuickItems from the database.
        """
        return self.db_session.query(ProjectEstimatePointQuickItems).all()

    def get_by_id(self, item_id: int) -> Optional[ProjectEstimatePointQuickItems]:
        """
        Fetch a ProjectEstimatePointQuickItem by its ID.
        """
        return self.db_session.query(ProjectEstimatePointQuickItems).filter(
            ProjectEstimatePointQuickItems.id == item_id
        ).first()

    def create(self, name: str, amount: str) -> ProjectEstimatePointQuickItems:
        """
        Create a new ProjectEstimatePointQuickItem and save it to the database.
        """
        new_item = ProjectEstimatePointQuickItems(
            name=name,
            amount=amount
        )
        self.db_session.add(new_item)
        self.db_session.commit()  # Ensure auto-incrementing ID is generated
        self.db_session.refresh(new_item)  # Refresh to fetch the generated ID
        return new_item

    def update(self, item_id: int, name: Optional[str], amount: Optional[str]) -> Optional[ProjectEstimatePointQuickItems]:
        """
        Update an existing ProjectEstimatePointQuickItem with new data.
        """
        item = self.get_by_id(item_id)
        if item:
            if name:
                item.name = name
            if amount:
                item.amount = amount
            self.db_session.commit()
            self.db_session.refresh(item)
            return item
        return None

    def delete(self, item_id: int) -> bool:
        """
        Delete a ProjectEstimatePointQuickItem by its ID.
        """
        item = self.get_by_id(item_id)
        if item:
            self.db_session.delete(item)
            self.db_session.commit()
            return True
        return False
