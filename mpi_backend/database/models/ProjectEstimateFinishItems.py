from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from mpi_backend.database.base import Base

class ProjectEstimateFinishItems(Base):
    __tablename__ = 'project_estimate_finish_items'

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    price = Column(String, nullable=False)
    qty = Column(String, nullable=False)
    amount = Column(String, nullable=False)

    project_estimate_id = Column(Integer, ForeignKey('project_estimation.id'), nullable=False)

    # Define the relationship to ProjectEstimation (if needed)
    project_estimate = relationship("ProjectEstimation", backref="finish_items")
