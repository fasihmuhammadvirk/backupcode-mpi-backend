import uuid
from sqlalchemy import Column, Integer, String, Date, DateTime, JSON, ForeignKey, UUID
from sqlalchemy.sql import func
from mpi_backend.database import Base

class PurchaseOrderDrafts(Base):
    __tablename__ = 'purchase_order_drafts'
    __table_args__ = {'schema': 'public'}

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    name = Column(String, nullable=True)
    from_date = Column(Date, nullable=True)
    to_date = Column(Date, nullable=True)
    items_count = Column(Integer, default=0)
    data = Column(JSON, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    saved_at = Column(DateTime(timezone=True), server_default=func.now())
