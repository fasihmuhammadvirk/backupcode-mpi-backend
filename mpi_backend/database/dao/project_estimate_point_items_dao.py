from sqlalchemy.orm import Session
from typing import List, Optional
from mpi_backend.database.models.ProjectEstimatePointItems import ProjectEstimatePointItems

class ProjectEstimatePointItemsDAO:
    def __init__(self, db_session: Session):
        self.db_session = db_session

    def get_all(self) -> List[ProjectEstimatePointItems]:
        return self.db_session.query(ProjectEstimatePointItems).all()

    def get_by_project_estimate_id(self, project_estimate_id: int) -> List[ProjectEstimatePointItems]:
        return self.db_session.query(ProjectEstimatePointItems).filter(ProjectEstimatePointItems.project_estimate_id == project_estimate_id).all()

    def get_by_id(self, item_id: int) -> Optional[ProjectEstimatePointItems]:
        return self.db_session.query(ProjectEstimatePointItems).filter(ProjectEstimatePointItems.id == item_id).first()

    def create(self, name: str, pts: str, qty: str, amount: str, project_estimate_id: int) -> ProjectEstimatePointItems:
        new_item = ProjectEstimatePointItems(name=name, pts=pts, qty=qty, amount=amount, project_estimate_id=project_estimate_id)
        self.db_session.add(new_item)
        self.db_session.commit()
        self.db_session.refresh(new_item)
        return new_item

    def update(self, item_id: int, name: Optional[str], pts: Optional[str], qty: Optional[str], amount: Optional[str], project_estimate_id: Optional[int]) -> Optional[ProjectEstimatePointItems]:
        item = self.get_by_id(item_id)
        if item:
            if name:
                item.name = name
            if pts:
                item.pts = pts
            if qty:
                item.qty = qty
            if amount:
                item.amount = amount
            if project_estimate_id is not None:
                item.project_estimate_id = project_estimate_id
            self.db_session.commit()
            self.db_session.refresh(item)
            return item
        return None

    def delete(self, item_id: int) -> bool:
        item = self.get_by_id(item_id)
        if item:
            self.db_session.delete(item)
            self.db_session.commit()
            return True
        return False