"""
Pydantic models for authentication and JWT handling.

These models provide type safety for JWT payloads and token responses.
"""

from pydantic import BaseModel, Field
from typing import Optional


class JWTPayload(BaseModel):
    """
    Typed model for JWT payload structure.

    Fields use strings (not UUIDs) to maintain flexibility for testing
    and to avoid type conversion issues when decoding JWTs.

    Standard JWT claims:
        sub: Subject (user ID)
        iat: Issued at timestamp
        exp: Expiration timestamp
        jti: JWT ID for token revocation tracking

    Custom claims:
        role: User role (admin, bookkeeping, standard)
        company_id: Associated company ID (None for admin users)
    """

    sub: str = Field(..., description="User ID (subject)")
    role: str = Field(..., description="User role")
    company_id: Optional[int] = Field(None, description="Company ID (None for admin)")
    iat: int = Field(..., description="Issued at timestamp")
    exp: int = Field(..., description="Expiration timestamp")
    jti: str = Field(..., description="JWT ID for revocation tracking")

    class Config:
        """Pydantic configuration."""
        json_schema_extra = {
            "example": {
                "sub": "550e8400-e29b-41d4-a716-446655440000",
                "role": "admin",
                "company_id": None,
                "iat": 1625097600,
                "exp": 1625101200,
                "jti": "123e4567-e89b-12d3-a456-426614174000"
            }
        }


class TokenResponse(BaseModel):
    """
    Standard token response model.

    Returns access token in the format expected by clients.
    """

    access_token: str = Field(..., description="JWT access token")

    class Config:
        """Pydantic configuration."""
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
            }
        }
