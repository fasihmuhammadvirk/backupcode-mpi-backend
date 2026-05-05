from sqlalchemy import Column, Integer, String, Float
from mpi_backend.database import Base

class ProjectEstimateFixedQuickItems(Base):
    __tablename__ = 'project_estimate_fixed_quick_items'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)

