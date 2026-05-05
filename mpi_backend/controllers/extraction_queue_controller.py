"""
Extraction Queue Controller - Business Logic Layer

Implements business logic for extraction queue operations following the architecture pattern:
Router (validation) --> Controller (business logic) --> DAO (data access)

This controller acts as the business logic layer between the FastAPI routes
and the database access layer, implementing ADR-0003 (DAO Layer Separation).
"""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from mpi_backend.database.dao.extraction_queue_dao import (
    ExtractionQueueDAO,
    QueueStatusResult,
    QueueDetailResult,
    QueueDetailItem,
    VendorPattern,
    ReprocessResult,
    BypassResult
)
from mpi_backend.database.models.PdfExtractionQueue import PdfExtractionStatus

logger = logging.getLogger(__name__)


# ================================================================================
# CONTROLLER RESPONSE MODELS (Business Logic DTOs)
# ================================================================================

@dataclass
class QueueStatusResponse:
    """Queue status response with business logic applied"""
    failed_extractions: int
    awaiting_extraction: int
    total_invoices: int

@dataclass
class VendorPatternsResponse:
    """Vendor patterns response with metadata"""
    patterns: List[Dict[str, Any]]
    summary: Dict[str, Any]
    cache_timestamp: datetime
    ttl_seconds: int

@dataclass
class ReprocessSingleResult:
    """Reprocess single operation result"""
    pdf_id: str
    email_id: Optional[str]
    previous_status: str
    sender: Optional[str]
    subject: Optional[str]

@dataclass
class BypassValidationResult:
    """Bypass validation operation result"""
    filename: str  # S3 filename (last part of s3_key) or fallback to PDF ID
    model_extracted_data_id: str
    previous_validation_score: Optional[float]
    new_validation_score: float


# ================================================================================
# PIPELINE OPERATIONS CONTROLLER
# ================================================================================

