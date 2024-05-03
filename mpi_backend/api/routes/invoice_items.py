from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query,UploadFile, File
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from datetime import datetime
from fastapi_pagination import Page, paginate
from datetime import date
import os
from mpi_backend.database.controllers import InvoiceItemController
from mpi_backend.database.schemas import InvoiceItems
from mpi_backend.utils.auth.auth_bearer import JWTBearer


router = APIRouter(prefix="/invoice-items")


@router.get("/all", response_model=Page[InvoiceItems])
def get_invoices(
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer())
):
    try:
        invoice_items = InvoiceItemController(db).get_invoice_items()

        return paginate(invoice_items)

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No Records Found!")


@router.get("/id", response_model=Page[InvoiceItems])
def get_invoices(
        db: Session = Depends(get_db),
        invoice_id: Optional[UUID] = Query(None, description="Filter by invoice_id"),
        token: str = Depends(JWTBearer())
):
    try:
        invoice_items = InvoiceItemController(db).get_invoice_items(invoice_id=invoice_id)
        return paginate(invoice_items)

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No Records Found!")
