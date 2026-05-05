import os
import logging
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from typing import List

from mpi_backend.database import get_db
from mpi_backend.database.schemas.ProjectEstimateFinishQuickItems import (
    ProjectEstimateFinishQuickItemsRequest,
    ProjectEstimateFinishQuickItemsResponse,
)
from mpi_backend.database.controllers.ProjectEstimateFinishQuickItemsController import (
    ProjectEstimateFinishQuickItemsController,
)
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.database.models.User import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/project-estimate-finish-quick-items",
    tags=["Project Estimate Finish Quick Items"],
)

PROJECT_ESTIMATE_ALLOWED_USER = os.getenv("PROJECT_ESTIMATE_ALLOWED_USER")

@router.get("/items", response_model=List[ProjectEstimateFinishQuickItemsResponse])
def get_all_finish_quick_items(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all finish quick items.
    """
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        controller = ProjectEstimateFinishQuickItemsController(db)
        return controller.get_all_items()
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating quick item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/items", response_model=ProjectEstimateFinishQuickItemsResponse, status_code=status.HTTP_201_CREATED)
def create_finish_quick_item(
    item: ProjectEstimateFinishQuickItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create finish quick item.
    """
    controller = ProjectEstimateFinishQuickItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.create_item(item.name, item.price)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating quick item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/items/{item_id}", response_model=ProjectEstimateFinishQuickItemsResponse)
def update_finish_quick_item(
    item_id: int,
    item: ProjectEstimateFinishQuickItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update finish quick item.
    """
    controller = ProjectEstimateFinishQuickItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.update_item(item_id, item.name, item.price)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating quick item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_finish_quick_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete finish quick item.
    """
    controller = ProjectEstimateFinishQuickItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        controller.delete_item(item_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting quick item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
