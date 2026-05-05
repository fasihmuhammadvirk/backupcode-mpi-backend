from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy.orm import sessionmaker, declarative_base
from psycopg2 import OperationalError as Psycopg2OperationalError
from contextlib import contextmanager
import logging

from mpi_backend.config import SQLALCHEMY_DATABASE_URI

logger = logging.getLogger(__name__)

# time before query timeout
# TODO: We set 2min here because there were queries that took almost 2min long.
# We have to improve queries to run under less than this
QUERY_TIMEOUT = "2min" 

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
        "application_name": "mpi_backend",
        "options": f"-c statement_timeout={QUERY_TIMEOUT}",
        # TCP keepalives so PostgreSQL detects dead clients (e.g. container
        # died during redeployment). Without these, orphaned server-side
        # processes run indefinitely, holding locks and consuming connection
        # slots. Detects a dead client within ~2min (60s idle + 4x15s probes).
        "keepalives": 1,
        "keepalives_idle": 60,
        "keepalives_interval": 15,
        "keepalives_count": 4,
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
        "application_name": "mpi_backend_qb",
        "options": f"-c statement_timeout={QUERY_TIMEOUT}",
        # Same keepalive settings as main engine -- see comment above.
        "keepalives": 1,
        "keepalives_idle": 60,
        "keepalives_interval": 15,
        "keepalives_count": 4,
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
QBSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=qb_engine)
Base = declarative_base()


# Simple database session management
def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        # Rollback on any exception to ensure clean session state
        logger.exception(f"Rolling back DB session due to exception: {type(e).__name__}")
        try:
            db.rollback()
        except Exception as rollback_error:
            logger.error(f"Error during rollback: {rollback_error}")
        raise
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
            logger.debug(f"Error closing main DB session: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error closing main DB session: {e}")


def get_qb_db():
    """Get QuickBooks database session with proper exception handling and rollback"""
    db = QBSessionLocal()
    try:
        yield db
    except Exception as e:
        # Rollback on any exception to ensure clean session state
        logger.warning(f"Rolling back QB DB session due to exception: {type(e).__name__}")
        try:
            db.rollback()
        except Exception as rollback_error:
            logger.error(f"Error during QB rollback: {rollback_error}")
        raise
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
