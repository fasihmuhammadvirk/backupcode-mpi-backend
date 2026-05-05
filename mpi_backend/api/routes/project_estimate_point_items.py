import os
import logging
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from typing import List

from mpi_backend.database import get_db
from mpi_backend.database.schemas.ProjectEstimatePointItems import (
    ProjectEstimatePointItemsRequest,
    ProjectEstimatePointItemsResponse,
)
from mpi_backend.database.controllers.ProjectEstimatePointItemsController import (
    ProjectEstimatePointItemsController,
)
from mpi_backend.database.controllers.ProjectEstimationController import (
    ProjectEstimationController,
)
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.database.models.User import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project-estimate-point-items", tags=["Project Estimate Point Items"])

PROJECT_ESTIMATE_ALLOWED_USER = os.getenv("PROJECT_ESTIMATE_ALLOWED_USER")

@router.get("/items/project/{project_estimate_id}", response_model=List[ProjectEstimatePointItemsResponse])
def get_point_items_by_project(
    project_estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get point items for a project estimation.
    """
    controller = ProjectEstimatePointItemsController(db)

    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.get_items_by_project(project_estimate_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error retrieving point items: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/items", response_model=ProjectEstimatePointItemsResponse, status_code=status.HTTP_201_CREATED)
def create_point_item(
    item: ProjectEstimatePointItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a point item.
    """
    controller = ProjectEstimatePointItemsController(db)

    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.create_item(item.name, item.pts, item.qty, item.amount, item.project_estimate_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating point item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/items/{item_id}", response_model=ProjectEstimatePointItemsResponse)
def update_point_item(
    item_id: int,
    item: ProjectEstimatePointItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update a point item.
    """
    controller = ProjectEstimatePointItemsController(db)

    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.update_item(
            item_id,
            item.name,
            item.pts,
            item.qty,
            item.amount,
            item.project_estimate_id,
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating point item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_point_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a point item.
    """
    controller = ProjectEstimatePointItemsController(db)

    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        controller.delete_item(item_id)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting Project Estimate Point Item : {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
