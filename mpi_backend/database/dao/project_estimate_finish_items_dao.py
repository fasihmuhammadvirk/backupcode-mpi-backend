from sqlalchemy.orm import Session
from typing import List, Optional
from mpi_backend.database.models.ProjectEstimateFinishItems import ProjectEstimateFinishItems

class ProjectEstimateFinishItemsDAO:
    def __init__(self, db_session: Session):
        self.db_session = db_session

    def get_all(self) -> List[ProjectEstimateFinishItems]:
        """
        Fetch all ProjectEstimateFinishItems from the database.
        """
        return self.db_session.query(ProjectEstimateFinishItems).all()
    
    def get_by_project_id(self, project_estimate_id: int) -> List[ProjectEstimateFinishItems]:
        """
        Fetch ProjectEstimateFinishItems by project_estimate_id.
        """
        return self.db_session.query(ProjectEstimateFinishItems).filter(
            ProjectEstimateFinishItems.project_estimate_id == project_estimate_id
        ).all()

    def get_by_id(self, item_id: int) -> Optional[ProjectEstimateFinishItems]:
        """
        Fetch a ProjectEstimateFinishItem by its ID.
        """
        return self.db_session.query(ProjectEstimateFinishItems).filter(
            ProjectEstimateFinishItems.id == item_id
        ).first()

    def create(self, name: str, price: str, qty: str, amount: str, project_estimate_id: int) -> ProjectEstimateFinishItems:
        """
        Create a new ProjectEstimateFinishItem and save it to the database.
        """
        new_item = ProjectEstimateFinishItems(
            name=name,
            price=price,
            qty=qty,
            amount=amount,
            project_estimate_id=project_estimate_id
        )
        self.db_session.add(new_item)
        self.db_session.commit()  # Ensure auto-incrementing ID is generated
        self.db_session.refresh(new_item)
        return new_item

    def update(self, item_id: int, name: Optional[str], price: Optional[str], qty: Optional[str], amount: Optional[str]) -> Optional[ProjectEstimateFinishItems]:
        """
        Update an existing ProjectEstimateFinishItem with new data.
        """
        item = self.get_by_id(item_id)
        if item:
            if name:
                item.name = name
            if price:
                item.price = price
            if qty:
                item.qty = qty
            if amount:
                item.amount = amount
            self.db_session.commit()
            self.db_session.refresh(item)
            return item
        return None

    def delete(self, item_id: int) -> bool:
        """
        Delete a ProjectEstimateFinishItem by its ID.
        """
        item = self.get_by_id(item_id)
        if item:
            self.db_session.delete(item)
            self.db_session.commit()
            return True
        return False