class ExtractionQueueController:
    """
    Extraction Queue Controller

    Implements business logic for extraction queue operations:
    - Queue status aggregation with circuit breaker status
    - Queue detail with pagination
    - Vendor pattern management
    - Reprocess single/batch PDF extractions
    """

    def __init__(self, db: Session):
        """Initialize controller with dependencies"""
        self.db = db
        self.dao = ExtractionQueueDAO(db)
        self.logger = logging.getLogger(__name__)

    def _extract_invoice_data_from_raw_json(self, raw_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract business invoice data from raw_json field.

        The raw_json contains extracted invoice data in format:
        {
            "invoices": [
                {
                    "ref_no": "186263",
                    "customer_job": "MPI PLUMBING CORP. 670 Myrtle Ave. #234 Brooklyn NY 11205",
                    "date": "04/15/2026",
                    "vendor": "Y & S Plumbing Supplies",
                    "total": "988.23",
                    ...
                }
            ]
        }

        For multiple invoices, concatenates values with "; " separator.

        Args:
            raw_json: The raw_data from model_extracted_data

        Returns:
            Dict with extracted fields: ref_no, job_address, invoice_date, supplier, amount
        """
        if not raw_json or not isinstance(raw_json, dict):
            return {
                "ref_no": None,
                "job_address": None,
                "invoice_date": None,
                "supplier": None,
                "amount": None,
                "validation_reason": None
            }

        try:
            # Normalize both shapes: multi-invoice {"invoices": [...]} and
            # single-invoice flat {"ref_no": ..., "date": ..., "vendor": ...}
            invoices_value = raw_json.get("invoices")
            if isinstance(invoices_value, list) and invoices_value:
                invoices = invoices_value
            else:
                # Flat single-invoice shape -- wrap it so the loop below works
                invoices = [raw_json]

            # Extract and concatenate data from all invoices
            ref_nos = []
            job_addresses = []
            invoice_dates = []
            suppliers = []
            amounts = []

            for invoice in invoices:
                if isinstance(invoice, dict):
                    # Extract ref_no
                    if invoice.get("ref_no"):
                        ref_nos.append(str(invoice["ref_no"]))

                    # Extract job_address from customer_job field
                    if invoice.get("customer_job"):
                        job_addresses.append(str(invoice["customer_job"]))

                    # Extract invoice_date from date field
                    if invoice.get("date"):
                        date_str = str(invoice["date"])
                        # Try to parse as datetime if it looks like a date
                        try:
                            # Handle common date formats: MM/DD/YYYY, YYYY-MM-DD, etc.
                            # Try parsing MM/DD/YYYY format first (common in sample data)
                            if "/" in date_str:
                                parsed_date = datetime.strptime(date_str, "%m/%d/%Y")
                                invoice_dates.append(parsed_date.date())
                            elif "-" in date_str:
                                parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
                                invoice_dates.append(parsed_date.date())
                            else:
                                # Keep as string if can't parse
                                invoice_dates.append(date_str)
                        except (ValueError, TypeError):
                            # Keep as string if parsing fails
                            invoice_dates.append(date_str)

                    # Extract supplier from vendor field
                    if invoice.get("vendor"):
                        suppliers.append(str(invoice["vendor"]))

                    # Extract amount from total field
                    if invoice.get("total"):
                        try:
                            amount_str = str(invoice["total"]).replace("$", "").replace(",", "")
                            amounts.append(float(amount_str))
                        except (ValueError, TypeError):
                            # Skip invalid amounts
                            pass

            # For invoice_date, return first valid date object (API expects datetime, not string)
            invoice_date_result = None
            if invoice_dates:
                # Return first valid date object to maintain API compatibility
                for d in invoice_dates:
                    if hasattr(d, 'strftime'):
                        # Found a valid date object, use it
                        invoice_date_result = d
                        break

                # If no date objects found, try to parse the first string
                if invoice_date_result is None and invoice_dates:
                    try:
                        first_date_str = str(invoice_dates[0])
                        if "/" in first_date_str:
                            parsed_date = datetime.strptime(first_date_str, "%m/%d/%Y")
                            invoice_date_result = parsed_date.date()
                        elif "-" in first_date_str:
                            parsed_date = datetime.strptime(first_date_str, "%Y-%m-%d")
                            invoice_date_result = parsed_date.date()
                    except (ValueError, TypeError):
                        # If parsing fails, leave as None
                        invoice_date_result = None

            # Extract validation failed checks from each invoice
            validation_checks = []
            for invoice in invoices:
                if isinstance(invoice, dict):
                    checks = invoice.get("_validation_failed_checks", [])
                    if isinstance(checks, list):
                        validation_checks.extend(str(c).replace("_", " ") for c in checks if c)

            return {
                "ref_no": "; ".join(ref_nos) if ref_nos else None,
                "job_address": "; ".join(job_addresses) if job_addresses else None,
                "invoice_date": invoice_date_result,
                "supplier": "; ".join(suppliers) if suppliers else None,
                "amount": sum(amounts) if amounts else None,
                "validation_reason": "; ".join(validation_checks) if validation_checks else None
            }

        except (KeyError, TypeError, AttributeError) as e:
            self.logger.warning(f"Failed to extract invoice data from raw_json: {e}")
            return {
                "ref_no": None,
                "job_address": None,
                "invoice_date": None,
                "supplier": None,
                "amount": None,
                "validation_reason": None
            }

    def get_queue_status(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> QueueStatusResponse:
        """
        Get comprehensive queue status including circuit breaker state.

        Business logic:
        - Aggregates queue counts from DAO
        - Adds circuit breaker status for operational awareness
        - Optionally filters by date range

        Returns:
            QueueStatusResponse with complete operational status
        """
        try:
            # Get queue data from DAO
            dao_result = self.dao.get_queue_status(
                date_from=date_from,
                date_to=date_to
            )

            self.logger.info(
                f"Queue status retrieved: "
                f"pdf_failed={dao_result.failed_extractions}, "
                f"pdf_pending={dao_result.awaiting_extraction}"
            )

            return QueueStatusResponse(
                failed_extractions=dao_result.failed_extractions,
                awaiting_extraction=dao_result.awaiting_extraction,
                total_invoices=dao_result.total_invoices,
            )

        except Exception as e:
            self.logger.exception("Failed to get queue status")
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
        Get paginated queue detail with business logic validation and invoice data extraction.

        Business logic:
        - Converts date objects to datetime for DAO compatibility
        - Validates pagination parameters
        - Applies default limits for performance
        - Extracts business invoice data from raw_json field

        Args:
            status: Optional status filter
            extraction_status: Optional extraction status filter
            sender: Optional sender pattern
            subject: Optional subject pattern
            date_from: Optional start date filter
            date_to: Optional end date filter
            limit: Records per page (max 100)
            offset: Page offset

        Returns:
            QueueDetailResult with enriched business data from raw_json
        """
        try:
            # Business logic: Validate and sanitize parameters
            limit = min(max(limit, 1), 100)  # Clamp between 1-100
            offset = max(offset, 0)  # No negative offsets

            self.logger.debug(
                f"Queue detail requested: status={status}, extraction_status={extraction_status}, "
                f"sender={bool(sender)}, subject={bool(subject)}, "
                f"date_range={bool(date_from or date_to)}, limit={limit}, offset={offset}"
            )

            # Get data from DAO - date_from/date_to are already tz-aware datetimes from Pydantic
            dao_result = self.dao.get_queue_detail(
                status=status,
                extraction_status=extraction_status,
                sender=sender,
                subject=subject,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                offset=offset
            )

            # Extract business data from raw_json for each item
            enriched_items = []
            for item in dao_result.items:
                # Extract business data from raw_json
                invoice_data = self._extract_invoice_data_from_raw_json(item.raw_json)

                # Debug logging for data extraction
                if item.raw_json and invoice_data["ref_no"]:
                    self.logger.debug(
                        f"Extracted invoice data for pdf_id={item.pdf_id}: "
                        f"ref_no={invoice_data['ref_no']}, supplier={invoice_data['supplier']}, "
                        f"amount={invoice_data['amount']}"
                    )

                # Create new item with extracted business data
                enriched_item = QueueDetailItem(
                    email_id=item.email_id,
                    email_date=item.email_date,
                    email_error=item.email_error,
                    email_created=item.email_created,
                    pdf_id=item.pdf_id,
                    pdf_status=item.pdf_status,
                    pdf_error=item.pdf_error,
                    s3_key=item.s3_key,
                    # Extracted business data from raw_json
                    ref_no=invoice_data["ref_no"],
                    job_address=invoice_data["job_address"],
                    invoice_date=invoice_data["invoice_date"],
                    supplier=invoice_data["supplier"],
                    amount=invoice_data["amount"],
                    validation_score=item.validation_score,  # Already available from DAO
                    validation_reason=invoice_data["validation_reason"],
                    raw_json=item.raw_json,
                )
                enriched_items.append(enriched_item)

            return QueueDetailResult(
                items=enriched_items,
                total_count=dao_result.total_count
            )

        except Exception as e:
            self.logger.exception("Failed to get queue detail with business data extraction")
            raise

    def get_vendor_patterns(self) -> VendorPatternsResponse:
        """
        Get vendor patterns with usage statistics and metadata.

        Business logic:
        - Formats patterns for API consumption
        - Calculates summary statistics
        - Adds caching metadata for client optimization

        Returns:
            VendorPatternsResponse with patterns and metadata
        """
        try:
            # Get patterns from DAO
            dao_patterns = self.dao.get_vendor_patterns()

            # Business logic: Format for API response
            patterns = []
            active_patterns = []
            inactive_patterns = []

            for pattern in dao_patterns:
                pattern_dict = {
                    "sender_pattern": pattern.sender_pattern,
                    "vendor_name": pattern.vendor_name,
                    "last_matched_at": pattern.last_matched_at,
                    "match_count": pattern.match_count,
                    "recent_emails": pattern.recent_emails,
                    "last_email_date": pattern.last_email_date,
                    "is_recently_active": pattern.is_recently_active
                }
                patterns.append(pattern_dict)

                if pattern.is_recently_active:
                    active_patterns.append(pattern_dict)
                else:
                    inactive_patterns.append(pattern_dict)

            # Business logic: Calculate summary statistics
            summary = {
                "total_patterns": len(patterns),
                "active_patterns": len(active_patterns),
                "inactive_patterns": len(inactive_patterns),
                "activity_rate": len(active_patterns) / len(patterns) if patterns else 0
            }

            self.logger.debug(
                f"Retrieved {len(patterns)} vendor patterns: "
                f"{len(active_patterns)} active, {len(inactive_patterns)} inactive"
            )

            return VendorPatternsResponse(
                patterns=patterns,
                summary=summary,
                cache_timestamp=datetime.now(timezone.utc),
                ttl_seconds=300  # 5 minutes cache recommendation
            )

        except Exception as e:
            self.logger.exception("Failed to get vendor patterns")
            raise

    def reprocess_single(
        self,
        email_id: Optional[str] = None,
        pdf_id: Optional[str] = None
    ) -> ReprocessSingleResult:
        """
        Reprocess a single failed PDF extraction.

        Business logic:
        - Validates that the PDF exists
        - Validates that the status allows reprocessing
        - Delegates to DAO for the actual reset

        Args:
            email_id: Email ID to reprocess
            pdf_id: Optional specific PDF ID

        Returns:
            ReprocessSingleResult with operation details

        Raises:
            ValueError: If PDF not found or status doesn't allow reprocessing
        """
        try:
            result = self.dao.find_pdf_for_reprocess(email_id, pdf_id)

            if not result:
                raise ValueError("PDF extraction record not found for the specified email")

            rowcount = self.dao.reset_pdf_for_reprocess(result.pdf_id)

            if rowcount == 0:
                raise ValueError(
                    f"Cannot reprocess item with status '{result.previous_status}'. "
                    "Only 'FAILED' or 'COMPLETED' items can be reprocessed."
                )

            self.logger.info(
                f"Reprocess initiated for pdf_id={result.pdf_id}",
                extra={
                    "pdf_id": result.pdf_id,
                    "email_id": email_id,
                    "previous_status": result.previous_status,
                }
            )

            return ReprocessSingleResult(
                pdf_id=result.pdf_id,
                email_id=result.email_id,
                previous_status=result.previous_status,
                sender=result.sender,
                subject=result.subject
            )

        except ValueError:
            raise
        except Exception as e:
            self.logger.exception("Failed to reprocess single item")
            raise

    def reprocess_batch(self, pdf_ids: List[str]) -> Dict[str, Any]:
        """
        Reprocess multiple failed PDF extractions in bulk.

        Business logic:
        - Finds all PDFs in a single query
        - Validates reprocessable status for each
        - Resets all valid PDFs in a single UPDATE
        - Returns per-item results for the caller

        Args:
            pdf_ids: List of PDF extraction queue IDs to reprocess

        Returns:
            Dict with successful count, failed count, and per-item results
        """
        try:
            found = self.dao.find_pdfs_for_reprocess_batch(pdf_ids)
            found_by_pdf = {r.pdf_id: r for r in found}

            non_reprocessable = {PdfExtractionStatus.IN_PROGRESS.value, PdfExtractionStatus.PENDING.value}
            to_reset = []
            results = []

            for pdf_id in pdf_ids:
                record = found_by_pdf.get(pdf_id)

                if not record:
                    results.append({
                        "pdf_id": pdf_id,
                        "success": False,
                        "message": "PDF extraction record not found",
                    })
                elif record.previous_status in non_reprocessable:
                    results.append({
                        "pdf_id": pdf_id,
                        "success": False,
                        "message": (
                            f"Cannot reprocess item with status '{record.previous_status}'. "
                            "Only 'FAILED' or 'COMPLETED' items can be reprocessed."
                        ),
                    })
                else:
                    to_reset.append(record)

            # Execute batch reset FIRST, then mark results based on actual rowcount
            rowcount = 0
            if to_reset:
                reset_ids = list(dict.fromkeys(r.pdf_id for r in to_reset))
                rowcount = self.dao.reset_pdfs_batch(reset_ids)
                if rowcount != len(reset_ids):
                    self.logger.warning(
                        f"Batch reprocess: expected {len(reset_ids)} updates but got {rowcount}. "
                        "Some items may have been concurrently modified or soft-deleted."
                    )

            # Mark success/failure based on DAO outcome
            for record in to_reset:
                if rowcount > 0:
                    results.append({
                        "pdf_id": record.pdf_id,
                        "success": True,
                        "message": "Queued for reprocessing",
                    })
                else:
                    results.append({
                        "pdf_id": record.pdf_id,
                        "success": False,
                        "message": "Failed to reset. Was the record concurrently modified?",
                    })

            successful = sum(1 for r in results if r["success"])
            failed = len(pdf_ids) - successful

            self.logger.info(
                f"Batch reprocess: {successful} successful, {failed} failed out of {len(pdf_ids)} requested"
            )

            return {
                "successful": successful,
                "failed": failed,
                "results": results,
            }

        except Exception as e:
            self.logger.exception("Failed to reprocess batch")
            raise

    def bypass_validation(
        self,
        pdf_id: str,
        user_id: str,
        reason: Optional[str] = None
    ) -> BypassValidationResult:
        """
        Bypass validation for a PDF extraction queue entry.

        Business logic validates that:
        - PDF exists and has status VALIDATION_FAILED (only validation-failed items can be bypassed)
        - Delegates to DAO for transaction handling

        Args:
            pdf_id: PDF extraction queue ID
            user_id: User ID performing the bypass
            reason: Optional reason for bypass

        Returns:
            BypassValidationResult with operation details

        Raises:
            ValueError: If PDF not found or not in VALIDATION_FAILED status
        """
        try:
            bypass_result = self.dao.bypass_validation(
                pdf_id,
                user_id,
                reason,
                required_status=PdfExtractionStatus.VALIDATION_FAILED.value,
            )

            if bypass_result is None:
                raise ValueError(
                    f"Cannot bypass validation for PDF {pdf_id}. "
                    f"Record not found, soft-deleted, or not in "
                    f"'{PdfExtractionStatus.VALIDATION_FAILED.value}' status."
                )

            self.logger.info(
                f"Validation bypassed for pdf_id={pdf_id}, user_id={user_id}, "
                f"previous_score={bypass_result.previous_validation_score}"
            )

            return BypassValidationResult(
                filename=bypass_result.filename,
                model_extracted_data_id=bypass_result.model_extracted_data_id,
                previous_validation_score=bypass_result.previous_validation_score,
                new_validation_score=95.123
            )

        except ValueError:
            raise
        except Exception as e:
            self.logger.exception(f"Failed to bypass validation for pdf_id={pdf_id}")
            raise
