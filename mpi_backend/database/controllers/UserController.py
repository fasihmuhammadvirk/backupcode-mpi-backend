from mpi_backend.database.models.User import User
from passlib.context import CryptContext
from sqlalchemy import select


class UserController:
    def __init__(self, db):
        self.db = db
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash_password(self, password):
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password, hashed_password):
        return self.pwd_context.verify(plain_password, hashed_password)

    async def validate_credentials(self, username, password):
        try:
            result = await self.db.execute(
                select(User).where(User.username == username)
            )
            user = result.scalar_one_or_none()
            if user:
                return self.verify_password(password, user.password)
            return False

        except Exception as e:
            print(f"Error Validating User: {e}")
            return None

    async def create_user(self, username, password):
        try:
            hashed_password = self.hash_password(password)
            new_user = User(username=username, password=hashed_password)
            self.db.add(new_user)
            await self.db.commit()
            return True
        except Exception as e:
            print(f"Error Creating User: {e}")
            await self.db.rollback()
            return False
