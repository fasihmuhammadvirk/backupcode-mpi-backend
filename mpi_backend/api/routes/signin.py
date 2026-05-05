from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mpi_backend.database.schemas.auth import SignInCredentials
from mpi_backend.database import get_db
from mpi_backend.database.controllers.UserController import UserController
from mpi_backend.utils.auth.auth_handler import signJWT
from mpi_backend.utils.auth.roles import UserRole

router = APIRouter(prefix="/signin", tags=["Authentication"])


@router.post(
    "",
    summary="Sign in to obtain a JWT",
    response_description="A JWT to use for authenticating requests.",
)
async def signin(credentials: SignInCredentials, db: Session = Depends(get_db)):
    """
    Signs in a user and returns a JWT.

    - **username**: The user's username.
    - **password**: The user's password.
    - **remember_me**: Optional. If True, token expires in 7 days; if False, expires in 8 hours (default: False).
    """
    user_controller = UserController(db)
    user = user_controller.get_user_by_username(credentials.username)

    if not user:
        raise HTTPException(status_code=403, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    if not user_controller.validate_credentials(
        credentials.username, credentials.password
    ):
        raise HTTPException(status_code=403, detail="Invalid credentials")

    # Generate JWT with user ID, role, company, and remember_me preference
    # Convert string role from DB to UserRole enum
    return signJWT(str(user.id), UserRole(user.role), user.company_id, credentials.remember_me)

