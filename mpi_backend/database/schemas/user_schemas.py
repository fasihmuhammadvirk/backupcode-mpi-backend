from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID

from mpi_backend.utils.auth.roles import UserRole


class UserBase(BaseModel):
    """Base user schema"""
    username: str
    email: Optional[EmailStr] = None


class CreateUserRequest(UserBase):
    """Schema for creating a new user (admin only)"""
    password: str
    role: UserRole = UserRole.STANDARD
    company_id: Optional[int] = None

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v


class UpdateUserRequest(BaseModel):
    """
    Schema for updating a user (admin only).
    Only allow specific fields to be updated.
    Never allow password_hash or id to be updated this way.
    """
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    company_id: Optional[int] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """
    Safe user data for API responses.
    Never include password or sensitive data.
    """
    id: UUID
    username: str
    email: Optional[str]
    role: UserRole
    company_id: Optional[int]
    is_active: bool
    created_at: Optional[datetime]

    class Config:
        from_attributes = True  # For Pydantic v2 (was orm_mode in v1)
        use_enum_values = True  # Serialize enum as string value


class CompanyResponse(BaseModel):
    """Company data for API responses"""
    id: int
    name: str

    class Config:
        from_attributes = True
