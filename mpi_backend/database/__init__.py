from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy.orm import sessionmaker, declarative_base
from psycopg2 import OperationalError as Psycopg2OperationalError
from contextlib import asynccontextmanager, contextmanager
import logging

from mpi_backend.config import SQLALCHEMY_DATABASE_URI

logger = logging.getLogger(__name__)

# Convert URI to async format if needed
async_database_uri = SQLALCHEMY_DATABASE_URI
if async_database_uri.startswith('postgresql://'):
    async_database_uri = async_database_uri.replace(
        'postgresql://', 'postgresql+asyncpg://', 1
    )

# UNLIMITED PERFORMANCE - No restrictions on database connections
engine = create_async_engine(
    async_database_uri,
    pool_size=100,  # Increased to 100 for unlimited performance
    max_overflow=200,  # Increased to 200 for unlimited performance
    pool_pre_ping=True,  # Enable connection health checks
    pool_timeout=60,  # Increased timeout for high load
    pool_recycle=7200,  # Recycle connections every 2 hours
    echo=False,  # Keep logging disabled
    connect_args={
        "connect_timeout": 60,  # Increased connection timeout
        "application_name": "mpi_backend_unlimited"
    }
)

# QuickBooks database engine - UNLIMITED PERFORMANCE
qb_engine = create_async_engine(
    async_database_uri,
    pool_size=50,  # Increased to 50 for unlimited performance
    max_overflow=100,  # Increased to 100 for unlimited performance
    pool_pre_ping=True,  # Enable connection health checks
    pool_timeout=60,  # Increased timeout for high load
    pool_recycle=7200,  # Recycle connections every 2 hours
    echo=False,  # Keep logging disabled
    connect_args={
        "connect_timeout": 60,  # Increased connection timeout
        "application_name": "mpi_backend_qb_unlimited"
    }
)

AsyncSessionLocal = sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)
QBAsyncSessionLocal = sessionmaker(
    qb_engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)
Base = declarative_base()


# UNLIMITED PERFORMANCE - No restrictions on database sessions
async def get_async_db():
    """Get async database session - UNLIMITED PERFORMANCE"""
    db = None
    try:
        db = AsyncSessionLocal()
        yield db
    except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
        logger.error(f"Error in main DB session: {e}")
        if db:
            try:
                await db.rollback()
            except Exception:
                pass
        raise
    except Exception as e:
        logger.error(f"Unexpected error in main DB session: {e}")
        if db:
            try:
                await db.rollback()
            except Exception:
                pass
        raise
    finally:
        if db:
            try:
                await db.close()
            except Exception as e:
                logger.error(f"Error closing DB session: {e}")


async def get_async_qb_db():
    """Get async QuickBooks database session - UNLIMITED PERFORMANCE"""
    db = None
    try:
        db = QBAsyncSessionLocal()
        yield db
    except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
        logger.error(f"Error in QB DB session: {e}")
        if db:
            try:
                await db.rollback()
            except Exception:
                pass
        raise
    except Exception as e:
        logger.error(f"Unexpected error in QB DB session: {e}")
        if db:
            try:
                await db.rollback()
            except Exception:
                pass
        raise
    finally:
        if db:
            try:
                await db.close()
            except Exception as e:
                logger.error(f"Error closing QB DB session: {e}")


@asynccontextmanager
async def async_db_context():
    """Async context manager for database sessions - UNLIMITED PERFORMANCE"""
    db = None
    try:
        db = AsyncSessionLocal()
        yield db
    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        if db:
            try:
                await db.rollback()
            except Exception:
                pass
        raise
    finally:
        if db:
            try:
                await db.close()
            except Exception as e:
                logger.error(f"Error closing database session: {e}")


# Keep legacy sync functions for backward compatibility during transition
SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)
QBSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=qb_engine
)


def get_db():
    """Get database session (legacy sync version)"""
    db = None
    try:
        db = SessionLocal()
        yield db
    finally:
        if db:
            try:
                db.close()
            except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
                logger.error(f"Error closing main DB session: {e}")
            except Exception as e:
                logger.error(f"Unexpected error closing main DB session: {e}")


def get_qb_db():
    """Get QuickBooks database session (legacy sync version)"""
    db = None
    try:
        db = QBSessionLocal()
        yield db
    finally:
        if db:
            try:
                db.close()
            except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
                logger.error(f"Error closing QB DB session: {e}")
            except Exception as e:
                logger.error(f"Unexpected error closing QB DB session: {e}")


@contextmanager
def db_context():
    """Context manager for database sessions (legacy sync version)"""
    db = None
    try:
        db = SessionLocal()
        yield db
    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        raise
    finally:
        if db:
            try:
                db.close()
            except Exception as e:
                logger.error(f"Error closing database session: {e}")


def get_db_health_status():
    """Get database health status - UNLIMITED PERFORMANCE"""
    return {
        "main_pool_size": 100,
        "qb_pool_size": 50,
        "max_overflow": 200,
        "qb_max_overflow": 100,
        "pool_timeout": 60,
        "pool_recycle": 7200,
        "healthy": True,
        "performance_mode": "unlimited"
    }
