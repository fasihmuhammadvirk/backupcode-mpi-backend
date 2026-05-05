"""
Schema selector for role-based column access control.

Provides functions to select appropriate Pydantic schemas based on user roles and validate column access
permissions.
"""

from typing import Type, Union
from fastapi import HTTPException, status
from mpi_backend.database.models.User import User
from mpi_backend.database.schemas.InvoiceItems import (
    InvoiceItemFull,
    InvoiceItemStandard,
)
from mpi_backend.utils.auth.roles import UserRole


# Column access control configuration
# Maps role to list of columns they CANNOT access
RESTRICTED_COLUMNS = {
    UserRole.STANDARD.value: ['account', 'account_number']  # Standard users cannot see account fields
    # UserRole.BOOKKEEPING.value: [],  # Bookkeeping can see everything
    # UserRole.ADMIN.value: [],  # Admin can see everything
}


def get_invoice_item_schema(user: User) -> Type[Union[InvoiceItemFull, InvoiceItemStandard]]:
    """
    Get appropriate InvoiceItem schema based on user role.

    Args:
        user: Authenticated user object with role attribute

    Returns:
        InvoiceItemFull for admin/bookkeeping (includes account field)
        InvoiceItemStandard for standard users (excludes account field)
    """
    if user.role in [UserRole.ADMIN.value, UserRole.BOOKKEEPING.value]:
        return InvoiceItemFull
    return InvoiceItemStandard


def validate_column_access(column_name: str, user_role: str) -> None:
    """
    Validate that a user role can access a specific column.

    Raises HTTPException(403) if the column is restricted for the role.

    Args:
        column_name: Name of the column to access
        user_role: User's role (admin, bookkeeping, standard)

    Raises:
        HTTPException: 403 Forbidden if access is denied
    """
    restricted_for_role = RESTRICTED_COLUMNS.get(user_role, [])

    if column_name in restricted_for_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"  # Don't reveal which column is restricted
        )


def can_access_column(column_name: str, user_role: str) -> bool:
    """
    Check if a user role can access a specific column.

    Args:
        column_name: Name of the column to check
        user_role: User's role (admin, bookkeeping, standard)

    Returns:
        True if access is allowed, False otherwise
    """
    restricted_for_role = RESTRICTED_COLUMNS.get(user_role, [])
    return column_name not in restricted_for_role
