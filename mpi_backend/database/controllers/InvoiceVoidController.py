"""Controller for invoice void / restore operations."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from mpi_backend.database.dao.invoice_void_dao import InvoiceVoidDAO
from mpi_backend.database.schemas.InvoiceVoid import (
    RestoreByKeyRequest,
    VoidByKeyRequest,
)

logger = logging.getLogger(__name__)


class InvoiceVoidController:
    """
    Handle invoice void and restore business operations.

    This controller coordinates request-level intent with DAO persistence:
    - Void: upsert a key into `public.invoice_voided`
    - Restore: delete a key from `public.invoice_voided`

    Notes:
        - Filtering logic reads void state via live join, so changes are reflected
          immediately without waiting for a dbt refresh.
        - Transaction commit behavior is owned by DAO methods.
    """

    def __init__(self, db: Session):
        self.db = db
        self.dao = InvoiceVoidDAO()

    def void_invoice(self, body: VoidByKeyRequest, user_id: str) -> None:
        """
        Void an invoice identified by composite key.

        Performs an upsert into `public.invoice_voided` using:
            - `ref_no`
            - `date`
            - `vendor`

        Args:
            body: Validated request payload with invoice key and optional reason.
            user_id: ID of the authenticated user performing the void action.

        Returns:
            None. Raises on persistence failure.
        """
        try:
            self.dao.upsert_void(
                db=self.db,
                ref_no=body.ref_no,
                invoice_date=body.date,
                vendor=body.vendor,
                voided_at=datetime.now(timezone.utc),
                voided_by=user_id,
                reason=body.reason,
            )
        except Exception as e:
            logger.error(f"Error voiding invoice {body.ref_no}: {e}")
            raise

    def restore_invoice(self, body: RestoreByKeyRequest) -> bool:
        """
        Restore a previously voided invoice by composite key.

        Deletes the matching row from `public.invoice_voided`.

        Args:
            body: Validated request payload containing `ref_no`, `date`, and `vendor`.

        Returns:
            True if a voided row was deleted, False if no matching row existed.
        """
        try:
            return self.dao.delete_void(
                db=self.db,
                ref_no=body.ref_no,
                invoice_date=body.date,
                vendor=body.vendor,
            )
        except Exception as e:
            logger.error(f"Error restoring invoice {body.ref_no}: {e}")
            raise
