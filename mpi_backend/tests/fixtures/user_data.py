"""
Test data factories for user-related entities.

Provides reusable test data builders for users, companies, and authentication.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import uuid4, UUID


class UserFactory:
    """Factory for creating test user data."""
    
    @staticmethod
    def create(
        id: Optional[UUID] = None,
        username: str = "test_user",
        password: str = "hashed_password_here",
        email: Optional[str] = None,
        role: str = "standard",
        company_id: Optional[int] = None,
        is_active: bool = True,
        created_at: Optional[datetime] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a test user.
        
        Args:
            id: User UUID
            username: Username
            password: Hashed password
            email: Email address
            role: User role (admin, bookkeeping, standard)
            company_id: Company ID
            is_active: Is active flag
            created_at: Creation timestamp
            **kwargs: Additional fields
            
        Returns:
            Dictionary with user data
        """
        return {
            "id": id or uuid4(),
            "username": username,
            "password": password,
            "email": email or f"{username}@test.com",
            "role": role,
            "company_id": company_id,
            "is_active": is_active,
            "created_at": created_at or datetime.now(),
            **kwargs
        }
    
    @staticmethod
    def create_admin(username: str = "admin_user", **kwargs) -> Dict[str, Any]:
        """Create an admin user."""
        return UserFactory.create(
            username=username,
            role="admin",
            company_id=None,  # Admins typically don't have company assignment
            **kwargs
        )
    
    @staticmethod
    def create_standard(username: str = "standard_user", company_id: int = 1, **kwargs) -> Dict[str, Any]:
        """Create a standard user."""
        return UserFactory.create(
            username=username,
            role="standard",
            company_id=company_id,
            **kwargs
        )
    
    @staticmethod
    def create_bookkeeping(username: str = "bookkeeping_user", company_id: int = 1, **kwargs) -> Dict[str, Any]:
        """Create a bookkeeping user."""
        return UserFactory.create(
            username=username,
            role="bookkeeping",
            company_id=company_id,
            **kwargs
        )
    
    @staticmethod
    def create_inactive(username: str = "inactive_user", **kwargs) -> Dict[str, Any]:
        """Create an inactive user."""
        return UserFactory.create(
            username=username,
            is_active=False,
            **kwargs
        )
    
    @staticmethod
    def create_multiple(count: int, **base_kwargs) -> list[Dict[str, Any]]:
        """
        Create multiple users with unique usernames.
        
        Args:
            count: Number of users to create
            **base_kwargs: Base attributes for all users
            
        Returns:
            List of user dictionaries
        """
        users = []
        for i in range(count):
            user_kwargs = base_kwargs.copy()
            base_username = user_kwargs.get('username', 'test_user')
            user_kwargs['username'] = f'{base_username}_{i+1}'
            users.append(UserFactory.create(**user_kwargs))
        return users


class CompanyFactory:
    """Factory for creating test company data."""
    
    @staticmethod
    def create(
        id: Optional[int] = None,
        name: str = "Test Company",
        created_at: Optional[datetime] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a test company.
        
        Args:
            id: Company ID
            name: Company name
            created_at: Creation timestamp
            **kwargs: Additional fields
            
        Returns:
            Dictionary with company data
        """
        return {
            "id": id or 1,
            "name": name,
            "created_at": created_at or datetime.now(),
            **kwargs
        }
    
    @staticmethod
    def create_multiple(count: int) -> list[Dict[str, Any]]:
        """
        Create multiple companies.
        
        Args:
            count: Number of companies to create
            
        Returns:
            List of company dictionaries
        """
        return [
            CompanyFactory.create(
                id=i + 1,
                name=f"Test Company {chr(65 + i)}"  # A, B, C, etc.
            )
            for i in range(count)
        ]


class UserAuditLogFactory:
    """Factory for creating test user audit log data."""
    
    @staticmethod
    def create(
        id: Optional[int] = None,
        user_id: Optional[UUID] = None,
        action: str = "created",
        changed_by: Optional[UUID] = None,
        old_values: Optional[Dict] = None,
        new_values: Optional[Dict] = None,
        ip_address: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a test user audit log entry.
        
        Args:
            id: Log entry ID
            user_id: User UUID being audited
            action: Action performed (created, updated, deleted, etc.)
            changed_by: UUID of user who made the change
            old_values: Old values before change
            new_values: New values after change
            ip_address: IP address of request
            timestamp: Timestamp of action
            **kwargs: Additional fields
            
        Returns:
            Dictionary with audit log data
        """
        return {
            "id": id or 1,
            "user_id": user_id or uuid4(),
            "action": action,
            "changed_by": changed_by or uuid4(),
            "old_values": old_values or {},
            "new_values": new_values or {},
            "ip_address": ip_address or "127.0.0.1",
            "timestamp": timestamp or datetime.now(),
            **kwargs
        }


# Preset scenarios for common test cases
class UserScenarios:
    """Predefined user scenarios for testing."""
    
    @staticmethod
    def multi_role_users_with_companies() -> Dict[str, Any]:
        """
        Create a complete scenario with multiple roles and companies.
        
        Returns:
            Dictionary with users and companies
        """
        companies = CompanyFactory.create_multiple(2)
        
        return {
            "companies": companies,
            "admin": UserFactory.create_admin(username="admin_test"),
            "standard_user_1": UserFactory.create_standard(
                username="user1_test",
                company_id=companies[0]["id"]
            ),
            "standard_user_2": UserFactory.create_standard(
                username="user2_test",
                company_id=companies[1]["id"]
            ),
            "bookkeeping_user": UserFactory.create_bookkeeping(
                username="bookkeeper_test",
                company_id=companies[0]["id"]
            ),
            "inactive_user": UserFactory.create_inactive(
                username="inactive_test",
                company_id=companies[0]["id"]
            ),
        }
    
    @staticmethod
    def authentication_test_users() -> Dict[str, Any]:
        """
        Create users for authentication testing.
        
        Returns:
            Dictionary with users for different auth scenarios
        """
        return {
            "valid_user": UserFactory.create(
                username="valid_user",
                password="$2b$12$valid_hashed_password",
                is_active=True
            ),
            "inactive_user": UserFactory.create(
                username="inactive_user",
                password="$2b$12$valid_hashed_password",
                is_active=False
            ),
            "wrong_password_user": UserFactory.create(
                username="wrong_pass_user",
                password="$2b$12$correct_hashed_password",
                is_active=True
            ),
        }
    
    @staticmethod
    def rbac_test_users() -> Dict[str, Any]:
        """
        Create users for RBAC (Role-Based Access Control) testing.
        
        Returns:
            Dictionary with users for different role scenarios
        """
        company_a = CompanyFactory.create(id=1, name="Company A")
        company_b = CompanyFactory.create(id=2, name="Company B")
        
        return {
            "companies": [company_a, company_b],
            "admin_full_access": UserFactory.create_admin(username="admin_full"),
            "standard_company_a": UserFactory.create_standard(
                username="standard_a",
                company_id=company_a["id"]
            ),
            "standard_company_b": UserFactory.create_standard(
                username="standard_b",
                company_id=company_b["id"]
            ),
            "bookkeeping_limited": UserFactory.create_bookkeeping(
                username="bookkeeping_limited",
                company_id=company_a["id"]
            ),
        }

