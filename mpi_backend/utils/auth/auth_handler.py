import logging
import time
from typing import Optional
from uuid import uuid4

import jwt
from pydantic import ValidationError

from mpi_backend.config import (
    SECRET_KEY,
    ACCESS_TOKEN_REMEMBER_ME_DAYS,
    ACCESS_TOKEN_SESSION_HOURS,
)
from mpi_backend.utils.auth.roles import UserRole
from mpi_backend.utils.auth.models import JWTPayload, TokenResponse

logger = logging.getLogger(__name__)

JWT_SECRET = SECRET_KEY
JWT_ALGORITHM = 'HS256'

# Token expiration settings (in seconds)
TOKEN_EXPIRE_REMEMBER_ME = ACCESS_TOKEN_REMEMBER_ME_DAYS * 24 * 60 * 60  # 7 days = 604,800 seconds
TOKEN_EXPIRE_SESSION = ACCESS_TOKEN_SESSION_HOURS * 60 * 60  # 8 hours = 28,800 seconds


def token_response(token: str) -> TokenResponse:
    """Create a standard token response."""
    return TokenResponse(access_token=token)


def signJWT(user_id: str, role: UserRole, company_id: Optional[int] = None, remember_me: bool = False) -> TokenResponse:
    """
    Generate JWT with standard claims and user info.

    Args:
        user_id: User identifier (as string for flexibility)
        role: User role enum
        company_id: Optional company ID (None for admin users)
        remember_me: If True, token expires in 7 days; if False, expires in 8 hours (default: False)

    Returns:
        TokenResponse containing the access token

    Note: Uses role.value to store string in JWT for compatibility.
    TODO: Move to refresh token pattern (Issue #XXX)
    """
    # Calculate expiration based on remember_me flag
    expiration_seconds = TOKEN_EXPIRE_REMEMBER_ME if remember_me else TOKEN_EXPIRE_SESSION

    payload = {
        "sub": str(user_id),  # Standard claim for user ID
        "role": role.value,  # Store enum value (string) in JWT
        "company_id": company_id,
        "iat": int(time.time()),  # Issued at
        "exp": int(time.time()) + expiration_seconds,  # Expiration (7 days or 8 hours)
        "jti": str(uuid4())  # Token ID for future revocation
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    return token_response(token)


def decodeJWT(token: str) -> Optional[JWTPayload]:
    """
    Decode and validate JWT token.

    Args:
        token: JWT token string to decode

    Returns:
        JWTPayload if valid, None if invalid/expired

    Note: jwt.decode automatically validates expiration (exp claim),
    so no manual expiry check is needed.
    """
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        # Parse into typed model for type safety
        return JWTPayload(**decoded)
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except ValidationError:
        # Invalid JWT structure (missing required fields)
        return None
    except Exception:
        return None
