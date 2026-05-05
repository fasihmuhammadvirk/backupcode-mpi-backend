from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from mpi_backend.database import get_db
from mpi_backend.database.models.User import User
from mpi_backend.database.controllers.UserController import UserController
from mpi_backend.database.schemas.user_schemas import (
    CreateUserRequest, UpdateUserRequest, UserResponse
)
from mpi_backend.utils.auth.dependencies import get_current_user, require_admin
from mpi_backend.utils.auth.roles import UserRole

router = APIRouter(prefix="/users", tags=["User Management"])


@router.get("", response_model=List[UserResponse])
async def get_all_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Get all users in the system (excluding current admin).

    **Summary:**
        Retrieves a complete list of all users in the system. This endpoint
        automatically excludes the currently logged-in admin user from the
        results to prevent self-management issues (e.g., admins accidentally
        changing their own role or deactivating themselves).

    **Authentication:**
        - Requires valid JWT token in Authorization header
        - **Admin role required** - Only admins can view all users

    **Returns:**
        - **List[UserResponse]**: Array of user objects containing:
            - **id** (`UUID`): User unique identifier
            - **username** (`str`): User login username
            - **email** (`str`): User email address
            - **role** (`str`): User role (admin, bookkeeping, standard)
            - **company_id** (`int`): Associated company ID (null for admins)
            - **is_active** (`bool`): Active status
            - **created_at** (`datetime`): Account creation timestamp
            - **updated_at** (`datetime`): Last update timestamp

    **Response Example:**
    ```json
    [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "username": "john.doe",
            "email": "john@example.com",
            "role": "bookkeeping",
            "company_id": 1,
            "is_active": true,
            "created_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-02-20T14:45:00Z"
        },
        {
            "id": "660e8400-e29b-41d4-a716-446655440111",
            "username": "jane.smith",
            "email": "jane@example.com",
            "role": "standard",
            "company_id": 2,
            "is_active": true,
            "created_at": "2024-03-10T09:15:00Z",
            "updated_at": null
        }
    ]
    ```

    **Filtering:**
        - Automatically excludes the current logged-in admin user
        - This prevents self-management accidents (changing own role, deactivating self)
        - All other users are included (active and inactive)

    **Error Codes:**
        - **403**: Non-admin user attempting to access endpoint

    **Use Cases:**
        - User management dashboard listing
        - User administration and oversight
        - Bulk user operations and reporting
        - User search and filtering interfaces

    **Notes:**
        - Current admin is excluded via SQL query (not post-filtering)
        - Returns users from all companies
        - No pagination applied - returns complete list
        - Includes both active and inactive users
        - To manage your own account, use GET /users/{user_id} with your ID
    """
    users = UserController(db).get_all_users(exclude_user_id=current_user.id)
    return users


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed user information by user ID.

    **Summary:**
        Retrieves detailed information for a specific user identified by their UUID.
        This endpoint implements role-based access control: admins can view any user,
        while non-admin users can only view their own profile information.

    **Path Parameters:**
        - **user_id** (`UUID`, required): The unique identifier of the user to retrieve

    **Authentication:**
        - Requires valid JWT token in Authorization header
        - **Admin**: Can view any user's details
        - **Non-admin**: Can only view their own details (user_id must match token)

    **Returns:**
        - **UserResponse**: User object containing:
            - **id** (`UUID`): User unique identifier
            - **username** (`str`): User login username
            - **email** (`str`): User email address
            - **role** (`str`): User role (admin, bookkeeping, standard)
            - **company_id** (`int`): Associated company ID
            - **is_active** (`bool`): Active status
            - **created_at** (`datetime`): Account creation timestamp
            - **updated_at** (`datetime`): Last update timestamp

    **Response Example:**
    ```json
    {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "username": "john.doe",
        "email": "john@example.com",
        "role": "bookkeeping",
        "company_id": 1,
        "is_active": true,
        "created_at": "2024-01-15T10:30:00Z",
        "updated_at": "2024-02-20T14:45:00Z"
    }
    ```

    **Access Control:**
        - **Admins**: Can retrieve any user by ID for user management
        - **Bookkeeping/Standard users**: Can only retrieve their own profile
        - Access denied if non-admin attempts to view another user

    **Error Codes:**
        - **403**: Non-admin user attempting to view another user's details
        - **404**: User ID not found in database

    **Use Cases:**
        - Displaying user profile information
        - Admin reviewing user details
        - User viewing their own account information
        - Pre-filling user edit forms

    **Notes:**
        - UUID format required for user_id parameter
        - Inactive users can still be retrieved (for audit purposes)
        - Non-admin access limited to self-view only
        - Use for single user lookups, not user listings
    """
    # Allow admin or self
    if current_user.role != UserRole.ADMIN.value and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    user = UserController(db).get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("", response_model=UserResponse)
