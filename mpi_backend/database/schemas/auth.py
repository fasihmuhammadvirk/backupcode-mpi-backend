from typing import Optional
from pydantic import BaseModel, Field


class SignInCredentials(BaseModel):
    """
    Credentials for signing in.

    Attributes:
        username: User's username
        password: User's password
        remember_me: If True, token expires in 7 days; if False, expires in 8 hours (default: False)
    """
    username: str
    password: str
    remember_me: Optional[bool] = False
