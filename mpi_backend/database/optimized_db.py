"""
Optimized Database Configuration for MPI Backend
Implements connection pooling, query optimization, and resource management.
"""

import logging
import time
from contextlib import contextmanager
from typing import Dict, Any
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
import psutil

from mpi_backend.config.performance_config import (
    get_optimized_db_config,
    get_quickbooks_db_config,
    MAX_DB_CONNECTIONS
)

logger = logging.getLogger(__name__)

class OptimizedDatabaseManager:
    """Manages optimized database connections and monitoring"""
    
    def __init__(self):
        self.main_engine = None
        self.qb_engine = None
        self.main_session_factory = None
        self.qb_session_factory = None
        self.connection_stats = {
            'total_connections': 0,
            'active_connections': 0,
            'failed_connections': 0,
            'slow_queries': 0,
            'last_cleanup': time.time()
        }
        
        self._initialize_engines()
        self._setup_monitoring()
    
    def _initialize_engines(self):
        """Initialize database engines with optimized configuration"""
        try:
            # Import database URI
            from mpi_backend.config import SQLALCHEMY_DATABASE_URI
            
            # Main database engine
            main_config = get_optimized_db_config()
            self.main_engine = create_engine(
                SQLALCHEMY_DATABASE_URI,
                **main_config,
                poolclass=QueuePool,
                pool_use_lifo=True,  # Use LIFO for better connection reuse
            )
            
            # QuickBooks dedicated engine
            qb_config = get_quickbooks_db_config()
            self.qb_engine = create_engine(
                SQLALCHEMY_DATABASE_URI,
                **qb_config,
                poolclass=QueuePool,
                pool_use_lifo=True,
            )
            
            # Create session factories
            self.main_session_factory = sessionmaker(
                bind=self.main_engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,  # Prevent lazy loading issues
            )
            
            self.qb_session_factory = sessionmaker(
                bind=self.qb_engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )
            
            logger.info("Database engines initialized successfully")
            logger.info(f"Main pool size: {self.main_engine.pool.size()}")
            logger.info(f"QB pool size: {self.qb_engine.pool.size()}")
            
        except Exception as e:
            logger.error(f"Failed to initialize database engines: {e}")
            raise
    
    def _setup_monitoring(self):
        """Setup database monitoring and event listeners"""
        if self.main_engine:
            # Monitor connection checkout
            @event.listens_for(self.main_engine, 'checkout')
            def receive_checkout(dbapi_connection, connection_record, connection_proxy):
                self.connection_stats['active_connections'] += 1
                self.connection_stats['total_connections'] += 1
                
                # Log high connection usage
                if self.connection_stats['active_connections'] > MAX_DB_CONNECTIONS * 0.8:
                    logger.warning(
                        f"High database connection usage: "
                        f"{self.connection_stats['active_connections']}/{MAX_DB_CONNECTIONS}"
                    )
            
            # Monitor connection checkin
            @event.listens_for(self.main_engine, 'checkin')
            def receive_checkin(dbapi_connection, connection_record):
                self.connection_stats['active_connections'] = max(
                    0, self.connection_stats['active_connections'] - 1
                )
            
            # Monitor connection failures
            @event.listens_for(self.main_engine, 'connect')
            def receive_connect(dbapi_connection, connection_record):
                pass  # Connection established successfully
            
            # Monitor query execution time
            @event.listens_for(self.main_engine, 'before_cursor_execute')
            def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
                conn.info.setdefault('query_start_time', []).append(time.time())
            
            @event.listens_for(self.main_engine, 'after_cursor_execute')
            def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
                if not conn.info.get('query_start_time'):
                    return
                
                start_time = conn.info['query_start_time'].pop()
                execution_time = time.time() - start_time
                
                # Log slow queries
                if execution_time > 1.0:  # Log queries slower than 1 second
                    self.connection_stats['slow_queries'] += 1
                    logger.warning(
                        f"Slow query detected ({execution_time:.2f}s): {statement[:100]}..."
                    )
    
    def get_main_session(self) -> Session:
        """Get a session from the main database pool"""
        try:
            session = self.main_session_factory()
            return session
        except Exception as e:
            self.connection_stats['failed_connections'] += 1
            logger.error(f"Failed to create main database session: {e}")
            raise
    
    def get_qb_session(self) -> Session:
        """Get a session from the QuickBooks database pool"""
        try:
            session = self.qb_session_factory()
            return session
        except Exception as e:
            self.connection_stats['failed_connections'] += 1
            logger.error(f"Failed to create QB database session: {e}")
            raise
    
    @contextmanager
    def get_main_db(self):
        """Context manager for main database sessions"""
        session = None
        try:
            session = self.get_main_session()
            yield session
        except Exception as e:
            if session:
                session.rollback()
            logger.error(f"Database operation failed: {e}")
            raise
        finally:
            if session:
                try:
                    session.close()
                except Exception as e:
                    logger.warning(f"Error closing main DB session: {e}")
    
    @contextmanager
    def get_qb_db(self):
        """Context manager for QuickBooks database sessions"""
        session = None
        try:
            session = self.get_qb_session()
            yield session
        except Exception as e:
            if session:
                session.rollback()
            logger.error(f"QB database operation failed: {e}")
            raise
        finally:
            if session:
                try:
                    session.close()
                except Exception as e:
                    logger.warning(f"Error closing QB DB session: {e}")
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get current database connection statistics"""
        if not self.main_engine:
            return self.connection_stats
        
        try:
            pool = self.main_engine.pool
            self.connection_stats.update({
                'pool_size': pool.size(),
                'checked_out': pool.checkedout(),
                'overflow': pool.overflow(),
                'checked_in': pool.checkedin(),
                'invalid': pool.invalid(),
                'available': pool.size() - pool.checkedout(),
            })
        except Exception as e:
            logger.debug(f"Could not get pool stats: {e}")
        
        return self.connection_stats
    
    def cleanup_connections(self):
        """Clean up database connections and perform maintenance"""
        try:
            current_time = time.time()
            
            # Cleanup every 5 minutes
            if current_time - self.connection_stats['last_cleanup'] < 300:
                return
            
            # Reset slow query counter
            self.connection_stats['slow_queries'] = 0
            self.connection_stats['last_cleanup'] = current_time
            
            # Log current stats
            stats = self.get_connection_stats()
            logger.info(
                f"DB Stats - Pool: {stats['pool_size']}, "
                f"Active: {stats['checked_out']}, "
                f"Available: {stats['available']}"
            )
            
            # Force garbage collection if memory usage is high
            memory = psutil.virtual_memory()
            if memory.percent > 80:
                import gc
                gc.collect()
                logger.info("Forced garbage collection due to high memory usage")
                
        except Exception as e:
            logger.error(f"Error during connection cleanup: {e}")
    
    def health_check(self) -> Dict[str, Any]:
        """Perform database health check"""
        health_status = {
            'status': 'healthy',
            'timestamp': time.time(),
            'connections': self.get_connection_stats(),
            'errors': []
        }
        
        try:
            # Test main database connection
            with self.get_main_db() as db:
                result = db.execute(text("SELECT 1"))
                result.fetchone()
            
            # Test QB database connection
            with self.get_qb_db() as db:
                result = db.execute(text("SELECT 1"))
                result.fetchone()
            
            # Check connection pool health
            stats = self.get_connection_stats()
            if stats['checked_out'] > stats['pool_size'] * 0.9:
                health_status['status'] = 'warning'
                health_status['errors'].append('High connection pool usage')
            
            if stats['failed_connections'] > 10:
                health_status['status'] = 'critical'
                health_status['errors'].append('High connection failure rate')
                
        except Exception as e:
            health_status['status'] = 'unhealthy'
            health_status['errors'].append(f'Database connection failed: {str(e)}')
        
        return health_status
    
    def close_all_connections(self):
        """Close all database connections"""
        try:
            if self.main_engine:
                self.main_engine.dispose()
                logger.info("Main database engine disposed")
            
            if self.qb_engine:
                self.qb_engine.dispose()
                logger.info("QB database engine disposed")
                
        except Exception as e:
            logger.error(f"Error closing database connections: {e}")

# Global database manager instance
db_manager = OptimizedDatabaseManager()

# Convenience functions for backward compatibility
def get_db():
    """Get main database session (for dependency injection)"""
    return db_manager.get_main_db()

def get_qb_db():
    """Get QuickBooks database session (for dependency injection)"""
    return db_manager.get_qb_db()

def get_connection_stats():
    """Get database connection statistics"""
    return db_manager.get_connection_stats()

def health_check():
    """Perform database health check"""
    return db_manager.health_check()

# Cleanup function for application shutdown
def cleanup_database():
    """Cleanup database connections on shutdown"""
    db_manager.close_all_connections()
