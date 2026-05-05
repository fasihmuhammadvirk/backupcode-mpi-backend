from sqlalchemy import Column, Integer, String, Enum, ForeignKey
from sqlalchemy.orm import relationship
from mpi_backend.database.base import Base

import enum

class EstimateType(enum.Enum):
    LABOR_ONLY = "LABOR_ONLY"
    LABOR_AND_MATERIAL = "LABOR_AND_MATERIAL"

class ProjectEstimateSubItem(Base):
    __tablename__ = "project_estimate_sub_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    price = Column(String)
    type = Column(Enum(EstimateType), nullable=False)

    # Foreign Key to ProjectEstimation
    project_estimate_id = Column(Integer, ForeignKey('project_estimation.id'))

    # Relationship to ProjectEstimation
    project_estimate = relationship("ProjectEstimation", back_populates="sub_items")

    def __repr__(self):
        return f"<ProjectEstimateSubItem(name={self.name}, price={self.price}, type={self.type})>"
