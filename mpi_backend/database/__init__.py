from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy.orm import sessionmaker, declarative_base
from psycopg2 import OperationalError as Psycopg2OperationalError
from contextlib import contextmanager

from mpi_backend.config import SQLALCHEMY_DATABASE_URI

# Main database engine (for regular operations)
engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_timeout=5,
)

# Enterprise QuickBooks Priority Engine
# Dedicated high-performance connection pool for QuickBooks exports
qb_engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=15,  # Dedicated pool for QB operations
    max_overflow=5,
    pool_pre_ping=True,
    pool_timeout=2,  # Faster timeout for priority operations
    pool_recycle=3600,  # Recycle connections every hour
    echo=False,  # Disable SQL logging for performance
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
QBSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=qb_engine)
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


def get_qb_db():
    """Dedicated database session for QuickBooks operations"""
    db = QBSessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError):
            pass


@contextmanager
def db_context():
    """Context manager for database sessions"""
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError):
            pass


@contextmanager
def qb_db_context():
    """Context manager for QuickBooks priority database sessions"""
    db = QBSessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError):
            pass
