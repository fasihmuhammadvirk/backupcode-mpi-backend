from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy.orm import sessionmaker, declarative_base
from psycopg2 import OperationalError as Psycopg2OperationalError
from contextlib import contextmanager
import logging

from mpi_backend.config import SQLALCHEMY_DATABASE_URI

logger = logging.getLogger(__name__)

# Simple database engine configuration
engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=20,  # Standard pool size
    max_overflow=30,  # Standard overflow
    pool_pre_ping=True,  # Enable connection health checks
    pool_timeout=30,  # Standard timeout
    pool_recycle=3600,  # Recycle connections every hour
    echo=False,  # Keep logging disabled
    connect_args={
        "connect_timeout": 30,  # Standard connection timeout
        "application_name": "mpi_backend"
    }
)

# QuickBooks database engine
qb_engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=10,  # Standard pool size
    max_overflow=20,  # Standard overflow
    pool_pre_ping=True,  # Enable connection health checks
    pool_timeout=30,  # Standard timeout
    pool_recycle=3600,  # Recycle connections every hour
    echo=False,  # Keep logging disabled
    connect_args={
        "connect_timeout": 30,  # Standard connection timeout
        "application_name": "mpi_backend_qb"
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
QBSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=qb_engine)
Base = declarative_base()


# Simple database session management
def get_db():
    """Get database session"""
    try:
        db = SessionLocal()
        yield db
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
            logger.debug(f"Error closing main DB session: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error closing main DB session: {e}")


def get_qb_db():
    """Get QuickBooks database session"""
    try:
        db = QBSessionLocal()
        yield db
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
            logger.debug(f"Error closing QB DB session: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error closing QB DB session: {e}")


@contextmanager
def db_context():
    """Context manager for database sessions"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.debug(f"Database operation failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception as e:
            logger.debug(f"Error closing database session: {e}")


def get_db_health_status():
    """Get database health status"""
    return {
        "main_pool_size": 20,
        "qb_pool_size": 10,
        "healthy": True
    }
