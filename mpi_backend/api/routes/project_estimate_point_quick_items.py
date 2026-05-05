import os
import logging
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from typing import List

from mpi_backend.database import get_db
from mpi_backend.database.schemas.ProjectEstimatePointQuickItems import (
    ProjectEstimatePointQuickItemsRequest,
    ProjectEstimatePointQuickItemsResponse,
)
from mpi_backend.database.controllers.ProjectEstimatePointQuickItemsController import (
    ProjectEstimatePointQuickItemsController,
)
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.database.models.User import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/project-estimate-point-quick-items",
    tags=["Project Estimate Point Quick Items"],
)

PROJECT_ESTIMATE_ALLOWED_USER = os.getenv("PROJECT_ESTIMATE_ALLOWED_USER")

@router.get("/items", response_model=List[ProjectEstimatePointQuickItemsResponse])
def get_all_quick_point_items(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all quick point items.
    """
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")

        controller = ProjectEstimatePointQuickItemsController(db)
        return controller.get_all_items()
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating Quick Item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/items", response_model=ProjectEstimatePointQuickItemsResponse, status_code=status.HTTP_201_CREATED)
def create_quick_point_item(
    item: ProjectEstimatePointQuickItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create quick point item.
    """
    controller = ProjectEstimatePointQuickItemsController(db)

    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.create_item(item.name, item.amount)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating Quick Item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/items/{item_id}", response_model=ProjectEstimatePointQuickItemsResponse)
def update_quick_point_item(
    item_id: int,
    item: ProjectEstimatePointQuickItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update quick point item.
    """
    controller = ProjectEstimatePointQuickItemsController(db)

    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.update_item(item_id, item.name, item.amount)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quick_point_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete quick point item.
    """
    controller = ProjectEstimatePointQuickItemsController(db)

    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        controller.delete_item(item_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
