
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from mpi_backend.database.controllers.UserController import UserController
from mpi_backend.config import SQLALCHEMY_DATABASE_URI

def create_user():
    """
    Creates a new user in the database.
    """
    # --- Configuration ---
    # Change these values to the desired username and password
    NEW_USERNAME = "testadmin"
    NEW_PASSWORD = "password"
    NEW_ROLE = "admin"
    # -------------------

    engine = create_engine(SQLALCHEMY_DATABASE_URI)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db_session = SessionLocal()

    try:
        user_controller = UserController(db_session)
        
        # Check if user already exists
        from mpi_backend.database.models import User
        existing_user = db_session.query(User).filter(User.username == NEW_USERNAME).first()
        if existing_user:
            print(f"User '{NEW_USERNAME}' already exists.")
            return

        success = user_controller.create_user(NEW_USERNAME, NEW_PASSWORD, role=NEW_ROLE)

        if success:
            print(f"Successfully created user '{NEW_USERNAME}' with password '{NEW_PASSWORD}'")
        else:
            print("Failed to create user.")
    
    finally:
        db_session.close()

if __name__ == "__main__":
    create_user()
