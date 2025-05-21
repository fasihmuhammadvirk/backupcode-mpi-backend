from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.controllers import UserController
from mpi_backend.utils.auth.auth_handler import signJWT

router = APIRouter(prefix="/signin",tags=["SignIn"])


@router.post("")
async def user_login(credentials: dict, db: Session = Depends(get_db)):
    username = credentials.get("username")
    password = credentials.get("password")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    if UserController(db).validate_credentials(username,password):
        return signJWT(username)
    else:
        raise HTTPException(status_code=403, detail="Wrong login details!")
