from sqlalchemy import Column, Integer, String, Float
from mpi_backend.database.base import Base

class ProjectEstimateFinishQuickItems(Base):
    __tablename__ = 'project_estimate_finish_quick_items'

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)

