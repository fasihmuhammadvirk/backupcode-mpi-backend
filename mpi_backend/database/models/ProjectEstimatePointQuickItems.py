from sqlalchemy import Column, Integer, String, Float
from mpi_backend.database.base import Base

class ProjectEstimatePointQuickItems(Base):
    __tablename__ = 'project_estimate_point_quick_items'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
