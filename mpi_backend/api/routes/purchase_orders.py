import logging
from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.controllers.PurchaseOrders import PurchaseOrder
from mpi_backend.database.models.User import User
from mpi_backend.database.schemas.PurchaseOrder import PODraftSummary, PODraftCreate, PODraftDetail, PaginatedPODraftResponse
from mpi_backend.database.schemas.PurchaseOrder import (
    POItemResponse,
    POBulkImportRequest
)
from mpi_backend.utils.auth.dependencies import get_current_user

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])
logger = logging.getLogger(__name__)


@router.post(path="/price-comparison", response_model=List[POItemResponse])
def bulk_import_items(
        request: POBulkImportRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Get the cheapest price comparison based on given filters from PDF extracted line items.

    **Summary:**
        - Accepts a list of MPI item codes, item codes, supplier names, and date range.
        - Returns a list of purchase order items with the best prices from the database.

    **Request Body:**
        - item_mpi_codes: Optional[List[str]] - List of MPI item codes to filter.
        - item_codes: Optional[List[str]] - List of item codes identified from invoice.
        - supplier_names: Optional[List[str]] - List of supplier names to filter.
        - from_date: Optional[date] - Start date for filtering purchase orders (YYYY-MM-DD).
        - to_date: Optional[date] - End date for filtering purchase orders (YYYY-MM-DD).

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - List[POItemResponse] - List of purchase order items with best prices.

    **Response Example:**
        ```json
        [
            {
                "invoice_item_id": 12345.67,
                "item_code": "ITEM001",
                "item_description": "Sample Item Description",
                "item_cost": 99.99,
                "purchase_date": "2023-01-15",
                "supplier_id": 1,
                "supplier_name": "Best Supplier Inc.",
                "item_mpi_code": "MPI001",
                "item_mpi_description": "Sample MPI Item Description"
            }
        ]
        ...

    **Error Codes:**
        - **500**: Internal server error
    """
    purchase_order_controller = PurchaseOrder(db)
    try:
        return purchase_order_controller.get_price_comparison(request)
    except Exception as e:
        logger.error(f"Error in bulk_import_items: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/price-comparison/export")
def export_price_comparison_to_csv(
        request: List[POItemResponse],
        background_tasks: BackgroundTasks,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Export price comparison data to CSV.

    For small datasets (<1000 records): Returns streaming CSV response immediately.
    For large datasets (>=1000 records): Returns export_id for async processing via S3.

    The async response includes a status_endpoint to poll for completion and download URL.
    """
    if not request:
        raise HTTPException(status_code=400, detail="No data provided")

    purchase_order_controller = PurchaseOrder(db)
    result = purchase_order_controller.export_price_comparison_to_csv(
        data=request,
        background_tasks=background_tasks
    )

    # Handle streaming response (small datasets)
    if result.get("type") == "streaming":
        return StreamingResponse(
            result["generator"],
            media_type="text/csv",
            headers={
                'Content-Disposition': f'attachment; filename="{result["filename"]}"'
            }
        )

    # Handle async response (large datasets)
    return JSONResponse(content={
        "export_id": result["export_id"],
        "status": result["status"],
        "record_count": result["record_count"],
        "message": result["message"],
        "status_endpoint": result["status_endpoint"]
    })


@router.post("/price-comparison/export/pdf")
def export_price_comparison_to_pdf(
        request: List[POItemResponse],
        background_tasks: BackgroundTasks,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Export price comparison data as a styled PDF purchase order document.

    For small datasets (<1000 records): Returns binary PDF stream immediately.
    For large datasets (>=1000 records): Returns export_id for async processing via S3.
    """
    if not request:
        raise HTTPException(status_code=400, detail="No data provided")

    purchase_order_controller = PurchaseOrder(db)
    try:
        result = purchase_order_controller.export_price_comparison_to_pdf(
            data=request,
            background_tasks=background_tasks
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating purchase order PDF: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate PDF")

    # Handle streaming response (small datasets)
    if isinstance(result, dict) and result.get("type") == "streaming":
        import io
        return StreamingResponse(
            io.BytesIO(result["pdf_bytes"]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{result["filename"]}"'
            }
        )

    # Handle async response (large datasets)
    return JSONResponse(content={
        "export_id": result["export_id"],
        "status": result["status"],
        "record_count": result["record_count"],
        "message": result["message"],
        "status_endpoint": result["status_endpoint"]
    })



@router.post("/draft", response_model=PODraftSummary)
def save_draft(
    request: PODraftCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Save a new purchase order draft to the database.
    """
    controller = PurchaseOrder(db)
    try:
        return controller.save_draft(request, current_user.id)
    except Exception as e:
        logger.error(f"Error saving draft: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save draft")

@router.get("/draft", response_model=PaginatedPODraftResponse)
def get_drafts_summary(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a paginated list of purchase order drafts summary.
    """
    controller = PurchaseOrder(db)
    try:
        return controller.get_drafts_summary(page, size)
    except Exception as e:
        logger.error(f"Error fetching drafts: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch drafts")

@router.get("/draft/{draft_id}", response_model=PODraftDetail)
def get_draft_detail(
    draft_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get full details of a specific purchase order draft.
    """
    controller = PurchaseOrder(db)
    draft = controller.get_draft_detail(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft

@router.delete("/draft/{draft_id}")
def delete_draft(
    draft_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a purchase order draft.
    """
    controller = PurchaseOrder(db)
    if not controller.delete_draft(draft_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"message": "Draft deleted successfully"}