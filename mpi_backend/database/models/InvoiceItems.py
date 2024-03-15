from sqlalchemy import Column, String, Date, Integer, Float, ForeignKey, UUID
from sqlalchemy.orm import relationship
from mpi_backend.database import Base


class InvoiceItem(Base):
    __tablename__ = 'invoice_items'

    id = Column(Integer, primary_key=True)
    filename = Column(String)
    sheet_name = Column(String)
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
    invoice_id = Column(UUID, ForeignKey('invoices.id'))
    invoice = relationship("Invoice", back_populates="items")
