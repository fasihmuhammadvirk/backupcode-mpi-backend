"""
Extraction Queue DAO - Database Access Layer

Implements data access patterns for extraction queue operations following ADR-0003.
All database operations use SQL-level aggregation (ADR-0002) and
respect soft delete patterns (ADR-0007).

This module provides clean data access abstraction for:
- Queue status aggregation
- Queue detail queries with filtering
- Vendor pattern management
- Reprocess single/batch PDF extractions
"""

import logging
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from mpi_backend.database.models.PdfExtractionQueue import PdfExtractionStatus

logger = logging.getLogger(__name__)

# ================================================================================
# DATA TRANSFER OBJECTS (DTOs for clean data contracts)
# ================================================================================

@dataclass
class QueueStatusResult:
    """Aggregated PDF extraction queue status counts"""
    failed_extractions: int
    awaiting_extraction: int
    total_invoices: int

@dataclass
class QueueDetailItem:
    """Individual queue detail item"""
    email_id: Optional[str]
    email_date: datetime
    email_error: Optional[str]
    email_created: datetime
    pdf_id: Optional[str]
    pdf_status: Optional[str]
    pdf_error: Optional[str]
    s3_key: Optional[str]

    # Enhanced business invoice data fields
    ref_no: Optional[str] = None
    job_address: Optional[str] = None
    invoice_date: Optional[datetime] = None
    supplier: Optional[str] = None
    amount: Optional[float] = None
    validation_score: Optional[float] = None
    validation_reason: Optional[str] = None
    raw_json: Optional[dict] = None

@dataclass
class QueueDetailResult:
    """Queue detail query result with pagination"""
    items: List[QueueDetailItem]
    total_count: int

@dataclass
class VendorPattern:
    """Vendor email pattern"""
    sender_pattern: str
    vendor_name: Optional[str]
    last_matched_at: Optional[datetime]
    match_count: int
    recent_emails: int
    last_email_date: Optional[datetime]
    is_recently_active: bool

@dataclass
class ReprocessResult:
    """Result of a single reprocess operation"""
    pdf_id: str
    email_id: Optional[str]
    previous_status: str
    sender: Optional[str]
    subject: Optional[str]

@dataclass
class BypassResult:
    """Result of a validation bypass operation"""
    filename: str  # S3 filename (last part of s3_key) or fallback to PDF ID
    model_extracted_data_id: str
    previous_validation_score: Optional[float]

# ================================================================================
# PIPELINE OPERATIONS DAO CLASS
# ================================================================================

