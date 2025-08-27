from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy.orm import sessionmaker, declarative_base
from psycopg2 import OperationalError as Psycopg2OperationalError
from contextlib import contextmanager
import logging

from mpi_backend.config import SQLALCHEMY_DATABASE_URI

logger = logging.getLogger(__name__)

# OPTIMIZED: Reduced connection pool sizes for 4GB server
# Main database engine (for regular operations)
engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=3,  # REDUCED from 5 to 3 for 4GB server
    max_overflow=2,  # REDUCED from 3 to 2
    pool_pre_ping=True,
    pool_timeout=15,  # REDUCED timeout for 4GB server
    pool_recycle=600,  # REDUCED to 10 minutes for better connection mgmt
    echo=False,  # Keep logging disabled for performance
    # ADDED: Connection pool optimization
    pool_use_lifo=True,  # Use LIFO for better connection reuse
    pool_reset_on_return='commit',  # Reset connections on return
)

# OPTIMIZED: Reduced QuickBooks pool size for 4GB server
# Dedicated high-performance connection pool for QuickBooks exports
qb_engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=2,  # REDUCED from 3 to 2 for 4GB server
    max_overflow=1,  # REDUCED from 2 to 1
    pool_pre_ping=True,
    pool_timeout=8,  # Reduced timeout for QB operations on 4GB
    pool_recycle=600,  # REDUCED to 10 minutes
    echo=False,  # Disable SQL logging for performance
    # ADDED: Connection pool optimization
    pool_use_lifo=True,
    pool_reset_on_return='commit',
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
QBSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=qb_engine)
Base = declarative_base()


# ENHANCED: Add connection pool monitoring with resource thresholds
def log_pool_status():
    """Log database connection pool status with resource monitoring"""
    try:
        main_pool = engine.pool
        qb_pool = qb_engine.pool
        
        main_checked_out = main_pool.checkedout()
        main_size = main_pool.size()
        qb_checked_out = qb_pool.checkedout()
        qb_size = qb_pool.size()
        
        logger.info(
            f"DB Pool Status - Main: {main_checked_out}/{main_size} "
            f"checked out, QB: {qb_checked_out}/{qb_size} checked out"
        )
        
        # Warn if pools are getting full (80% threshold)
        main_usage = (main_checked_out / main_size) * 100 if main_size > 0 else 0
        qb_usage = (qb_checked_out / qb_size) * 100 if qb_size > 0 else 0
        
        if main_usage > 80:
            logger.warning(f"Main DB pool usage high: {main_usage:.1f}%")
        if qb_usage > 80:
            logger.warning(f"QB DB pool usage high: {qb_usage:.1f}%")
            
        # CRITICAL: Log if pools are exhausted
        if main_usage >= 95:
            logger.critical(f"Main DB pool nearly exhausted: {main_usage:.1f}%")
        if qb_usage >= 95:
            logger.critical(f"QB DB pool nearly exhausted: {qb_usage:.1f}%")
            
    except Exception as e:
        logger.debug(f"Could not check pool status: {e}")


# ADDED: Resource-aware database session management
def get_db():
    """Get database session with resource monitoring"""
    try:
        # Check pool status before creating session
        log_pool_status()
        
        db = SessionLocal()
        yield db
    finally:
        try:
            db.close()
        except (OperationalError, DBAPIError, Psycopg2OperationalError) as e:
            logger.warning(f"Error closing main DB session: {e}")
        except Exception as e:
            logger.error(f"Unexpected error closing main DB session: {e}")


def get_qb_db():
    """Dedicated database session for QuickBooks operations with resource monitoring"""
    try:
        # Check QB pool status before creating session
        log_pool_status()
        
        db = QBSessionLocal()
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
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception as e:
            logger.error(f"Error closing database session: {e}")


# ADDED: Resource monitoring function for system health checks
def get_db_health_status():
    """Get database health status for monitoring"""
    try:
        main_pool = engine.pool
        qb_pool = qb_engine.pool
        
        main_usage = (main_pool.checkedout() / main_pool.size()) * 100 if main_pool.size() > 0 else 0
        qb_usage = (qb_pool.checkedout() / qb_pool.size()) * 100 if qb_pool.size() > 0 else 0
        
        return {
            "main_pool_usage": round(main_usage, 2),
            "qb_pool_usage": round(qb_usage, 2),
            "main_pool_size": main_pool.size(),
            "qb_pool_size": qb_pool.size(),
            "main_checked_out": main_pool.checkedout(),
            "qb_checked_out": qb_pool.checkedout(),
            "healthy": main_usage < 90 and qb_usage < 90
        }
    except Exception as e:
        logger.error(f"Error getting DB health status: {e}")
        return {"healthy": False, "error": str(e)}
