"""Data Access Object for invoice void / restore operations."""

import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class InvoiceVoidDAO:

    def upsert_void(
        self,
        db: Session,
        ref_no: str,
        invoice_date,
        vendor: str,
        voided_at: datetime,
        voided_by: str | None,
        reason: str | None,
    ) -> None:
        db.execute(
            text("""
                INSERT INTO public.invoice_voided
                    (ref_no, date, vendor, invoice_voided_at, invoice_voided_by, void_reason)
                VALUES
                    (:ref_no, :date, :vendor, :voided_at, :voided_by, :reason)
                ON CONFLICT (ref_no, date, vendor) DO UPDATE SET
                    invoice_voided_at  = EXCLUDED.invoice_voided_at,
                    invoice_voided_by  = EXCLUDED.invoice_voided_by,
                    void_reason        = EXCLUDED.void_reason
            """),
            {
                "ref_no": ref_no,
                "date": invoice_date,
                "vendor": vendor,
                "voided_at": voided_at,
                "voided_by": voided_by,
                "reason": reason,
            },
        )
        db.commit()

    def delete_void(self, db: Session, ref_no: str, invoice_date, vendor: str) -> bool:
        """Delete a void record. Returns True if a row was deleted, False if not found."""
        result = db.execute(
            text("""
                DELETE FROM public.invoice_voided
                WHERE ref_no = :ref_no
                  AND date   = :date
                  AND vendor = :vendor
            """),
            {"ref_no": ref_no, "date": invoice_date, "vendor": vendor},
        )
        db.commit()
        return result.rowcount > 0
