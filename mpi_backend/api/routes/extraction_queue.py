"""
Extraction Queue API - Admin-only endpoints for email/PDF extraction queue management.

Thin route layer following ADR-0012 (Three-Layer Architecture):
  Route (validation + auth) --> Controller (business logic) --> DAO (data access)

Endpoints:
1. GET  /extraction-queue/status            - Aggregated extraction queue counts and status
2. GET  /extraction-queue/detail            - Paginated extraction queue entries with filters
3. GET  /extraction-queue/vendors           - Active vendor patterns for dropdowns
4. POST /extraction-queue/reprocess-single  - Retry failed PDF extraction
5. POST /extraction-queue/reprocess-batch   - Batch retry failed PDF extractions
6. POST /extraction-queue/bypass-validation - Bypass validation for VALIDATION_FAILED PDFs
"""

import logging
import os
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.models.User import User
from mpi_backend.database.models.PdfExtractionQueue import PdfExtractionStatus
from mpi_backend.utils.auth.dependencies import require_admin, get_current_user
from mpi_backend.database.schemas.ExtractionQueue import (
    QueueStatusFilters,
    QueueDetailFilters,
    ReprocessRequest,
    ReprocessBatchRequest,
    BypassValidationRequest,
    QueueStatusResponse,
    QueueDetailItem,
    QueueDetailResponse,
    PaginationMeta,
    VendorPatternsResponse,
    ReprocessSingleResponse,
    ReprocessBatchResult,
    ReprocessBatchResponse,
    BypassValidationResponse,
)
from mpi_backend.controllers.extraction_queue_controller import ExtractionQueueController

logger = logging.getLogger(__name__)

# ==============================================================================
# AUTHORIZATION HELPERS
# ==============================================================================

def check_bypass_authorization(user_id: str) -> bool:
    """
    Check if user is authorized to view raw_json data based on BYPASS_ALLOWED_USER_IDS.

    Args:
        user_id: User ID to check

    Returns:
        True if user is authorized for raw_json access, False otherwise
    """
    bypass_allowed_str = os.environ.get("BYPASS_ALLOWED_USER_IDS", "")
    bypass_allowed_ids = [uid.strip() for uid in bypass_allowed_str.split(",") if uid.strip()]
    return str(user_id) in bypass_allowed_ids

# ==============================================================================
# ROUTER SETUP
# ==============================================================================

router = APIRouter(
    prefix="/extraction-queue",
    tags=["Extraction Queue"]
)


def _get_controller(db: Session) -> ExtractionQueueController:
    """Build controller with dependencies."""
    return ExtractionQueueController(db)


# ==============================================================================
# ENDPOINT: EXTRACTION QUEUE STATUS
# ==============================================================================

