import logging

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.controllers.SupplierComparison import SupplierComparison
from mpi_backend.database.models.User import User
from mpi_backend.database.schemas.SupplierComparison import (
    SupplierComparisonRequest,
    SupplierComparisonResponse,
    SupplierComparisonSummary
)
from mpi_backend.utils.auth.dependencies import get_current_user

router = APIRouter(prefix="/supplier-comparison", tags=["Supplier Comparison"])
logger = logging.getLogger(__name__)

@router.post("/summary", response_model=SupplierComparisonSummary)
def get_comparison_summary(
    request: SupplierComparisonRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get summary statistics for the supplier comparison dashboard.

    **Request Body:**
        - from_date: Optional[date] - Start date for filtering metrics (YYYY-MM-DD).
        - to_date: Optional[date] - End date for filtering metrics (YYYY-MM-DD).
        - supplier_name: Optional[str] - Filter metrics based on items sold by this supplier.
        - search: Optional[str] - Search by item code or reference number.

    **Authentication:**
        - Requires valid JWT token in Authorization header.

    **Returns:**
        - SupplierComparisonSummary - Object containing global metrics and supplier cards.

    **Response Example:**
        ```json
        {
            "total_missed_savings": 1250.50,
            "item_count": 45,
            "highest_priced_supplier": "Expensive Inc.",
            "highest_priced_excess_amount": 500.00,
            "highest_impact_item_codes": ["MPI001", "MPI002"],
            "highest_priced_loss_rate": 85.5,
            "top_value_supplier": "Economy Co.",
            "top_value_saved_amount": 300.25,
            "top_value_win_rate": 95.0,
            "top_value_item_codes": ["MPI003", "MPI004"]
        }
        ```

    **Error Codes:**
        - **500**: Internal server error
    """
    try:
        controller = SupplierComparison(db)
        return controller.get_comparison_summary(request)
    except Exception as e:
        logger.error(f"Error in get_comparison_summary: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/table", response_model=SupplierComparisonResponse)
def supplier_price_compare(
    request: SupplierComparisonRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get the main supplier comparison table with pagination and nested vendor details.

    **Summary:**
        - Returns a paginated list of items with their market best prices and potential savings.
        - Provides nested details for every vendor selling each item.
        - Supports dynamic sorting by savings, quotes, and description.

    **Request Body:**
        - from_date: Optional[date] - Start date for comparison (YYYY-MM-DD).
        - to_date: Optional[date] - End date for comparison (YYYY-MM-DD).
        - supplier_name: Optional[str] - Scope items to those sold by this specific supplier.
        - item_mpi_codes: Optional[List[str]] - Filter by specific MPI item codes.
        - search: Optional[str] - Search by MPI item code or reference number.
        - page: Optional[int] - Page number for pagination (starting from 1).
        - page_size: Optional[int] - Items per page.
        - sort_by: Optional[str] - Field to sort by (potential_savings, quotes, item_description).
        - sort_order: Optional[str] - Sort direction (asc, desc).

    **Authentication:**
        - Requires valid JWT token in Authorization header.

    **Returns:**
        - SupplierComparisonResponse - Paginated items with nested vendor comparison arrays.

    **Response Example:**
        ```json
        {
            "items": [
                {
                    "item_mpi_code": "MPI001",
                    "item_description": "Sample Item",
                    "quotes_count": 2,
                    "best_price": 45.00,
                    "potential_savings": 15.50,
                    "vendor_details": [
                        {
                            "supplier_name": "Vendor A",
                            "purchase_date": "2024-01-15",
                            "ref_no": "INV_123",
                            "quantity": 10.0,
                            "unit_price": 50.00,
                            "variance_amount": 5.00,
                            "variance_percentage": 11.1,
                            "is_best_value": false
                        }
                    ]
                }
            ],
            "total_count": 100,
            "page": 1,
            "page_size": 20
        }
        ```

    **Error Codes:**
        - **500**: Internal server error
    """
    try:
        controller = SupplierComparison(db)
        return controller.get_comparison_table(request)
    except Exception as e:
        logger.error(f"Error in get_comparison_table: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/export")
def supplier_price_compare_export(
    request: SupplierComparisonRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Export the supplier comparison data as a CSV file.

    **Summary:**
        - Generates a downloadable CSV of all items matching the criteria.
        - Includes detailed vendor information for each item.
        - Useful for offline analysis and reporting.

    **Request Body:**
        - from_date: Optional[date] - Start date for export (YYYY-MM-DD).
        - to_date: Optional[date] - End date for export (YYYY-MM-DD).
        - supplier_name: Optional[str] - Scope items to those sold by this specific supplier.
        - item_mpi_codes: Optional[List[str]] - Filter by specific MPI item codes.
        - search: Optional[str] - Search by MPI item code or reference number.
        - sort_by: Optional[str] - Field to sort by (potential_savings, quotes, item_description).
        - sort_order: Optional[str] - Sort direction (asc, desc).

    **Authentication:**
        - Requires valid JWT token in Authorization header.

    **Returns:**
        - For small datasets (<1000 records): Returns streaming CSV response immediately.
        - For large datasets (>=1000 records): Returns export_id for async processing via S3.

    **Error Codes:**
        - **500**: Internal server error
    """
    try:
        controller = SupplierComparison(db)
        result = controller.export_comparison_data(request, background_tasks)

        if result.get("type") == "streaming":
            return StreamingResponse(
                result["generator"],
                media_type="text/csv",
                headers={
                    'Content-Disposition': f'attachment; filename="{result["filename"]}"'
                }
            )

        return JSONResponse(content={
            "export_id": result["export_id"],
            "status": result["status"],
            "record_count": result["record_count"],
            "message": result["message"],
            "status_endpoint": result.get("status_endpoint")
        })
    except Exception as e:
        logger.error(f"Error in supplier_price_compare_export: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

