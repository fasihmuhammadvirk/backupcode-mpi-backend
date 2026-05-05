"""
API routes for voiding and restoring invoices by key (ref_no, date, vendor).

Void state lives exclusively in public.invoice_voided. The filter/DAO layer
performs a live LEFT JOIN to this table so the UI sees void state immediately
without any mart patching or dbt run.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.controllers.InvoiceVoidController import InvoiceVoidController
from mpi_backend.database.models.User import User
from mpi_backend.database.schemas.InvoiceVoid import (
    RestoreByKeyRequest,
    VoidByKeyRequest,
)
from mpi_backend.utils.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoice", tags=["Invoice Voids"])


@router.post("/void-by-key")
def void_invoice_by_key(
    body: VoidByKeyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Void an invoice identified by (ref_no, date, vendor).

    Upserts into public.invoice_voided. The filter DAO live-joins this table,
    so the UI reflects the change immediately.
    """
    try:
        controller = InvoiceVoidController(db)
        user_id = str(current_user.id) if current_user else None
        controller.void_invoice(body, user_id)
        logger.info("Voided invoice ref_no=%s vendor=%s", body.ref_no, body.vendor)

        return {"status": "voided"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("POST /invoice/void-by-key - unexpected error")
        raise HTTPException(status_code=500, detail="Failed to void invoice") from e


@router.post("/restore-by-key")
def restore_invoice_by_key(
    body: RestoreByKeyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore a previously voided invoice by (ref_no, date, vendor).

    Deletes the row from public.invoice_voided. The filter DAO live-joins this
    table, so the UI reflects the change immediately.
    """
    try:
        controller = InvoiceVoidController(db)
        success = controller.restore_invoice(body)

        if not success:
            logger.warning("Restore failed — no void record for ref_no=%s vendor=%s", body.ref_no, body.vendor)
            raise HTTPException(
                status_code=404,
                detail="No void record found for the given key",
            )

        logger.info("Restored invoice ref_no=%s vendor=%s", body.ref_no, body.vendor)
        return {"status": "restored"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("POST /invoice/restore-by-key - unexpected error")
        raise HTTPException(status_code=500, detail="Failed to restore invoice") from e
