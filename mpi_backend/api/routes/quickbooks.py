from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
import pyodbc

from mpi_backend.database import get_db
from mpi_backend.database.controllers import InvoiceItemController
from mpi_backend.utils.auth.auth_bearer import JWTBearer

router = APIRouter(prefix="/quickbooks")


@router.post("/migrate")
def migrate_invoice_to_QB(
        invoice_ids: List[UUID], db: Session = Depends(get_db)):
    QB_connection = pyodbc.connect('DSN=QuickBooks Data;')  # 5 queries per session in trial mode
    cursor = QB_connection.cursor()

    for invoice_id in invoice_ids:
        line_items = InvoiceItemController(db).get_invoice_items(invoice_id)

        for line_item in line_items:
            try:
                query = f"""INSERT INTO "BillItemLine" ("VendorRefFullName", "RefNumber", "Memo", "ItemLineItemRefFullName", "ItemLineDesc", "ItemLineQuantity", "ItemLineCost", "ItemLineAmount", "ItemLineCustomerRefFullName", "ItemLineClassRefFullName","TxnDate") VALUES ('{line_item.vendor}', '{line_item.ref_no}', '{line_item.memo}', '{line_item.item}', '{line_item.description}', {line_item.qty}, {line_item.cost}, {float(line_item.amount.replace('$', ''))} ,'{line_item.customer_job}', NULL, {{d'{line_item.date.strftime('%Y-%m-%d')}'}})"""
                cursor.execute(query)
            except Exception as e:
                print(f"Error inserting line item {line_item} --> : {e}")
                continue
    QB_connection.commit()
    cursor.close()
    QB_connection.close()
