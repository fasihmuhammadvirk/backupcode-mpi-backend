from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from mpi_backend.database.base import Base

class ProjectEstimatePointItems(Base):
    __tablename__ = 'project_estimate_point_items'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    pts = Column(String, nullable=False)
    qty = Column(String, nullable=False)
    amount = Column(String, nullable=False)

    # Foreign Key to ProjectEstimation
    project_estimate_id = Column(Integer, ForeignKey('project_estimation.id'))

    # Relationship to ProjectEstimation
    project_estimate = relationship("ProjectEstimation", back_populates="point_items")
