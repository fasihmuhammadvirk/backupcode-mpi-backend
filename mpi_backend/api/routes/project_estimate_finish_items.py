import os
import logging
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from typing import List

from mpi_backend.database import get_db
from mpi_backend.database.schemas.ProjectEstimateFinishItems import (
    ProjectEstimateFinishItemsRequest,
    ProjectEstimateFinishItemsResponse,
)
from mpi_backend.database.controllers.ProjectEstimateFinishItemsController import (
    ProjectEstimateFinishItemsController,
)
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.database.models.User import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/project-estimate-finish-items",
    tags=["Project Estimate Finish Items"],
)

PROJECT_ESTIMATE_ALLOWED_USER = os.getenv("PROJECT_ESTIMATE_ALLOWED_USER")

@router.get("/items/project/{project_estimate_id}", response_model=List[ProjectEstimateFinishItemsResponse])
def get_finish_items_by_project(
    project_estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get finish items by project.
    """
    controller = ProjectEstimateFinishItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.get_items_by_project(project_estimate_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post("/items", response_model=ProjectEstimateFinishItemsResponse, status_code=status.HTTP_201_CREATED)
def create_finish_item(
    item: ProjectEstimateFinishItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create finish item.
    """
    controller = ProjectEstimateFinishItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.create_item(
            item.name,
            item.price,
            item.qty,
            item.amount,
            item.project_estimate_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/items/{item_id}", response_model=ProjectEstimateFinishItemsResponse)
def update_finish_item(
    item_id: int,
    item: ProjectEstimateFinishItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update finish item.
    """
    controller = ProjectEstimateFinishItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.update_item(
            item_id,
            item.name,
            item.price,
            item.qty,
            item.amount,
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating finish item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_finish_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete finish item.
    """
    controller = ProjectEstimateFinishItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        controller.delete_item(item_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting finish item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
