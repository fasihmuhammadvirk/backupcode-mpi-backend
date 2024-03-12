from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy.orm import sessionmaker, declarative_base
from psycopg2 import OperationalError as Psycopg2OperationalError

from mpi_backend.config import SQLALCHEMY_DATABASE_URI

engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_timeout=5,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError):
            pass