async def create_user(
    user_data: CreateUserRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Create a new user with role-based access control.

    **Summary:**
        Creates a new user account in the system with specified role and company
        assignment. This endpoint is admin-only and automatically logs the creation
        action with audit trail including who created the user, from what IP address,
        and when the creation occurred.

    **Request Body:**
        - **user_data** (`CreateUserRequest`, required): User creation data
            - **username** (`str`, required): Unique username for login
            - **password** (`str`, required): User password (hashed before storage)
            - **email** (`str`, required): User email address
            - **role** (`UserRole`, required): User role (admin, bookkeeping, standard)
            - **company_id** (`int`, optional): Company to assign user to

    **Request Example:**
    ```json
    {
        "username": "john.doe",
        "password": "SecurePassword123!",
        "email": "john.doe@example.com",
        "role": "bookkeeping",
        "company_id": 1
    }
    ```

    **Authentication:**
        - Requires valid JWT token in Authorization header
        - **Admin role required** - Only admins can create users

    **Returns:**
        - **UserResponse**: Created user object containing:
            - **id** (`UUID`): Newly assigned user ID
            - **username** (`str`): Username (as provided)
            - **email** (`str`): Email address
            - **role** (`str`): Assigned role
            - **company_id** (`int`): Associated company
            - **is_active** (`bool`): Active status (default: true)
            - **created_at** (`datetime`): Creation timestamp
            - **updated_at** (`datetime`): Last update (null for new users)

    **Response Example:**
    ```json
    {
        "id": "770e8400-e29b-41d4-a716-446655440222",
        "username": "john.doe",
        "email": "john.doe@example.com",
        "role": "bookkeeping",
        "company_id": 1,
        "is_active": true,
        "created_at": "2024-12-19T15:45:00Z",
        "updated_at": null
    }
    ```

    **Validation:**
        - Username must be unique (case-insensitive check)
        - Password must meet strength requirements
        - Email format validation applied
        - Role must be valid enum value (admin, bookkeeping, standard)
        - Company ID must exist if provided

    **Error Codes:**
        - **400**: Username already exists or invalid input data
        - **403**: Non-admin user attempting to create user
        - **422**: Invalid request body format or validation errors
        - **500**: Database error during user creation

    **Audit Logging:**
        - Records user creation event in user_audit_logs table
        - Captures: created_by (admin user ID), IP address, timestamp
        - Audit entry created automatically in same transaction
        - Useful for security compliance and user tracking

    **Security:**
        - Password is hashed using bcrypt before database storage
        - Never returns password in response
        - Client IP captured for security auditing
        - Atomic transaction ensures audit log consistency

    **Notes:**
        - New users are active by default (is_active = true)
        - Company assignment is optional (null for admin users)
        - Username uniqueness enforced at database level
        - Timestamps automatically set to current server time
        - User can login immediately after creation
    """
    # Check username doesn't exist
    user_controller = UserController(db)
    existing = user_controller.get_user_by_username(user_data.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    # Get client IP for audit log
    client_ip = request.client.host if request.client else None

    # Create user with audit logging
    user = user_controller.create_user(
        username=user_data.username,
        password=user_data.password,
        email=user_data.email,
        role=user_data.role.value,
        company_id=user_data.company_id,
        created_by=current_user.id,
        ip_address=client_ip
    )

    if not user:
        raise HTTPException(status_code=500, detail="Failed to create user")
    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_data: UpdateUserRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Update an existing user's information.

    **Summary:**
        Updates user account information including email, role, company assignment,
        and active status. This endpoint is admin-only and includes security controls
        to prevent admins from accidentally changing their own role. All updates are
        logged in the audit trail with details of who made the change and when.

    **Path Parameters:**
        - **user_id** (`UUID`, required): The unique identifier of the user to update

    **Request Body:**
        - **user_data** (`UpdateUserRequest`, required): User update data (all optional)
            - **email** (`str`, optional): New email address
            - **role** (`UserRole`, optional): New role (admin, bookkeeping, standard)
            - **company_id** (`int`, optional): New company assignment
            - **is_active** (`bool`, optional): Active status (true/false)

    **Request Example:**
    ```json
    {
        "email": "john.updated@example.com",
        "role": "admin",
        "company_id": 2,
        "is_active": true
    }
    ```

    **Authentication:**
        - Requires valid JWT token in Authorization header
        - **Admin role required** - Only admins can update users

    **Returns:**
        - **UserResponse**: Updated user object containing:
            - **id** (`UUID`): User ID (unchanged)
            - **username** (`str`): Username (unchanged)
            - **email** (`str`): Updated email
            - **role** (`str`): Updated role
            - **company_id** (`int`): Updated company assignment
            - **is_active** (`bool`): Updated active status
            - **created_at** (`datetime`): Original creation time
            - **updated_at** (`datetime`): Update timestamp (now)

    **Response Example:**
    ```json
    {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "username": "john.doe",
        "email": "john.updated@example.com",
        "role": "admin",
        "company_id": 2,
        "is_active": true,
        "created_at": "2024-01-15T10:30:00Z",
        "updated_at": "2024-12-19T16:00:00Z"
    }
    ```

    **Security Controls:**
        - **Self-role protection**: Admins cannot change their own role
        - This prevents accidental lockouts (admin demoting themselves)
        - If admin needs role change, another admin must perform it
        - Applies only to role changes, other fields can be self-updated

    **Partial Updates:**
        - All fields in request body are optional
        - Only provided fields are updated
        - Omitted fields remain unchanged
        - Username cannot be changed (not in UpdateUserRequest)

    **Error Codes:**
        - **400**: Admin attempting to change their own role
        - **403**: Non-admin user attempting to update user
        - **404**: User ID not found in database
        - **422**: Invalid request body format or validation errors
        - **500**: Database error during user update

    **Audit Logging:**
        - Records user update event in user_audit_logs table
        - Captures: changed_by (admin user ID), old values, new values, IP address
        - Audit entry created automatically in same transaction
        - Tracks all field changes for compliance and security

    **Common Update Operations:**
        - **Deactivate user**: Set is_active to false
        - **Change role**: Update role field (bookkeeping ↔ standard)
        - **Reassign company**: Update company_id
        - **Update contact**: Change email address

    **Notes:**
        - Password cannot be updated via this endpoint (use password reset)
        - Username is immutable after creation
        - Updated_at timestamp automatically set on any change
        - Deactivated users cannot login but remain in database
        - Company reassignment doesn't affect user's existing data
    """
    # Prevent admin from changing their own role
    if current_user.id == user_id and user_data.role and user_data.role.value != current_user.role:
        raise HTTPException(
            status_code=400,
            detail="Cannot change your own role. Use another admin account."
        )

    # Get client IP for audit log
    client_ip = request.client.host if request.client else None

    # Update user with audit logging
    user_controller = UserController(db)
    user = user_controller.update_user(
        user_id=user_id,
        changed_by=current_user.id,
        ip_address=client_ip,
        email=user_data.email,
        role=user_data.role.value if user_data.role else None,
        company_id=user_data.company_id,
        is_active=user_data.is_active
    )

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
