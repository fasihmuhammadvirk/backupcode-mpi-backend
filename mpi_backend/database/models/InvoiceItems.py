from sqlalchemy import (
    Column, String, Date, Integer, Float, ForeignKey, UUID, Boolean
)
from sqlalchemy.orm import relationship
from mpi_backend.database import Base
from sqlalchemy import event, or_
from sqlalchemy.orm import Query


class InvoiceItem(Base):
    __tablename__ = 'invoice_items'

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    sheet_name = Column(String)
    mpi_item = Column(String, default='No Match')
    mpi_description = Column(String, default='No Match')
    item = Column(String)
    description = Column(String)
    qty = Column(Integer)
    cost = Column(Float)
    amount = Column(String)
    date = Column(Date)
    ref_no = Column(String)
    po_number = Column(String)
    customer_job = Column(String)
    bill = Column(String)
    vendor = Column(String)
    class_ = Column(String)  # 'class' is a reserved word in Python, so appending an underscore
    memo = Column(String)
    buyer = Column(String)
    date_added = Column(Date)
    export_status = Column(String, default="Pending")
    invoice_id = Column(UUID, ForeignKey('invoices.id'))
    invoice = relationship("Invoice", back_populates="items")
    is_active = Column(Boolean, default=True)


@event.listens_for(Query, "before_compile", retval=True)
def _apply_active_filter(query):
    """Automatic filter to exclude FALSE items (include TRUE and NULL)"""
    if query._execution_options.get('include_all', False):
        return query

    for desc in query.column_descriptions:
        if desc['type'] is InvoiceItem:
            # Show items where is_active is NOT FALSE
            query = query.enable_assertions(False).filter( or_(
                    InvoiceItem.is_active.is_(True),
                    InvoiceItem.is_active.is_(None)  # Include NULL values
                )
            )
            break
    return query
