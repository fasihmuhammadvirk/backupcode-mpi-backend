from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
import pyodbc

from mpi_backend.database import get_db
from mpi_backend.database.controllers import InvoiceItemController
from mpi_backend.utils.auth.auth_bearer import JWTBearer

router = APIRouter(prefix="/quickbooks")


@router.get("/migrate")
def migrate_invoice_to_QB(
        invoice_ids:List[UUID], db: Session = Depends(get_db)):

    QB_connection = pyodbc.connect('DSN=QuickBooks Data;')
    cursor = QB_connection.cursor()
    # TODO replace with fields from MPI latest company file & value of line_item
    query = """
       INSERT INTO InvoiceLine (CustomerRefFullName, InvoiceLineItemRefFullName, InvoiceLineDesc, InvoiceLineRate, InvoiceLineAmount, InvoiceLineSalesTaxCodeRefFullName, FQSaveToCache)
       VALUES ('Joe Mama Inc 2', 'Pest Control', 'Callback VoIP Charge', 33.00, 33.00, 'Non', 0)"""

    for invoice_id in invoice_ids:
        try:
            line_item = InvoiceItemController(db).get_invoice_items(invoice_id)
            cursor.execute(query)
            QB_connection.commit()
        except Exception as e:
            print(f"Error executing query for invoice {invoice_id}: {e}")
            QB_connection.rollback()
        finally:
            cursor.close()
            QB_connection.close()
