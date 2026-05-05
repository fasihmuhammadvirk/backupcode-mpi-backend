from mpi_backend.database.models.User import User
from mpi_backend.database.models.UserAuditLog import UserAuditLog
from passlib.context import CryptContext
from typing import Optional, List
from uuid import UUID


class UserController:
    def __init__(self, db):
        self.db = db
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash_password(self, password):
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password, hashed_password):
        return self.pwd_context.verify(plain_password, hashed_password)

    def validate_credentials(self, username, password):
        """Validate user credentials (check password and is_active)"""
        try:
            user = self.db.query(User).filter(User.username == username).first()
            if user and user.is_active:
                return self.verify_password(password, user.password)
            return False

        except Exception as e:
            print(f"Error Validating User: {e}")
            return None

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        return self.db.query(User).filter(User.username == username).first()

    def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID"""
        return self.db.query(User).filter(User.id == user_id).first()

    def get_all_users(self, exclude_user_id: Optional[UUID] = None) -> List[User]:
        """
        Get all users, optionally excluding a specific user.

        The user id that we typically would exclude would be the same user that is requesting the data.

        Args:
            exclude_user_id: Optional UUID of user to exclude from results

        Returns:
            List of User objects
        """
        query = self.db.query(User)
        if exclude_user_id:
            query = query.filter(User.id != exclude_user_id)
        return query.all()

    def create_user(self, username: str, password: str, email: Optional[str] = None,
                   role: str = "standard", company_id: Optional[int] = None,
                   created_by: Optional[UUID] = None, ip_address: Optional[str] = None):
        """
        Create a new user with audit logging.

        Args:
            username: Username
            password: Plain text password (will be hashed)
            email: Optional email
            role: User role (admin, bookkeeping, standard)
            company_id: Optional company assignment
            created_by: UUID of admin creating the user (for audit)
            ip_address: IP address of request (for audit)

        Returns:
            User object if successful, None if failed
        """
        try:
            hashed_password = self.hash_password(password)
            new_user = User(
                username=username,
                password=hashed_password,
                email=email,
                role=role,
                company_id=company_id,
                is_active=True
            )
            self.db.add(new_user)
            self.db.flush()  # Get user ID before commit

            # Audit log
            if created_by:
                audit = UserAuditLog(
                    user_id=new_user.id,
                    action="created",
                    changed_by=created_by,
                    new_values={
                        "username": username,
                        "role": role,
                        "company_id": company_id,
                        "email": email
                    },
                    ip_address=ip_address
                )
                self.db.add(audit)

            self.db.commit()
            return new_user
        except Exception as e:
            print(f"Error Creating User: {e}")
            self.db.rollback()
            return None

    def update_user(self, user_id: UUID, changed_by: UUID, ip_address: Optional[str] = None,
                   email: Optional[str] = None, role: Optional[str] = None,
                   company_id: Optional[int] = None, is_active: Optional[bool] = None):
        """
        Update user with audit logging.

        Args:
            user_id: UUID of user to update
            changed_by: UUID of admin making the change
            ip_address: IP address of request
            email: New email (optional)
            role: New role (optional)
            company_id: New company (optional)
            is_active: New active status (optional)

        Returns:
            Updated User object if successful, None if failed
        """
        try:
            user = self.db.query(User).filter(User.id == user_id).first()
            if not user:
                return None

            # Track changes for audit
            old_values = {}
            new_values = {}

            if email is not None and email != user.email:
                old_values["email"] = user.email
                new_values["email"] = email
                user.email = email

            if role is not None and role != user.role:
                old_values["role"] = user.role
                new_values["role"] = role
                user.role = role

            if company_id is not None and company_id != user.company_id:
                old_values["company_id"] = user.company_id
                new_values["company_id"] = company_id
                user.company_id = company_id

            if is_active is not None and is_active != user.is_active:
                old_values["is_active"] = user.is_active
                new_values["is_active"] = is_active
                user.is_active = is_active

            # Only create audit log if there were actual changes
            if old_values or new_values:
                audit = UserAuditLog(
                    user_id=user_id,
                    action="updated",
                    changed_by=changed_by,
                    old_values=old_values if old_values else None,
                    new_values=new_values if new_values else None,
                    ip_address=ip_address
                )
                self.db.add(audit)

            self.db.commit()
            return user
        except Exception as e:
            print(f"Error Updating User: {e}")
            self.db.rollback()
            return None