class ExtractionQueueDAO:
    """
    Data Access Object for Extraction Queue

    Implements clean separation between API routes and database operations
    following ADR-0003 (DAO Layer Separation). All queries use SQL-level
    aggregation (ADR-0002) and respect soft deletes (ADR-0007).
    """

    def __init__(self, db: Session):
        """Initialize DAO with database session"""
        self.db = db
        self.logger = logging.getLogger(__name__)

    def get_queue_status(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> QueueStatusResult:
        """
        Get aggregated queue status counts using SQL aggregation.

        Follows ADR-0002 by performing all aggregation in SQL rather than Python.
        Respects ADR-0007 by filtering out soft-deleted records.

        Args:
            date_from: Optional start date filter on created_at
            date_to: Optional end date filter on created_at

        Returns:
            QueueStatusResult with email/PDF queue counts and recent errors
        """
        try:
            # PDF queue status counts with optional date filtering
            conditions = ["p.deleted_at IS NULL", "e.deleted_at IS NULL"]
            params: dict = {}

            if date_from:
                conditions.append("e.email_date >= :date_from")
                params['date_from'] = date_from

            if date_to:
                conditions.append("e.email_date <= :date_to")
                params['date_to'] = date_to

            where_clause = " AND ".join(conditions)
            pdf_query = text(f"""
                WITH latest_scores AS (
                    SELECT
                        pdf_extraction_queue_id,
                        validation_score,
                        ROW_NUMBER() OVER (
                            PARTITION BY pdf_extraction_queue_id
                            ORDER BY extracted_at DESC
                        ) AS rn
                    FROM raw.model_extracted_data
                    WHERE deleted_at IS NULL
                )
                SELECT
                    CASE
                        WHEN p.status = 'completed'
                             AND COALESCE(ls.validation_score, 100) < 95
                        THEN 'validation_failed'
                        ELSE p.status
                    END AS status,
                    COUNT(*) as count
                FROM raw.pdf_extraction_queue p
                JOIN raw.email_download_queue e ON p.email_queue_id = e.id
                LEFT JOIN latest_scores ls
                    ON p.id = ls.pdf_extraction_queue_id AND ls.rn = 1
                WHERE {where_clause}
                GROUP BY 1
            """)

            # Execute queries
            pdf_results = self.db.execute(pdf_query, params).fetchall()

            # Compute semantic fields from raw PDF status dict
            pdf_queue = {row.status: row.count for row in pdf_results}
            failed_extractions = pdf_queue.get(PdfExtractionStatus.FAILED, 0) + pdf_queue.get(PdfExtractionStatus.VALIDATION_FAILED, 0)
            awaiting_extraction = pdf_queue.get(PdfExtractionStatus.PENDING, 0) + pdf_queue.get(PdfExtractionStatus.IN_PROGRESS, 0)
            total_invoices = sum(pdf_queue.values())


            return QueueStatusResult(
                failed_extractions=failed_extractions,
                awaiting_extraction=awaiting_extraction,
                total_invoices=total_invoices,
            )

        except SQLAlchemyError as e:
            self.logger.error(f"Database error in get_queue_status: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_queue_status: {e}")
            raise

    def get_queue_detail(
        self,
        status: Optional[str] = None,
        extraction_status: Optional[str] = None,
        sender: Optional[str] = None,
        subject: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> QueueDetailResult:
        """
        Get paginated queue detail with filtering and optimized CTE queries.

        Optimized query using CTEs to get latest extraction data efficiently.
        Business invoice data is extracted from raw_data JSON in the controller.

        Args:
            status: Filter by queue status
            extraction_status: Extraction status filter (unextracted/failed/completed)
            sender: Filter by sender pattern (ILIKE search)
            subject: Filter by subject pattern (ILIKE search)
            date_from: Filter emails from this date
            date_to: Filter emails to this date
            limit: Maximum records to return
            offset: Records to skip for pagination

        Returns:
            QueueDetailResult with items and total count
        """
        try:
            # Optimized CTE-based query - avoids expensive mart table JOIN
            # Gets latest extraction data efficiently using window functions
            base_query = """
                WITH active_extractions AS (
                    SELECT
                        pdf_extraction_queue_id,
                        validation_score,
                        raw_data,
                        extracted_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY pdf_extraction_queue_id
                            ORDER BY extracted_at DESC
                        ) AS rn
                    FROM raw.model_extracted_data
                    WHERE deleted_at IS NULL
                ),
                latest_extractions AS (
                    SELECT
                        pdf_extraction_queue_id,
                        validation_score,
                        raw_data,
                        extracted_at
                    FROM active_extractions
                    WHERE rn = 1
                )
                SELECT
                    e.id as email_id,
                    e.email_date,
                    e.error_message as email_error,
                    e.created_at as email_created,
                    p.id as pdf_id,
                    CASE
                        WHEN p.status = 'completed'
                             AND COALESCE(le.validation_score, 100) < 95
                        THEN 'validation_failed'
                        ELSE p.status
                    END as pdf_status,
                    p.error_message as pdf_error,
                    p.s3_key,
                    -- Latest extraction data
                    le.validation_score as validation_score,
                    le.raw_data as raw_json,
                    le.extracted_at
                FROM raw.pdf_extraction_queue p
                LEFT JOIN raw.email_download_queue e ON p.email_queue_id = e.id
                LEFT JOIN latest_extractions le ON p.id = le.pdf_extraction_queue_id
                WHERE p.deleted_at IS NULL
                  AND (e.deleted_at IS NULL OR e.id IS NULL)
                  AND p.id IS NOT NULL
            """

            # Build dynamic WHERE conditions with parameter binding
            conditions = []
            params = {}

            if status:
                conditions.append("p.status = :status")
                params['status'] = status

            if extraction_status:
                if extraction_status == 'unextracted':
                    conditions.append("p.status IN (:ext_status_1, :ext_status_2)")
                    params['ext_status_1'] = PdfExtractionStatus.PENDING.value
                    params['ext_status_2'] = PdfExtractionStatus.IN_PROGRESS.value
                elif extraction_status == 'failed':
                    # Match explicit failure statuses OR completed with validation_score < 95
                    conditions.append("""(
                        p.status IN (:ext_status_1, :ext_status_2)
                        OR (p.status = :ext_status_completed AND COALESCE(le.validation_score, 100) < 95)
                    )""")
                    params['ext_status_1'] = PdfExtractionStatus.FAILED.value
                    params['ext_status_2'] = PdfExtractionStatus.VALIDATION_FAILED.value
                    params['ext_status_completed'] = PdfExtractionStatus.COMPLETED.value
                elif extraction_status == 'completed':
                    # Only truly completed: completed with score >= 95, or bypassed
                    conditions.append("""(
                        (p.status = :ext_status_1 AND COALESCE(le.validation_score, 100) >= 95)
                        OR p.status = :ext_status_2
                    )""")
                    params['ext_status_1'] = PdfExtractionStatus.COMPLETED.value
                    params['ext_status_2'] = PdfExtractionStatus.BYPASSED.value

            if sender:
                conditions.append("e.sender ILIKE :sender_pattern")
                params['sender_pattern'] = f"%{sender}%"

            if subject:
                conditions.append("e.subject ILIKE :subject_pattern")
                params['subject_pattern'] = f"%{subject}%"

            if date_from:
                conditions.append("e.email_date >= :date_from")
                params['date_from'] = date_from

            if date_to:
                conditions.append("e.email_date <= :date_to")
                params['date_to'] = date_to

            # Add conditions to query
            if conditions:
                base_query += " AND " + " AND ".join(conditions)

            # Full query with ordering and pagination
            full_query = f"""
                {base_query}
                ORDER BY COALESCE(le.extracted_at, p.created_at) DESC
                LIMIT :limit OFFSET :offset
            """
            params.update({'limit': limit, 'offset': offset})

            # Count query for pagination
            count_query = f"SELECT COUNT(*) as total FROM ({base_query}) as filtered"
            count_params = {k: v for k, v in params.items() if k not in ['limit', 'offset']}

            # Execute queries
            results = self.db.execute(text(full_query), params).fetchall()
            count_result = self.db.execute(text(count_query), count_params).fetchone()

            # Build result objects - business data will be extracted from raw_json in controller
            items = []
            for row in results:
                items.append(QueueDetailItem(
                    email_id=str(row.email_id) if row.email_id is not None else None,
                    email_date=row.email_date,
                    email_error=row.email_error,
                    email_created=row.email_created,
                    pdf_id=str(row.pdf_id) if row.pdf_id else None,
                    pdf_status=row.pdf_status,
                    pdf_error=row.pdf_error,
                    s3_key=row.s3_key,
                    validation_score=float(row.validation_score) if row.validation_score is not None else None,
                    raw_json=row.raw_json,
                ))

            total_count = count_result.total if count_result else 0

            self.logger.debug(
                f"Queue detail query returned {len(items)} items, "
                f"total_count={total_count}, filters applied: "
                f"status={status}, sender={bool(sender)}, date_range={bool(date_from or date_to)}"
            )

            return QueueDetailResult(
                items=items,
                total_count=total_count
            )

        except SQLAlchemyError as e:
            self.logger.error(f"Database error in get_queue_detail: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_queue_detail: {e}")
            raise

    def get_vendor_patterns(self) -> List[VendorPattern]:
        """
        Get active vendor email patterns with usage statistics.

        Returns patterns from supplier_email_patterns table with
        recent activity statistics for better UX.

        Returns:
            List of VendorPattern objects with usage statistics
        """
        try:
            query = text("""
                SELECT
                    sep.sender_pattern,
                    s.supplier_name as vendor_name,
                    NULL as last_matched_at,
                    0 as match_count,
                    COUNT(DISTINCT edq.id) as recent_emails,
                    MAX(edq.email_date) as last_email_date
                FROM public.supplier_email_patterns sep
                JOIN public.suppliers s ON sep.supplier_id = s.id
                LEFT JOIN raw.email_download_queue edq ON (
                    (sep.sender_pattern LIKE '@%' AND edq.sender LIKE '%' || sep.sender_pattern) OR
                    (sep.sender_pattern NOT LIKE '@%' AND edq.sender = sep.sender_pattern)
                ) AND edq.deleted_at IS NULL
                  AND edq.email_date >= NOW() - INTERVAL '30 days'
                WHERE sep.is_active = TRUE
                GROUP BY sep.sender_pattern, s.supplier_name
                ORDER BY
                    COUNT(DISTINCT edq.id) DESC,
                    sep.sender_pattern
            """)

            results = self.db.execute(query).fetchall()

            patterns = []
            for row in results:
                patterns.append(VendorPattern(
                    sender_pattern=row.sender_pattern,
                    vendor_name=row.vendor_name,
                    last_matched_at=row.last_matched_at,
                    match_count=row.match_count or 0,
                    recent_emails=row.recent_emails,
                    last_email_date=row.last_email_date,
                    is_recently_active=bool(row.recent_emails > 0)
                ))

            self.logger.debug(f"Retrieved {len(patterns)} vendor patterns")

            return patterns

        except SQLAlchemyError as e:
            self.logger.error(f"Database error in get_vendor_patterns: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_vendor_patterns: {e}")
            raise

    def find_pdf_for_reprocess(
        self,
        email_id: Optional[str] = None,
        pdf_id: Optional[str] = None
    ) -> Optional[ReprocessResult]:
        """
        Find a PDF extraction queue entry for reprocessing.

        Lookup priority: pdf_id (+ optional email_id) > email_id alone.

        Args:
            email_id: Optional email ID to look up
            pdf_id: Optional specific PDF ID

        Returns:
            ReprocessResult if found, None otherwise
        """
        try:
            if pdf_id and email_id:
                query = text("""
                    SELECT p.id, e.id as email_id, p.status, p.error_message, e.sender, e.subject
                    FROM raw.pdf_extraction_queue p
                    JOIN raw.email_download_queue e ON p.email_queue_id = e.id
                    WHERE p.id = :pdf_id
                      AND e.id = :email_id
                      AND p.deleted_at IS NULL
                      AND e.deleted_at IS NULL
                """)
                result = self.db.execute(query, {
                    'pdf_id': pdf_id,
                    'email_id': email_id
                }).fetchone()
            elif pdf_id:
                query = text("""
                    SELECT p.id, e.id as email_id, p.status, p.error_message, e.sender, e.subject
                    FROM raw.pdf_extraction_queue p
                    JOIN raw.email_download_queue e ON p.email_queue_id = e.id
                    WHERE p.id = :pdf_id
                      AND p.deleted_at IS NULL
                      AND e.deleted_at IS NULL
                """)
                result = self.db.execute(query, {'pdf_id': pdf_id}).fetchone()
            else:
                query = text("""
                    SELECT p.id, e.id as email_id, p.status, p.error_message, e.sender, e.subject
                    FROM raw.pdf_extraction_queue p
                    JOIN raw.email_download_queue e ON p.email_queue_id = e.id
                    WHERE e.id = :email_id
                      AND p.deleted_at IS NULL
                      AND e.deleted_at IS NULL
                    ORDER BY p.created_at DESC
                    LIMIT 1
                """)
                result = self.db.execute(query, {'email_id': email_id}).fetchone()

            if not result:
                return None

            return ReprocessResult(
                pdf_id=str(result.id),
                email_id=str(result.email_id),
                previous_status=result.status,
                sender=result.sender,
                subject=result.subject
            )

        except SQLAlchemyError as e:
            self.logger.error(f"Database error in find_pdf_for_reprocess: {e}")
            raise

    def reset_pdf_for_reprocess(self, pdf_id: str) -> int:
        """
        Reset a PDF extraction queue entry to PENDING status for reprocessing.

        Guards against soft-deleted records and non-reprocessable statuses atomically.

        Args:
            pdf_id: PDF extraction queue ID to reset

        Returns:
            Number of rows updated (0 if record was deleted or in blocked status)
        """
        try:
            update_query = text("""
                UPDATE raw.pdf_extraction_queue
                SET status = :new_status,
                    error_message = NULL,
                    extracted_at = NULL
                WHERE id = :pdf_id
                  AND deleted_at IS NULL
                  AND status NOT IN (:blocked_1, :blocked_2)
            """)
            result = self.db.execute(update_query, {
                'pdf_id': pdf_id,
                'new_status': PdfExtractionStatus.PENDING.value,
                'blocked_1': PdfExtractionStatus.IN_PROGRESS.value,
                'blocked_2': PdfExtractionStatus.PENDING.value,
            })
            self.db.commit()
            return result.rowcount
        except SQLAlchemyError as e:
            self.db.rollback()
            self.logger.error(f"Database error in reset_pdf_for_reprocess: {e}")
            raise

    def find_pdfs_for_reprocess_batch(self, pdf_ids: List[str]) -> List[ReprocessResult]:
        """
        Find PDF extraction queue entries for a batch of PDF IDs.

        Args:
            pdf_ids: List of PDF extraction queue IDs to look up

        Returns:
            List of ReprocessResult for found entries
        """
        try:
            query = text("""
                SELECT p.id, p.status, p.error_message, e.id as email_id, e.sender, e.subject
                FROM raw.pdf_extraction_queue p
                JOIN raw.email_download_queue e ON p.email_queue_id = e.id
                WHERE p.id = ANY(:pdf_ids)
                  AND p.deleted_at IS NULL
                  AND e.deleted_at IS NULL
            """)
            results = self.db.execute(query, {'pdf_ids': pdf_ids}).fetchall()

            return [
                ReprocessResult(
                    pdf_id=str(row.id),
                    email_id=str(row.email_id) if row.email_id is not None else None,
                    previous_status=row.status,
                    sender=row.sender,
                    subject=row.subject
                )
                for row in results
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"Database error in find_pdfs_for_reprocess_batch: {e}")
            raise

    def reset_pdfs_batch(self, pdf_ids: List[str]) -> int:
        """
        Reset multiple PDF extraction queue entries to PENDING in a single UPDATE.

        Args:
            pdf_ids: List of PDF extraction queue IDs to reset

        Returns:
            Number of rows updated
        """
        try:
            update_query = text("""
                UPDATE raw.pdf_extraction_queue
                SET status = :new_status,
                    error_message = NULL,
                    extracted_at = NULL
                WHERE id = ANY(:pdf_ids)
                  AND deleted_at IS NULL
                  AND status NOT IN (:blocked_1, :blocked_2)
            """)
            result = self.db.execute(update_query, {
                'pdf_ids': pdf_ids,
                'new_status': PdfExtractionStatus.PENDING.value,
                'blocked_1': PdfExtractionStatus.IN_PROGRESS.value,
                'blocked_2': PdfExtractionStatus.PENDING.value,
            })
            self.db.commit()
            return result.rowcount
        except SQLAlchemyError as e:
            self.db.rollback()
            self.logger.error(f"Database error in reset_pdfs_batch: {e}")
            raise

    def bypass_validation(
        self,
        pdf_id: str,
        user_id: str,
        reason: Optional[str],
        required_status: str = "validation_failed",
    ) -> Optional[BypassResult]:
        """
        Bypass validation for a PDF extraction queue entry.

        Atomically validates the PDF status, updates the validation_score to 95.123
        on the latest model_extracted_data, sets PDF status to 'bypassed', and logs
        the bypass operation.

        Follows ADR-0003 (DAO Layer Separation) with transaction handling.
        Respects ADR-0007 (soft deletes).

        Args:
            pdf_id: PDF extraction queue ID
            user_id: User ID performing the bypass
            reason: Optional reason for bypass
            required_status: PDF must be in this status to bypass

        Returns:
            BypassResult with operation details, or None if not found / wrong status
        """
        try:
            find_data_query = text("""
                SELECT med.id, med.validation_score, peq.s3_key
                FROM raw.model_extracted_data med
                JOIN raw.pdf_extraction_queue peq ON med.pdf_extraction_queue_id = peq.id
                WHERE med.pdf_extraction_queue_id = :pdf_id
                  AND med.deleted_at IS NULL
                  AND peq.deleted_at IS NULL
                  AND (
                      peq.status = :required_status
                      OR (peq.status = 'completed' AND med.validation_score < 95)
                  )
                ORDER BY med.extracted_at DESC
                LIMIT 1
            """)
            data_row = self.db.execute(find_data_query, {
                'pdf_id': pdf_id,
                'required_status': required_status,
            }).fetchone()

            if not data_row:
                self.logger.warning(f"No bypassable record found for pdf_id={pdf_id}")
                return None

            model_data_id = data_row[0]
            previous_score = data_row[1]
            s3_key = data_row[2]

            s3_filename = s3_key.split('/')[-1] if s3_key else pdf_id

            try:
                update_score_query = text("""
                    UPDATE raw.model_extracted_data
                    SET validation_score = :new_score
                    WHERE id = :model_data_id
                      AND deleted_at IS NULL
                """)
                self.db.execute(update_score_query, {
                    'new_score': 95.123,
                    'model_data_id': model_data_id
                })

                update_status_query = text("""
                    UPDATE raw.pdf_extraction_queue
                    SET status = :new_status
                    WHERE id = :pdf_id
                      AND deleted_at IS NULL
                """)
                self.db.execute(update_status_query, {
                    'new_status': PdfExtractionStatus.BYPASSED.value,
                    'pdf_id': pdf_id
                })

                insert_log_query = text("""
                    INSERT INTO public.validation_bypass_log
                    (pdf_extraction_queue_id, model_extracted_data_id, user_id, reason, previous_validation_score)
                    VALUES (:pdf_id, :model_data_id, :user_id, :reason, :prev_score)
                """)
                self.db.execute(insert_log_query, {
                    'pdf_id': pdf_id,
                    'model_data_id': str(model_data_id),
                    'user_id': user_id,
                    'reason': reason,
                    'prev_score': previous_score
                })

                self.db.commit()

                self.logger.info(
                    f"Successfully bypassed validation for pdf_id={pdf_id}, "
                    f"user_id={user_id}, previous_score={previous_score}"
                )

                return BypassResult(
                    filename=s3_filename,
                    model_extracted_data_id=str(model_data_id),
                    previous_validation_score=previous_score
                )

            except SQLAlchemyError as e:
                self.db.rollback()
                self.logger.error(f"Transaction error in bypass_validation: {e}")
                raise

        except SQLAlchemyError as e:
            self.logger.error(f"Database error in bypass_validation: {e}")
            raise
