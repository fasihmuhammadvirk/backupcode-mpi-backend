"""
User role definitions for authentication and authorization.

This module defines the UserRole enum which provides type-safe role handling throughout the application.
"""

from enum import Enum


class UserRole(str, Enum):
    """
    User role enumeration for access control.

    Roles define what users can access in the system:

    - ADMIN: Full system access including:
        * User management (create, update, deactivate users)
        * All company data access
        * All invoice and accounting columns

    - BOOKKEEPING: Elevated permissions for accounting tasks:
        * Access to invoice accounting columns (account, account_number)
        * Full invoice data access for their company
        * Cannot manage users

    - STANDARD: Basic user permissions:
        * View invoices for their company
        * Restricted from accounting columns
        * Cannot manage users

    Note: This enum uses string values for database compatibility.
    Permission checks should remain explicit rather than hierarchical.
    """

    ADMIN = "admin"
    BOOKKEEPING = "bookkeeping"
    STANDARD = "standard"

    @classmethod
    def values(cls) -> list[str]:
        """Return list of all valid role values."""
        return [role.value for role in cls]
