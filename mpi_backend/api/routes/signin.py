from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging

from mpi_backend.database import get_db
from mpi_backend.database.controllers.UserController import UserController
from mpi_backend.utils.auth.auth_handler import signJWT

router = APIRouter(prefix="/signin", tags=["Authentication"])
logger = logging.getLogger(__name__)


@router.post("")
def signin(user_credentials: dict, db: Session = Depends(get_db)):
    logger.info("POST /signin - User signin attempt")
    try:
        user_controller = UserController(db)
        user = user_controller.get_user_by_email(user_credentials["email"])
        
        if user and user_controller.verify_password(user_credentials["password"], user.password):
            token = signJWT(user.email)
            logger.info(f"POST /signin - Successful signin for user: {user.email}")
            return {"access_token": token}
        else:
            logger.warning(f"POST /signin - Failed signin attempt for email: {user_credentials.get('email', 'unknown')}")
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception as e:
        logger.error(f"POST /signin - Error during signin: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Signin failed: {e}")
