import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.controllers.ProjectEstimateFixedItemsController import (
    ProjectEstimateFixedItemsController,
)
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.database.models.User import User
from mpi_backend.database.schemas.ProjectEstimateFixedItems import (
    ProjectEstimateFixedItemsRequest,
    ProjectEstimateFixedItemsResponse,
)

router = APIRouter(
    prefix="/project-estimate-fixed-items",
    tags=["Project Estimate Fixed Items"],
)

PROJECT_ESTIMATE_ALLOWED_USER = os.getenv("PROJECT_ESTIMATE_ALLOWED_USER")

@router.get("/items/{item_id}", response_model=ProjectEstimateFixedItemsResponse)
def get_project_estimate_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Fetch a single project estimate fixed item by ID.

    Args:
        item_id (int): ID of the fixed item.
        db (Session): Database session.
        current_user (User): Current logged-in user.

    Returns:
        ProjectEstimateFixedItemsResponse: Requested item.

    Raises:
        HTTPException: 404 if item not found.
    """
    controller = ProjectEstimateFixedItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        item = controller.get_item_by_id(item_id)
        return item
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/items",
    response_model=ProjectEstimateFixedItemsResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_estimate_fixed_item(
    data: ProjectEstimateFixedItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new project estimate fixed item.

    Args:
        data (ProjectEstimateFixedItemsRequest): Item payload.
        db (Session): Database session.
        current_user (User): Current logged-in user.

    Returns:
        ProjectEstimateFixedItemsResponse: Created item.
    """
    controller = ProjectEstimateFixedItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.create_item(
            data.name,
            data.price,
            data.project_estimation_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.put("/items/{item_id}", response_model=ProjectEstimateFixedItemsResponse)
def update_project_estimate_fixed_item(
    item_id: int,
    item : ProjectEstimateFixedItemsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update an existing project estimate fixed item.

    Args:
        item_id (int): Item ID.
        item (ProjectEstimateFixedItemsRequest): Updated item data.
        db (Session): Database session.
        current_user (User): Current logged-in user.

    Returns:
        ProjectEstimateFixedItemsResponse: Updated item.

    Raises:
        HTTPException: 404 if item not found.
    """
    controller = ProjectEstimateFixedItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.update_item(item_id, item.name, item.price, item.project_estimation_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_estimate_fixed_item(item_id: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user) ):
    """
    Delete a project estimate fixed item.

    Args:
        item_id (int): Item ID.
        db (Session): Database session.
        current_user (User): Current logged-in user.

    Returns:
        None

    Raises:
        HTTPException: 404 if item not found.
    """
    controller = ProjectEstimateFixedItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        controller.delete_item(item_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/items/project/{project_id}",
    response_model=List[ProjectEstimateFixedItemsResponse],
)
def get_items_by_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Fetch all fixed items for a specific project estimation.

    Args:
        project_id (int): Project estimation ID.
        db (Session): Database session.
        current_user (User): Current logged-in user.

    Returns:
        List[ProjectEstimateFixedItemsResponse]: Items for the project.

    Raises:
        HTTPException: 404 if no items found.
    """
    controller = ProjectEstimateFixedItemsController(db)
    try:
        if str(current_user.id) != PROJECT_ESTIMATE_ALLOWED_USER:
            raise PermissionError("Access denied to this project estimation.")
        return controller.get_items_by_project(project_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
