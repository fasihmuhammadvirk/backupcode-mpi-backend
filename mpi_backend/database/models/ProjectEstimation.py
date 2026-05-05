from mpi_backend.database import Base
from sqlalchemy import String, Integer, Column, ForeignKey, UUID
from sqlalchemy.orm import relationship

class ProjectEstimation(Base):
    __tablename__ = "project_estimation"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    location = Column(String)
    contract_value = Column(String)
    budget_allocation = Column(String)
    labor_percentage = Column(String)
    material_percentage = Column(String)
    dollar_point = Column(String)
    budget_limit = Column(String)
    labor_rem = Column(String)
    material_rem = Column(String)
    finishing = Column(String)
    point_value = Column(String)
    target_value = Column(String)
    fixed_costs = Column(String)
    
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    user = relationship("User", back_populates="project_estimations")
    
    fixed_items = relationship("ProjectEstimateFixedItems", back_populates="project_estimation")
    sub_items = relationship("ProjectEstimateSubItem", back_populates="project_estimate")
    point_items = relationship("ProjectEstimatePointItems", back_populates="project_estimate")

