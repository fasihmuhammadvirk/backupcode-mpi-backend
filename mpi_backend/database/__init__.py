from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy.orm import sessionmaker, declarative_base
from psycopg2 import OperationalError as Psycopg2OperationalError
from contextlib import contextmanager
import logging

from mpi_backend.config import SQLALCHEMY_DATABASE_URI

logger = logging.getLogger(__name__)

# OPTIMIZED: Increased connection pool sizes for multi-user environment
# Main database engine (for regular operations)
engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=10,  # INCREASED from 3 to 10 for multi-user
    max_overflow=8,  # INCREASED from 2 to 8
    pool_pre_ping=True,
    pool_timeout=30,  # INCREASED timeout for better user experience
    pool_recycle=600,  # Keep 10 minutes for better connection mgmt
    echo=False,  # Keep logging disabled for performance
    # ADDED: Connection pool optimization
    pool_use_lifo=True,  # Use LIFO for better connection reuse
    pool_reset_on_return='commit',  # Reset connections on return
)

# OPTIMIZED: Increased QuickBooks pool size for multi-user
# Dedicated high-performance connection pool for QuickBooks exports
qb_engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_size=6,  # INCREASED from 2 to 6 for multi-user
    max_overflow=4,  # INCREASED from 1 to 4
    pool_pre_ping=True,
    pool_timeout=20,  # INCREASED timeout for QB operations
    pool_recycle=600,  # Keep 10 minutes
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
    """Enhanced connection pool monitoring with proactive alerts"""
    try:
        main_pool = engine.pool
        qb_pool = qb_engine.pool
        
        main_checked_out = main_pool.checkedout()
        main_size = main_pool.size()
        main_overflow = main_pool.overflow()
        qb_checked_out = qb_pool.checkedout()
        qb_size = qb_pool.size()
        qb_overflow = qb_pool.overflow()
        
        # Calculate total available connections
        main_total = main_size + main_overflow
        qb_total = qb_size + qb_overflow
        total_available = main_total + qb_total
        
        # Calculate usage percentages
        main_usage = (main_checked_out / main_total) * 100 if main_total > 0 else 0
        qb_usage = (qb_checked_out / qb_total) * 100 if qb_total > 0 else 0
        total_usage = ((main_checked_out + qb_checked_out) / total_available) * 100 if total_available > 0 else 0
        
        logger.info(
            f"DB Pool Status - Main: {main_checked_out}/{main_total} "
            f"({main_usage:.1f}%), QB: {qb_checked_out}/{qb_total} "
            f"({qb_usage:.1f}%), Total: {total_usage:.1f}%"
        )
        
        # Progressive alerts based on usage
        if main_usage > 70:
            logger.warning(f"Main DB pool usage high: {main_usage:.1f}%")
        if qb_usage > 70:
            logger.warning(f"QB DB pool usage high: {qb_usage:.1f}%")
        if total_usage > 70:
            logger.warning(f"Total DB pool usage high: {total_usage:.1f}%")
            
        # Critical alerts when approaching exhaustion
        if main_usage >= 85:
            logger.critical(f"Main DB pool nearly exhausted: {main_usage:.1f}%")
        if qb_usage >= 85:
            logger.critical(f"QB DB pool nearly exhausted: {qb_usage:.1f}%")
        if total_usage >= 85:
            logger.critical(f"CRITICAL: Total DB pool nearly exhausted: {total_usage:.1f}%")
            
        # Emergency alert at 95% usage
        if total_usage >= 95:
            logger.critical(f"EMERGENCY: DB pool exhaustion imminent! {total_usage:.1f}%")
            
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
