"""
Database Connection Optimizer for MPI Backend
Automatically applies query optimizations when database connections are created.
"""

import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from mpi_backend.database.query_optimizer import query_optimizer

logger = logging.getLogger(__name__)

def create_optimized_engine(database_url: str, **kwargs):
    """Create a database engine with automatic optimizations"""
    try:
        # Create engine with optimized connection pool settings
        engine = create_engine(
            database_url,
            pool_size=8,           # Reduced from 10
            max_overflow=3,        # Reduced from 5
            pool_timeout=20,       # Reduced from 30
            pool_recycle=900,      # 15 minutes instead of 30
            pool_pre_ping=True,    # Verify connections before use
            echo=False,            # Disable SQL logging for performance
            **kwargs
        )
        
        # Apply query optimizations
        query_optimizer.optimize_connection_pool(engine)
        
        # Create performance indexes
        query_optimizer.create_performance_indexes(engine)
        
        logger.info("Created optimized database engine with automatic optimizations")
        return engine
        
    except Exception as e:
        logger.error(f"Error creating optimized database engine: {e}")
        # Fallback to standard engine
        return create_engine(database_url, **kwargs)

def create_optimized_session_factory(engine):
    """Create a session factory with automatic optimizations"""
    try:
        # Create session factory
        SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine
        )
        
        # Add event listeners for automatic optimizations
        @event.listens_for(SessionLocal, 'after_begin')
        def receive_after_begin(session, transaction, connection):
            """Apply optimizations when session begins"""
            try:
                # Set session-level optimizations
                session.execute("SET SESSION query_cache_type = ON")
                session.execute("SET SESSION query_cache_size = 1048576")  # 1MB
                logger.debug("Applied session-level optimizations")
            except Exception as e:
                logger.debug(f"Could not apply session optimizations: {e}")
        
        @event.listens_for(SessionLocal, 'after_commit')
        def receive_after_commit(session):
            """Clean up after commit"""
            try:
                # Clear any session-level caches
                session.close()
                logger.debug("Session committed and cleaned up")
            except Exception as e:
                logger.debug(f"Error in session cleanup: {e}")
        
        logger.info("Created optimized session factory with automatic optimizations")
        return SessionLocal
        
    except Exception as e:
        logger.error(f"Error creating optimized session factory: {e}")
        # Fallback to standard session factory
        return sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_optimized_session(engine):
    """Get an optimized database session"""
    try:
        SessionLocal = create_optimized_session_factory(engine)
        return SessionLocal()
    except Exception as e:
        logger.error(f"Error creating optimized session: {e}")
        # Fallback to standard session
        from sqlalchemy.orm import sessionmaker
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return SessionLocal()

# Global optimized engine and session factory
optimized_engine = None
optimized_session_factory = None

def initialize_optimized_database(database_url: str, **kwargs):
    """Initialize the optimized database connection"""
    global optimized_engine, optimized_session_factory
    
    try:
        # Create optimized engine
        optimized_engine = create_optimized_engine(database_url, **kwargs)
        
        # Create optimized session factory
        optimized_session_factory = create_optimized_session_factory(optimized_engine)
        
        logger.info("Optimized database connection initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error initializing optimized database: {e}")
        return False

def get_optimized_database_session():
    """Get an optimized database session"""
    global optimized_session_factory
    
    if optimized_session_factory is None:
        logger.error("Optimized database not initialized")
        return None
    
    try:
        return optimized_session_factory()
    except Exception as e:
        logger.error(f"Error getting optimized database session: {e}")
        return None
