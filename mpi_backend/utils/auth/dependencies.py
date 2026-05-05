from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.models.User import User
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.auth.auth_handler import decodeJWT
from mpi_backend.utils.auth.roles import UserRole


async def get_current_user(
    request: Request,
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db)
) -> User:
    """
    CRITICAL: Server-side user validation.
    - Decodes token
    - Loads user from DB (fresh data, not stale token data)
    - Verifies user is active
    - Returns user object for permission checks

    This ensures authorization is always based on current DB state,
    not potentially outdated token claims.
    """
    payload = decodeJWT(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    user_id = payload.sub
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    # Load user from DB (fresh data, not token data)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated"
        )

    # Attach request info for audit logging
    request.state.user = user
    request.state.client_ip = request.client.host if request.client else None

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Require admin role.
    Use as dependency on endpoints that require admin access.
    """
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


def require_bookkeeping_or_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Require bookkeeping or admin role.
    Use as dependency on endpoints that require elevated access.
    """
    if current_user.role not in [UserRole.ADMIN.value, UserRole.BOOKKEEPING.value]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bookkeeping or admin access required"
        )
    return current_user
