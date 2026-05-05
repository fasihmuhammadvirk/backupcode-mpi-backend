import os
import logging
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from typing import List

from mpi_backend.database import get_db
from mpi_backend.database.schemas.ProjectEstimateFixedQuickItems import (
    ProjectEstimateFixedQuickItemsRequest,
    ProjectEstimateFixedQuickItemsResponse,
)
from mpi_backend.database.controllers.ProjectEstimateFixedQuickItemsController import (
    ProjectEstimateFixedQuickItemsController,
)
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.database.models.User import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/project-estimate-fixed-quick-items",
    tags=["Project Estimate Fixed Quick Items"],
)

PROJECT_ESTIMATE_ALLOWED_USER = os.getenv("PROJECT_ESTIMATE_ALLOWED_USER")

@router.post("/create/", response_model=ProjectEstimateFixedQuickItemsResponse)
def create_quick_item(
    quick_item: ProjectEstimateFixedQuickItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a quick item.

    Quick items are global presets, so only authentication is required.
    """
    controller = ProjectEstimateFixedQuickItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")

        new_item = controller.create_item(
            quick_item.name,
            quick_item.amount,
        )

        if not new_item:
            raise HTTPException(status_code=400, detail="Failed to create item")

        return new_item

    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating Quick Item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/items", response_model=List[ProjectEstimateFixedQuickItemsResponse])
def list_quick_items(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all quick items.
    """
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")

        controller = ProjectEstimateFixedQuickItemsController(db)
        return controller.get_all_items()
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating Quick Item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/items/{item_id}", response_model=ProjectEstimateFixedQuickItemsResponse)
def get_quick_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get quick item by ID.
    """
    controller = ProjectEstimateFixedQuickItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.get_item_by_id(item_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.put("/items/{item_id}", response_model=ProjectEstimateFixedQuickItemsResponse)
def update_quick_item(
    item_id: int,
    quick_item: ProjectEstimateFixedQuickItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update quick item.
    """
    controller = ProjectEstimateFixedQuickItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.update_item(
            item_id,
            quick_item.name,
            quick_item.amount,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.delete("/items/{item_id}")
def delete_quick_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete quick item.
    """
    controller = ProjectEstimateFixedQuickItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        controller.delete_item(item_id)
        return {"message": "Quick item deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
