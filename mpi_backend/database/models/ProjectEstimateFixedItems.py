from sqlalchemy import String, Integer, Column
from mpi_backend.database import Base
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship

                                
class ProjectEstimateFixedItems(Base):
    __tablename__ = 'project_estimate_fixed_items'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    price = Column(String)

    # Foreign key reference to ProjectEstimation
    project_estimation_id = Column(Integer, ForeignKey('project_estimation.id'))

    # Relationship to ProjectEstimation
    project_estimation = relationship("ProjectEstimation", back_populates="fixed_items")
