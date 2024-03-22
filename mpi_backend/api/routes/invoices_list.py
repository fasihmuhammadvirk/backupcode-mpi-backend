from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from datetime import datetime
from fastapi_pagination import Page, paginate
from datetime import date
from mpi_backend.database.controllers import SupplierController, InvoiceController
from mpi_backend.database.schemas import Invoice

router = APIRouter(prefix="/invoice")


@router.get("", response_model=Page[Invoice])
def get_invoices(
        db: Session = Depends(get_db),
        supplier_id: int = Query(None),
        from_date: date = Query(None),
        to_date: date = Query(None),
        status: str = Query('all', description="Status (all, processed, unprocessed)"),
        page: int = Query(1),
        size: int = Query(10)
):
    try:
        invoices = InvoiceController(db).get_invoices(
            db=db,
            supplier_id=supplier_id,
            from_date=from_date,
            to_date=to_date,
            status=status,
        )

        return paginate(invoices)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch invoices: {e}")
