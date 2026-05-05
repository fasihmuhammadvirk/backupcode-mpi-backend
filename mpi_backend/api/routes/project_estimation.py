import os
import logging
from fastapi import APIRouter, HTTPException, status, Depends
from mpi_backend.database import get_db
from mpi_backend.database.schemas.ProjectEstimation import ProjectEstimationRequest, ProjectEstimationResponse
from mpi_backend.database.controllers.ProjectEstimationController import ProjectEstimationController
from sqlalchemy.orm import Session
from typing import List
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.database.models.User import User

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/project-estimation", tags=["Project Estimation"])

PROJECT_ESTIMATE_ALLOWED_USER = os.getenv("PROJECT_ESTIMATE_ALLOWED_USER")

@router.post("/create/", response_model=ProjectEstimationResponse)
def create_project_estimation(
    project_estimation: ProjectEstimationRequest, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Create a new project estimation.
    """
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        controller = ProjectEstimationController(db)
        new_project_estimation = controller.create_estimation(project_estimation.model_dump(), current_user.id)
        return new_project_estimation
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error in get Project Estimation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/list/", response_model=List[ProjectEstimationResponse])
def get_project_estimations_by_user(
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """
    Get all project estimations for the authenticated user.
    
    The `current_user` is automatically fetched from the JWT token.
    """
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        controller = ProjectEstimationController(db)
        project_estimations = controller.get_estimations_by_user(current_user.id)
        return project_estimations
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error in get Project Estimation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{project_estimation_id}", response_model=ProjectEstimationResponse)
def get_project_estimation_by_id(
    project_estimation_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Get a project estimation by its ID.
    """
    controller = ProjectEstimationController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        project_estimation = controller.get_estimation_by_id(project_estimation_id, current_user.id)
        return project_estimation
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error in get Project Estimation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{project_estimation_id}", response_model=ProjectEstimationResponse)
def update_project_estimation(
    project_estimation_id: int, 
    project_estimation: ProjectEstimationRequest, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Update a project estimation.
    """
    controller = ProjectEstimationController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        updated_estimation = controller.update_estimation(project_estimation_id, current_user.id, project_estimation.model_dump(exclude_unset=True))
        return updated_estimation
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error in update Project Estimation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/{project_estimation_id}")
def delete_project_estimation(
    project_estimation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a project estimation.
    """
    controller = ProjectEstimationController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        controller.delete_estimation(project_estimation_id, current_user.id)
        return {"message": "Project estimation deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error in delete Project Estimation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
