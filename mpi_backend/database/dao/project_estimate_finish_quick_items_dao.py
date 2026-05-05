from sqlalchemy.orm import Session
from typing import List, Optional
from mpi_backend.database.models.ProjectEstimateFinishQuickItems import ProjectEstimateFinishQuickItems

class ProjectEstimateFinishQuickItemsDAO:
    def __init__(self, db_session: Session):
        self.db_session = db_session

    def get_all(self) -> List[ProjectEstimateFinishQuickItems]:
        """
        Fetch all ProjectEstimateFinishQuickItems from the database.
        """
        return self.db_session.query(ProjectEstimateFinishQuickItems).all()

    def get_by_id(self, item_id: int) -> Optional[ProjectEstimateFinishQuickItems]:
        """
        Fetch a ProjectEstimateFinishQuickItem by its ID.
        """
        return self.db_session.query(ProjectEstimateFinishQuickItems).filter(
            ProjectEstimateFinishQuickItems.id == item_id
        ).first()

    def create(self, name: str, price: str) -> ProjectEstimateFinishQuickItems:
        """
        Create a new ProjectEstimateFinishQuickItem and save it to the database.
        """
        new_item = ProjectEstimateFinishQuickItems(
            name=name,
            price=price
        )
        self.db_session.add(new_item)
        self.db_session.commit()
        self.db_session.refresh(new_item)
        return new_item

    def update(self, item_id: int, name: Optional[str], price: Optional[str]) -> Optional[ProjectEstimateFinishQuickItems]:
        """
        Update an existing ProjectEstimateFinishQuickItem with new data.
        """
        item = self.get_by_id(item_id)
        if item:
            if name:
                item.name = name
            if price:
                item.price = price
            self.db_session.commit()
            self.db_session.refresh(item)
            return item
        return None

    def delete(self, item_id: int) -> bool:
        """
        Delete a ProjectEstimateFinishQuickItem by its ID.
        """
        item = self.get_by_id(item_id)
        if item:
            self.db_session.delete(item)
            self.db_session.commit()
            return True
        return False
