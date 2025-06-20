from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy.orm import sessionmaker, declarative_base
from psycopg2 import OperationalError as Psycopg2OperationalError
from contextlib import contextmanager
import logging

from mpi_backend.config import SQLALCHEMY_DATABASE_URI

logger = logging.getLogger(__name__)

# CRITICAL FIX: Reduced connection pool sizes to prevent exhaustion
# Main database engine (for regular operations)
engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=10,  # REDUCED from 20 to 10
    max_overflow=5,  # REDUCED from 10 to 5
    pool_pre_ping=True,
    pool_timeout=10,  # INCREASED timeout for better stability
    pool_recycle=1800,  # ADDED: Recycle connections every 30 minutes
    echo=False,  # Keep logging disabled for performance
)

# CRITICAL FIX: Reduced QuickBooks pool size
# Dedicated high-performance connection pool for QuickBooks exports
qb_engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=8,  # REDUCED from 15 to 8
    max_overflow=3,  # REDUCED from 5 to 3
    pool_pre_ping=True,
    pool_timeout=5,  # Keep faster timeout for QB operations
    pool_recycle=1800,  # REDUCED from 3600 to 1800 (30 minutes)
    echo=False,  # Disable SQL logging for performance
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
QBSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=qb_engine)
Base = declarative_base()

# ENHANCED: Add connection pool monitoring
def log_pool_status():
    """Log database connection pool status"""
    try:
        main_pool = engine.pool
        qb_pool = qb_engine.pool
        
        logger.info(f"DB Pool Status - Main: {main_pool.checkedout()}/{main_pool.size()} checked out, "
                   f"QB: {qb_pool.checkedout()}/{qb_pool.size()} checked out")
        
        # Warn if pools are getting full
        main_usage = (main_pool.checkedout() / main_pool.size()) * 100
        qb_usage = (qb_pool.checkedout() / qb_pool.size()) * 100
        
        if main_usage > 80:
            logger.warning(f"Main DB pool usage high: {main_usage:.1f}%")
        if qb_usage > 80:
            logger.warning(f"QB DB pool usage high: {qb_usage:.1f}%")
            
    except Exception as e:
        logger.debug(f"Could not check pool status: {e}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
            logger.warning(f"Error closing main DB session: {e}")
        except Exception as e:
            logger.error(f"Unexpected error closing main DB session: {e}")


def get_qb_db():
    """Dedicated database session for QuickBooks operations"""
    db = QBSessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
            logger.warning(f"Error closing QB DB session: {e}")
        except Exception as e:
            logger.error(f"Unexpected error closing QB DB session: {e}")


@contextmanager
def db_context():
    """Context manager for database sessions with enhanced error handling"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        try:
            db.rollback()
        except:
            pass
        raise
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
            logger.warning(f"Error closing DB context session: {e}")
        except Exception as e:
            logger.error(f"Unexpected error closing DB context session: {e}")


@contextmanager
def qb_db_context():
    """Context manager for QuickBooks priority database sessions"""
    db = QBSessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"QB Database operation failed: {e}")
        try:
            db.rollback()
        except:
            pass
        raise
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
            logger.warning(f"Error closing QB DB context session: {e}")
        except Exception as e:
            logger.error(f"Unexpected error closing QB DB context session: {e}")

# Log initial pool configuration
logger.info("Database connection pools configured:")
logger.info(f"  Main DB: {engine.pool.size()} connections (max overflow: {engine.pool._max_overflow})")
logger.info(f"  QB DB: {qb_engine.pool.size()} connections (max overflow: {qb_engine.pool._max_overflow})")
logger.info("  Connection recycling: 30 minutes")
logger.info("  Pool monitoring: ENABLED")
