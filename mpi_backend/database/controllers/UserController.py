from mpi_backend.database.models.User import User
from passlib.context import CryptContext


class UserController:
    def __init__(self, db):
        self.db = db
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash_password(self, password):
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password, hashed_password):
        return self.pwd_context.verify(plain_password, hashed_password)

    def validate_credentials(self,username,password):
        try:
            user = self.db.query(User).filter(User.username == username).first()
            if user:
                return self.verify_password(password, user.password)
            return False

        except Exception as e:
            print(f"Error Validating User: {e}")
            return None

    def create_user(self,username,password):
        try:
            hashed_password = self.hash_password(password)
            new_user = User(username=username, password=hashed_password)
            self.db.add(new_user)
            self.db.commit()
            return True
        except Exception as e:
            print(f"Error Creating User: {e}")
            self.db.rollback()
            return False
