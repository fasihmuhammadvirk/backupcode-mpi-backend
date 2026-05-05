from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from mpi_backend.database import get_db
from mpi_backend.database.models.User import User
from mpi_backend.database.controllers.CompanyController import CompanyController
from mpi_backend.database.schemas.user_schemas import CompanyResponse
from mpi_backend.utils.auth.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.get("", response_model=List[CompanyResponse])
async def get_all_companies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all companies in the system.

    **Summary:**
        Retrieves a complete list of all companies registered in the system.
        This endpoint is commonly used for populating company dropdown menus
        in user management interfaces and for displaying company selections.

    **Authentication:**
        - Requires valid JWT token in Authorization header
        - Available to all authenticated users (admin, bookkeeping, standard)

    **Returns:**
        - **List[CompanyResponse]**: Array of company objects containing:
            - **id** (`int`): Company unique identifier
            - **name** (`str`): Company name
            - **created_at** (`datetime`): Company creation timestamp

    **Response Example:**
    ```json
    [
        {
            "id": 1,
            "name": "ABC Plumbing Supply",
            "created_at": "2024-01-15T10:30:00Z"
        },
        {
            "id": 2,
            "name": "XYZ Construction",
            "created_at": "2024-02-20T14:45:00Z"
        }
    ]
    ```

    **Use Cases:**
        - Populating company selection dropdowns in user management
        - Displaying available companies for user assignment
        - Company browsing and selection interfaces
        - Reporting and analytics company filters

    **Notes:**
        - Returns all companies regardless of active status
        - No pagination applied - returns complete list
        - Ordered by company name or creation date
        - Users from all roles can view the company list
    """
    companies = CompanyController(db).get_all_companies()
    return companies


@router.post("", response_model=CompanyResponse)
async def create_company(
    company_data: dict,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Create a new company in the system.

    **Summary:**
        Creates a new company record in the database. This endpoint is restricted
        to admin users only and validates that the company name is unique before
        creation. Once created, the company can be assigned to users.

    **Request Body:**
        - **company_data** (`dict`, required): Company creation data
            - **name** (`str`, required): Unique company name

    **Request Example:**
    ```json
    {
        "name": "New Construction Company"
    }
    ```

    **Authentication:**
        - Requires valid JWT token in Authorization header
        - **Admin role required** - Only admins can create companies

    **Returns:**
        - **CompanyResponse**: Created company object containing:
            - **id** (`int`): Newly assigned company ID
            - **name** (`str`): Company name
            - **created_at** (`datetime`): Creation timestamp

    **Response Example:**
    ```json
    {
        "id": 5,
        "name": "New Construction Company",
        "created_at": "2024-12-19T15:30:00Z"
    }
    ```

    **Validation:**
        - Company name is required (cannot be empty)
        - Company name must be unique (case-sensitive check)
        - Name length and format validation applied

    **Error Codes:**
        - **400**: Missing company name or company already exists
        - **403**: Non-admin user attempting to create company
        - **500**: Database error during company creation

    **Creation Process:**
        1. Validates admin role authorization
        2. Checks company name is provided
        3. Verifies company name doesn't already exist
        4. Creates company record in database
        5. Returns created company with assigned ID

    **Notes:**
        - Company names are case-sensitive
        - Duplicate names are rejected with descriptive error
        - Created companies are immediately available for user assignment
        - Timestamp is automatically set to current server time
        - Future: Will support additional fields (settings, subscription tier)
    """
    name = company_data.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Company name required")

    company_controller = CompanyController(db)

    # Check if company already exists
    existing = company_controller.get_company_by_name(name)
    if existing:
        raise HTTPException(status_code=400, detail=f"Company '{name}' already exists")

    company = company_controller.create_company(name)
    if not company:
        raise HTTPException(status_code=500, detail="Failed to create company")
    return company
