import os
import logging
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from typing import List

from mpi_backend.database import get_db
from mpi_backend.database.schemas.ProjectEstimateSubItems import (
    ProjectEstimateSubItemRequest,
    ProjectEstimateSubItemResponse,
)
from mpi_backend.database.controllers.ProjectEstimateSubItemController import (
    ProjectEstimateSubItemController,
)
from mpi_backend.database.controllers.ProjectEstimationController import (
    ProjectEstimationController,
)
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.database.models.User import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/project-estimate-sub-items",
    tags=["Project Estimate Sub Items"],
)

PROJECT_ESTIMATE_ALLOWED_USER = os.getenv("PROJECT_ESTIMATE_ALLOWED_USER")

@router.get("/items/project/{project_estimate_id}", response_model=List[ProjectEstimateSubItemResponse])
def get_sub_items_by_project(
    project_estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get sub items for a project estimation.
    """
    if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
        raise PermissionError("Access denied to this project estimation.")

    controller = ProjectEstimateSubItemController(db)

    try:
        return controller.get_items_by_project(project_estimate_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting sub items: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/items", response_model=ProjectEstimateSubItemResponse, status_code=status.HTTP_201_CREATED)
def create_sub_item(
    sub_item: ProjectEstimateSubItemRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create sub item.
    """
    if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
        raise PermissionError("Access denied to this project estimation.")

    controller = ProjectEstimateSubItemController(db)

    try:
        new_item = controller.create_item(
            sub_item.name,
            sub_item.price,
            sub_item.type,
            sub_item.project_estimate_id,
        )
        return new_item

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating sub item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/items/{item_id}", response_model=ProjectEstimateSubItemResponse)
def update_sub_item(
    item_id: int,
    sub_item: ProjectEstimateSubItemRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update sub item.
    """
    if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
        raise PermissionError("Access denied to this project estimation.")

    controller = ProjectEstimateSubItemController(db)

    try:
        updated = controller.update_item(
            item_id,
            sub_item.name,
            sub_item.price,
            sub_item.type,
            sub_item.project_estimate_id,
        )
        return updated

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating sub item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sub_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete sub item.
    """
    if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
        raise PermissionError("Access denied to this project estimation.")

    controller = ProjectEstimateSubItemController(db)

    try:
        controller.delete_item(item_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting sub item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