@router.get("/status", response_model=QueueStatusResponse)
def get_queue_status(
    filters: Annotated[QueueStatusFilters, Query()],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get aggregated pipeline queue status counts."""
    logger.info(f"User {user.id} requested pipeline queue status: date_from={filters.date_from}, date_to={filters.date_to}")
    try:
        controller = _get_controller(db)
        result = controller.get_queue_status(
            date_from=filters.date_from,
            date_to=filters.date_to
        )
        return QueueStatusResponse(
            failed_extractions=result.failed_extractions,
            awaiting_extraction=result.awaiting_extraction,
            total_invoices=result.total_invoices,
        )
    except Exception as e:
        logger.exception(f"Failed to get queue status for user {user.id}")
        raise HTTPException(status_code=500, detail="Failed to retrieve queue status") from e


# ==============================================================================
# ENDPOINT: EXTRACTION QUEUE DETAIL
# ==============================================================================

@router.get("/detail", response_model=QueueDetailResponse)
def get_queue_detail(
    filters: Annotated[QueueDetailFilters, Query()],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get paginated queue entries with filtering."""
    logger.info(f"User {user.id} requested queue detail: status={filters.status}, limit={filters.limit}, offset={filters.offset}")

    try:
        # Check authorization for raw_json access
        bypass_authorized = check_bypass_authorization(user.id)

        effective_limit = min(max(filters.limit, 1), 100)
        effective_offset = max(filters.offset, 0)

        controller = _get_controller(db)
        dao_result = controller.get_queue_detail(
            status=filters.status,
            extraction_status=filters.extraction_status,
            sender=filters.sender,
            subject=filters.subject,
            date_from=filters.date_from,
            date_to=filters.date_to,
            limit=effective_limit,
            offset=effective_offset
        )

        items = []
        for row in dao_result.items:
            # Conditionally include raw_json based on authorization
            raw_json_data = row.raw_json if bypass_authorized else None

            items.append(QueueDetailItem(
                email_id=row.email_id,
                email_date=row.email_date,
                email_error=row.email_error,
                email_created=row.email_created,
                pdf_id=row.pdf_id,
                pdf_status=row.pdf_status,
                pdf_error=row.pdf_error,
                s3_key=row.s3_key,
                # Enhanced business invoice data fields
                ref_no=row.ref_no,
                job_address=row.job_address,
                invoice_date=row.invoice_date,
                supplier=row.supplier,
                amount=row.amount,
                validation_score=row.validation_score,
                validation_reason=row.validation_reason,
                raw_json=raw_json_data,
            ))

        return QueueDetailResponse(
            items=items,
            pagination=PaginationMeta(
                total_count=dao_result.total_count,
            ),
        )

    except Exception as e:
        logger.exception(f"Failed to get queue detail for user {user.id}")
        raise HTTPException(status_code=500, detail="Failed to retrieve queue details") from e


# ==============================================================================
# ENDPOINT: VENDORS
# ==============================================================================

@router.get("/vendors", response_model=VendorPatternsResponse)
def get_vendor_patterns(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    """Get active vendor email patterns for filter dropdowns."""
    logger.info(f"Admin {user.id} requested vendor patterns")
    try:
        controller = _get_controller(db)
        result = controller.get_vendor_patterns()
        return VendorPatternsResponse(
            patterns=result.patterns,
            summary=result.summary,
            cache_timestamp=result.cache_timestamp,
            ttl_seconds=result.ttl_seconds
        )
    except Exception as e:
        logger.exception(f"Failed to get vendor patterns for admin {user.id}")
        raise HTTPException(status_code=500, detail="Failed to retrieve vendor patterns") from e


# ==============================================================================
# ENDPOINT 6: REPROCESS SINGLE
# ==============================================================================

@router.post("/reprocess-single", response_model=ReprocessSingleResponse)
def reprocess_single(
    reprocess_request: ReprocessRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    """Reprocess a single failed PDF extraction."""
    logger.info(
        f"Admin {user.id} requested reprocess for email_id={reprocess_request.email_id}, "
        f"pdf_id={reprocess_request.pdf_id}"
    )

    try:
        controller = _get_controller(db)
        result = controller.reprocess_single(
            email_id=reprocess_request.email_id,
            pdf_id=reprocess_request.pdf_id
        )

        return ReprocessSingleResponse(
            status="success",
            message="PDF extraction queued for reprocessing",
            pdf_id=result.pdf_id,
            email_id=result.email_id,
            previous_status=result.previous_status,
            new_status=PdfExtractionStatus.PENDING.value,
            email_info={
                "sender": result.sender,
                "subject": result.subject
            },
            timestamp=datetime.now(timezone.utc)
        )

    except ValueError as e:
        status_code = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=status_code, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to reprocess email_id={reprocess_request.email_id} for admin {user.id}")
        raise HTTPException(status_code=500, detail="Failed to initiate reprocessing") from e


# ==============================================================================
# ENDPOINT 7: REPROCESS BATCH
# ==============================================================================

@router.post("/reprocess-batch", response_model=ReprocessBatchResponse)
def reprocess_batch(
    batch_request: ReprocessBatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    """Reprocess multiple failed PDF extractions in a single request."""
    logger.info(f"Admin {user.id} requested batch reprocess for {len(batch_request.pdf_ids)} items")

    try:
        controller = _get_controller(db)
        result = controller.reprocess_batch(pdf_ids=batch_request.pdf_ids)

        successful = result["successful"]
        failed = result["failed"]

        if failed == 0:
            message = f"Successfully queued {successful} items for reprocessing"
        else:
            message = f"Queued {successful} items, {failed} failed"

        logger.info(
            f"Batch reprocess completed for admin {user.id}: {successful} successful, {failed} failed"
        )

        return ReprocessBatchResponse(
            total_requested=len(batch_request.pdf_ids),
            successful=successful,
            failed=failed,
            results=[
                ReprocessBatchResult(
                    pdf_id=r["pdf_id"],
                    success=r["success"],
                    message=r["message"]
                )
                for r in result["results"]
            ],
            message=message
        )

    except Exception as e:
        logger.error(f"Batch reprocess error: {str(e)}")
        raise HTTPException(status_code=500, detail="Batch reprocessing failed") from e


# ==============================================================================
# ENDPOINT: BYPASS VALIDATION
# ==============================================================================

@router.post("/bypass-validation", response_model=BypassValidationResponse)
def bypass_validation(
    request: BypassValidationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Bypass validation for a VALIDATION_FAILED PDF extraction.

    Authorization:
    - Checks BYPASS_ALLOWED_USER_IDS environment variable (comma-separated UUIDs)
    - Returns 403 if user not in allow list
    - Backend enforces authorization; frontend env var is UI-only convenience

    Business Logic:
    - Only allows bypass for PDFs with status 'validation_failed'
    - Sets validation_score = 95.123
    - Sets PDF status = 'bypassed'
    - Records bypass in audit log

    Returns:
        BypassValidationResponse with operation details and timestamp
    """
    logger.info(f"User {user.id} requested validation bypass for pdf_id={request.pdf_id}")

    try:
        # Read BYPASS_ALLOWED_USER_IDS from environment
        bypass_allowed_str = os.environ.get("BYPASS_ALLOWED_USER_IDS", "")
        bypass_allowed_ids = [uid.strip() for uid in bypass_allowed_str.split(",") if uid.strip()]

        # Check if user is authorized
        user_id_str = str(user.id)
        if user_id_str not in bypass_allowed_ids:
            logger.warning(
                f"Unauthorized bypass attempt by user {user.id}. "
                f"User not in BYPASS_ALLOWED_USER_IDS"
            )
            raise HTTPException(
                status_code=403,
                detail="User not authorized for validation bypass"
            )

        # Delegate to controller
        controller = _get_controller(db)
        result = controller.bypass_validation(
            pdf_id=request.pdf_id,
            user_id=user_id_str,
            reason=request.reason
        )

        logger.info(
            f"Validation bypass successful: pdf_id={request.pdf_id}, "
            f"user_id={user.id}, previous_score={result.previous_validation_score}"
        )

        return BypassValidationResponse(
            status="success",
            message=f"Validation bypassed for file {result.filename}",
            filename=result.filename,
            model_extracted_data_id=result.model_extracted_data_id,
            previous_validation_score=result.previous_validation_score,
            new_validation_score=result.new_validation_score,
            timestamp=datetime.now(timezone.utc)
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except ValueError as e:
        # Business logic validation errors
        logger.warning(f"Validation bypass failed for pdf_id={request.pdf_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Validation bypass error for pdf_id={request.pdf_id}")
        raise HTTPException(status_code=500, detail="Validation bypass failed") from e
