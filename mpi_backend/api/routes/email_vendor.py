"""
API for email-based supplier configuration (sender patterns, subject-resolved inbox).

All endpoints require authentication.
"""
import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.controllers.EmailVendorController import EmailVendorController
from mpi_backend.database.models.User import User
from mpi_backend.database.schemas.EmailVendor import (
    SupplierEmailCreate,
    SupplierEmailResponse,
    SupplierEmailUpdate,
    SupplierPatternCreate,
    SupplierPatternResponse,
    SupplierPatternUpdate,
    supplier_to_response,
)
from mpi_backend.utils.auth.dependencies import get_current_user

router = APIRouter(prefix="/email-vendor", tags=["Email Vendor"])
logger = logging.getLogger(__name__)


@router.get("/vendors", response_model=List[SupplierEmailResponse])
async def list_email_vendors(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List suppliers configured for email resolution (pattern or subject-resolved)."""
    try:
        controller = EmailVendorController(db)
        return [supplier_to_response(s) for s in controller.get_all_suppliers()]
    except Exception as e:
        logger.exception("GET /email-vendor/vendors failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch email vendors",
        ) from e


@router.get("/vendors/{vendor_id}", response_model=SupplierEmailResponse)
async def get_email_vendor(
    vendor_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return one supplier by id."""
    try:
        controller = EmailVendorController(db)
        s = controller.get_supplier_by_id(vendor_id)
        if not s:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vendor not found",
            )
        return supplier_to_response(s)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("GET /email-vendor/vendors/%s failed", vendor_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch email vendor",
        ) from e


@router.post(
    "/vendors",
    response_model=SupplierEmailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_email_vendor(
    body: SupplierEmailCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a supplier for email scanning."""
    controller = EmailVendorController(db)
    try:
        created = controller.create_supplier(body.name, body.is_subject_resolved)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        # Log stacktrace so production failures are diagnosable without repro.
        logger.exception("POST /email-vendor/vendors failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e
    logger.info(
        "Email vendor created id=%s by user=%s",
        created.id,
        current_user.username,
    )
    return supplier_to_response(created)


@router.patch("/vendors/{vendor_id}", response_model=SupplierEmailResponse)
async def update_email_vendor(
    vendor_id: int,
    body: SupplierEmailUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Partially update a supplier."""
    controller = EmailVendorController(db)
    updates = {}
    if "name" in body.model_fields_set:
        updates["name"] = body.name
    if "is_subject_resolved" in body.model_fields_set:
        updates["is_subject_resolved"] = body.is_subject_resolved
    try:
        updated = controller.update_supplier(vendor_id, updates)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor not found",
        ) from None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception("PATCH /email-vendor/vendors/%s failed", vendor_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e
    logger.info(
        "Email vendor updated id=%s by user=%s",
        vendor_id,
        current_user.username,
    )
    return supplier_to_response(updated)


@router.delete("/vendors/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email_vendor(
    vendor_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a supplier from email scanning. Returns 400 if rows still reference this supplier."""
    controller = EmailVendorController(db)
    try:
        controller.delete_supplier(vendor_id)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor not found",
        ) from None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        # Log stacktrace so production failures are diagnosable without repro.
        logger.exception("DELETE /email-vendor/vendors/%s failed", vendor_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e
    logger.info(
        "Email vendor deleted id=%s by user=%s",
        vendor_id,
        current_user.username,
    )


@router.post(
    "/vendors/{vendor_id}/patterns",
    response_model=SupplierPatternResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_vendor_pattern(
    vendor_id: int,
    body: SupplierPatternCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a sender pattern to a supplier."""
    controller = EmailVendorController(db)
    try:
        p = controller.add_pattern(
            vendor_id, body.sender_pattern, body.is_active
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor not found",
        ) from None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception("POST /email-vendor/vendors/%s/patterns failed", vendor_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e
    logger.info(
        "Email vendor pattern created id=%s vendor_id=%s by user=%s",
        p.id,
        vendor_id,
        current_user.username,
    )
    return SupplierPatternResponse(
        id=p.id,
        sender_pattern=p.sender_pattern,
        is_active=bool(p.is_active),
    )


@router.patch("/patterns/{pattern_id}", response_model=SupplierPatternResponse)
async def update_vendor_pattern(
    pattern_id: uuid.UUID,
    body: SupplierPatternUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Partially update a pattern."""
    controller = EmailVendorController(db)
    updates = {}
    if "sender_pattern" in body.model_fields_set:
        updates["sender_pattern"] = body.sender_pattern
    if "is_active" in body.model_fields_set:
        updates["is_active"] = body.is_active
    try:
        p = controller.update_pattern(pattern_id, updates)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pattern not found",
        ) from None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        # Log stacktrace so production failures are diagnosable without repro.
        logger.exception("PATCH /email-vendor/patterns/%s failed", pattern_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e
    logger.info(
        "Email vendor pattern updated id=%s by user=%s",
        pattern_id,
        current_user.username,
    )
    return SupplierPatternResponse(
        id=p.id,
        sender_pattern=p.sender_pattern,
        is_active=bool(p.is_active),
    )


@router.delete("/patterns/{pattern_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vendor_pattern(
    pattern_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a pattern."""
    controller = EmailVendorController(db)
    try:
        controller.delete_pattern(pattern_id)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pattern not found",
        ) from None
    except Exception as e:
        logger.exception("DELETE /email-vendor/patterns/%s failed", pattern_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e
    logger.info(
        "Email vendor pattern deleted id=%s by user=%s",
        pattern_id,
        current_user.username,
    )
