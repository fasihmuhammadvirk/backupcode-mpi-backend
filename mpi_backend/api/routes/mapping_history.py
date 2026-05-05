import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.dao import get_item_history
from mpi_backend.database.models.User import User
from mpi_backend.database.schemas.MappingTimeline import (
    MappingHistoryRequest,
    MappingHistoryResponse,
)
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.utils.auth.dependencies import get_current_user

router = APIRouter(prefix="/mapping-history", tags=["Mapping History"])
logger = logging.getLogger(__name__)


@router.post("/item", response_model=MappingHistoryResponse)
def get_item_mapping_history(
        request: MappingHistoryRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """
    Get the full mapping status history for a single supplier item.

    **Summary:**
        Returns a chronological list of mapping state events (oldest first)
        for one (supplier_item_ids, supplier_id) pair.

        Rows where supplier_id IS NULL for the same item code are always included
        (temporary mappings often have no supplier context).

    **Request Body:**
        - supplier_item_ids: Supplier item code shown on the invoice (required)
        - supplier_name: Supplier Name (optional — NULL rows always included)

    **Returns:**
        - supplier_item_ids, supplier_id
        - events: Ordered list of mapping state events:
            - mapping_type: no_match | temporary | permanent
            - recorded_at: ISO timestamp when this state was first observed
            - supplier_id: Supplier ID for this entry (may be null)
            - supplier: Supplier name

    **Response Example:**
        ```json
        {
            "supplier_item_ids": "SP*00011341-W",
            "supplier_id": 3,
            "events": [
                {
                    "mapping_type": "no_match",
                    "recorded_at": "2023-12-10T09:15:00",
                    "supplier_id": 3,
                    "supplier": "World Wide Plumbing"
                },
                {
                    "mapping_type": "temporary",
                    "recorded_at": "2023-10-25T14:30:00",
                    "supplier_id": null,
                    "supplier": null
                },
                {
                    "mapping_type": "permanent",
                    "recorded_at": "2023-11-04T11:45:00",
                    "supplier_id": 3,
                    "supplier": "World Wide Plumbing"
                }
            ]
        }
        ```

    **Error Codes:**
        - **422**: Validation error (empty supplier_item_ids)
        - **500**: Internal server error
    """
    try:
        # Resolve supplier_name to supplier_id if provided
        supplier_id = None
        if request.supplier_name:
            supplier_id = SupplierController(db).get_supplier_name(request.supplier_name)
            if supplier_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Supplier '{request.supplier_name}' not found",
                )

        events = get_item_history(
            db=db,
            supplier_item_ids=request.supplier_item_ids,
            supplier_id=supplier_id,
        )
        response = MappingHistoryResponse(
            supplier_item_ids=request.supplier_item_ids,
            supplier_id=supplier_id,
            events=events,
        )
        return JSONResponse(content=response.model_dump())
    except Exception as e:
        logger.error(f"Error fetching mapping history for item='{request.supplier_item_ids}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
