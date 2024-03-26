from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.controllers import UserController
from mpi_backend.utils.auth.auth_handler import signJWT

router = APIRouter(prefix="/signin")


@router.post("")
async def user_login(username, password, db: Session = Depends(get_db)):
    if UserController(db).validate_credentials(username,password):
        return signJWT(username)
    return {
        "error": "Wrong login details!"
    }
