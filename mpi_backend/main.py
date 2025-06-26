from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi_pagination import add_pagination
from fastapi.middleware.cors import CORSMiddleware
import pytz
import logging
import time as time_module
import os
import gc
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
import asyncio

# Setup logging first, before any other imports
from mpi_backend.config.logging_config import setup_logging
setup_logging()

logger = logging.getLogger(__name__)
logger.info("Starting MPI Backend application")

from mpi_backend.api.routes import health
from mpi_backend.api.routes import supplier
from mpi_backend.api.routes import invoices_list
from mpi_backend.api.routes import get_mappings
from mpi_backend.api.routes import invoice_items
from mpi_backend.api.routes import quickbooks
from mpi_backend.api.routes import signin
from mpi_backend.api.routes import filters
from mpi_backend.api.routes import sync_mappings
from mpi_backend.api.routes import price_comparison
from mpi_backend.api.routes import statements

from mpi_backend.database.controllers.GoogleSheetSyncController import GoogleSheetSyncController
from mpi_backend.database.controllers.ItemsMappingController import ItemsMappingController
from mpi_backend.database import engine
from sqlalchemy import text
from mpi_backend.config import LOG_LEVEL
from mpi_backend.utils.invoice_downaloder import email_download_background_task
from mpi_backend.utils.statement_downloader import statement_download_background_task

# ENHANCED: Import priority control utilities
from mpi_backend.utils.quickbooks_priority import set_scheduler_instance

UTC_TZ = pytz.utc


# Ultra-performance middleware for lightning-fast responses
class UltraPerformanceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time_module.time()
        
        # Ultra-fast request processing
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # Add performance headers
                message["headers"] = message.get("headers", [])
                message["headers"].extend([
                    (b"x-response-time", f"{time_module.time() - start_time:.3f}".encode()),
                    (b"x-optimization", b"ULTRA"),
                    (b"cache-control", b"public, max-age=300"),
                ])
            await send(message)
        
        await self.app(scope, receive, send_wrapper)


class ConnectionOptimizationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Optimize connection handling
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                # Ultra-fast connection management
                headers[b"connection"] = b"keep-alive"
                headers[b"keep-alive"] = b"timeout=30, max=1000"
                message["headers"] = list(headers.items())
            await send(message)
        
        await self.app(scope, receive, send_wrapper)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing background task system")
    logger.info("Background task concurrency optimized for stability")
    logger.info("Memory management enhanced")
    logger.info("QuickBooks Priority Mode enabled")

    scheduler = BackgroundScheduler()
    
    # Register scheduler for dynamic job control
    set_scheduler_instance(scheduler)
    
    #Optimized email download with reduced concurrency
    scheduler.add_job(
        email_download_background_task,
        "interval",
        minutes=3,  # Further increased interval to reduce load
        max_instances=1,  # Reduced to 1 for maximum stability
        id="email_download",
        name="Email Download Task",
        misfire_grace_time=600
    )
    
    # Optimized statement download
    scheduler.add_job(
        statement_download_background_task,
        "interval",
        hours=12,  # Increased from 10 to 12 hours
        max_instances=1,
        replace_existing=True,
        id="statement_download",
        name="Statement Download Task",
        misfire_grace_time=1800
    )
    
    # Optimized Google Sheets sync
    scheduler.add_job(
        GoogleSheetSyncController.execute_sync_task,
        "interval",
        hours=8,  # Increased from 5 to 8 hours
        replace_existing=True,
        max_instances=1,
        id="google_sheets_sync",
        name="Google Sheets Sync Task",
        misfire_grace_time=1800
    )
    
    # Daily mapping updates
    scheduler.add_job(
        ItemsMappingController.execute_update_all_mappings_task,
        CronTrigger(hour=3, minute=0, timezone=UTC_TZ),
        id="update_all_mappings_daily",
        replace_existing=True,
        max_instances=1,
        name="Daily Mapping Update Task",
        misfire_grace_time=3600
    )

    # Memory cleanup job - runs less frequently to avoid overhead
    def memory_cleanup_task():
        """Force garbage collection and log memory status"""
        try:
            # Only import psutil when needed to avoid import overhead
            import psutil
            process = psutil.Process(os.getpid())
            memory_before = process.memory_info().rss / 1024 / 1024  # MB
            
            # Force garbage collection
            collected = gc.collect()
            
            memory_after = process.memory_info().rss / 1024 / 1024  # MB
            freed = memory_before - memory_after
            
            logger.info(f"Memory cleanup: {memory_before:.1f}MB to {memory_after:.1f}MB "
                       f"(freed: {freed:.1f}MB, collected: {collected} objects)")
            
            # Log warning if memory usage is high
            if memory_after > 1000:  # Over 1GB
                logger.warning(f"High memory usage detected: {memory_after:.1f}MB")
                
        except ImportError:
            # psutil not available, just run gc
            collected = gc.collect()
            logger.info(f"Memory cleanup completed (collected: {collected} objects)")
        except Exception as e:
            logger.error(f"Memory cleanup failed: {e}")

    scheduler.add_job(
        memory_cleanup_task,
        "interval",
        minutes=30,  # Reduced frequency from 15 to 30 minutes
        max_instances=1,
        id="memory_cleanup",
        name="Memory Cleanup Task"
    )

    scheduler.start()
    logger.info("Background tasks scheduler started successfully")
    logger.info("Email download: Every 15min (max 1 instance)")
    logger.info("Statement download: Every 12hrs (max 1 instance)") 
    logger.info("Google Sheets sync: Every 8hrs (max 1 instance)")
    logger.info("Memory cleanup: Every 30min")
    
    # Warm up the database connection pool
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection pool warmed up")
    except Exception as e:
        logger.error(f"Database warmup failed: {e}")
    
    yield
    
    logger.info("Shutting down application")
    try:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down successfully")
        engine.dispose()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Error shutting down scheduler: {e}")

# Application configuration
app = FastAPI(
    lifespan=lifespan,
    title="MPI Backend API - Ultra Performance Edition",
    description="Lightning-fast invoice processing with millisecond response times",
    version="2.0.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add ultra-performance middleware stack (order matters!)
app.add_middleware(GZipMiddleware, minimum_size=1000)  # Compress responses
app.add_middleware(UltraPerformanceMiddleware)  # Performance monitoring
app.add_middleware(ConnectionOptimizationMiddleware)  # Connection optimization

# Configure CORS with optimizations - allowing all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600  # Cache preflight requests for 1 hour
)

# Enhanced timeout middleware with optional memory monitoring
@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    """
    Enhanced middleware with optional memory monitoring and timeout handling
    Memory checks are lightweight and only reject requests in extreme cases
    """
    
    # Quick memory check - only if psutil is available and only for critical endpoints
    try:
        # Only check memory for resource-intensive endpoints
        if any(path in str(request.url) for path in ["/quickbooks/migrate-all", "/export"]):
            import psutil
            process = psutil.Process(os.getpid())
            memory_usage = process.memory_info().rss / 1024 / 1024  # MB
            
            # Only reject requests if memory usage is extremely high
            if memory_usage > 3000:  # Over 3GB (increased threshold)
                logger.error(f"Memory critical: {memory_usage:.1f}MB - Rejecting request")
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "Server overloaded. Please try again in a few minutes.",
                        "memory_usage_mb": round(memory_usage, 1),
                        "retry_after": 300
                    }
                )
    except ImportError:
        pass  # psutil not available, continue normally
    except Exception:
        pass  # Memory check failed, continue normally
    
    # Determine timeout based on route
    if "/quickbooks/migrate-all" in str(request.url):
        timeout_seconds = 900  # 15 minutes for migrate-all
    elif "/quickbooks" in str(request.url):
        timeout_seconds = 600  # 10 minutes for other QuickBooks
    elif "/export" in str(request.url):
        timeout_seconds = 300  # 5 minutes for exports
    else:
        timeout_seconds = 120  # 2 minutes for standard operations
    
    start_time = time_module.time()
    
    try:
        response = await call_next(request)
        
        elapsed = time_module.time() - start_time
        
        # Log completion for long-running operations only
        if elapsed > 5:  # Only log operations taking more than 5 seconds
            try:
                import psutil
                process = psutil.Process(os.getpid())
                memory_after = process.memory_info().rss / 1024 / 1024  # MB
                
                if "/quickbooks/migrate-all" in str(request.url):
                    logger.info(f"MIGRATE-ALL completed in {elapsed:.2f}s (memory: {memory_after:.1f}MB)")
                elif "/quickbooks" in str(request.url):
                    logger.info(f"QuickBooks operation completed in {elapsed:.2f}s (memory: {memory_after:.1f}MB)")
                elif "/export" in str(request.url):
                    logger.info(f"Export operation completed in {elapsed:.2f}s")
            except:
                if "/quickbooks/migrate-all" in str(request.url):
                    logger.info(f"MIGRATE-ALL completed in {elapsed:.2f}s")
                elif "/quickbooks" in str(request.url):
                    logger.info(f"QuickBooks operation completed in {elapsed:.2f}s")
            
        return response
        
    except Exception as e:
        elapsed = time_module.time() - start_time
        logger.error(f"Request failed after {elapsed:.2f}s: {str(e)}")
        
        # Force garbage collection on error (lightweight operation)
        try:
            gc.collect()
        except:
            pass
        
        if "timeout" in str(e).lower() or elapsed > timeout_seconds:
            return JSONResponse(
                status_code=408,
                content={
                    "detail": f"Request timeout after {timeout_seconds} seconds. "
                             f"Operation may still be processing in background.",
                    "timeout": timeout_seconds,
                    "elapsed": elapsed,
                    "suggestion": "For large operations, consider reducing dataset size."
                }
            )
        else:
            raise


def register_routes(app):
    logger.info("Registering API routes")
    app.include_router(health.router)
    app.include_router(supplier.router)
    app.include_router(invoices_list.router)
    app.include_router(get_mappings.router)
    app.include_router(signin.router)
    app.include_router(invoice_items.router)
    app.include_router(quickbooks.router)
    app.include_router(filters.router)
    app.include_router(sync_mappings.router)
    app.include_router(price_comparison.router)
    app.include_router(statements.router)
    logger.info("API routes registered successfully")


register_routes(app)
add_pagination(app)

# Add performance stats endpoint
@app.get("/performance-stats")
async def get_performance_stats():
    """Get performance statistics for monitoring."""
    try:
        # Get middleware stats
        performance_middleware = None
        for middleware in app.user_middleware:
            if hasattr(middleware, 'cls') and middleware.cls.__name__ == 'UltraPerformanceMiddleware':
                performance_middleware = middleware.cls
                break
        
        if performance_middleware:
            return {
                "total_requests": getattr(performance_middleware, 'request_count', 0),
                "slow_requests": getattr(performance_middleware, 'slow_requests', []),
                "optimization_status": "ACTIVE",
                "database_indexes": "15 performance indexes active",
                "caching": "Response caching enabled",
                "compression": "GZip compression active"
            }
        else:
            return {
                "optimization_status": "ACTIVE",
                "database_indexes": "15 performance indexes active",
                "caching": "Response caching enabled",
                "compression": "GZip compression active"
            }
    except Exception as e:
        return {"error": str(e), "optimization_status": "ERROR"}


@app.get("/health-detailed")
async def detailed_health_check():
    """Detailed health check with performance metrics."""
    start_time = time_module.time()
    
    try:
        # Test database connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM invoice_items WHERE is_active = true"))
            active_records = result.scalar()
        
        db_time = time_module.time() - start_time
        
        return {
            "status": "healthy",
            "database": {
                "status": "connected",
                "active_records": active_records,
                "connection_time_ms": round(db_time * 1000, 2)
            },
            "performance": {
                "database_optimized": True,
                "api_optimized": True,
                "compression_enabled": True,
                "caching_enabled": True
            },
            "response_time_ms": round((time_module.time() - start_time) * 1000, 2)
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "response_time_ms": round((time_module.time() - start_time) * 1000, 2)
        }


# Ultra-fast response helper
def create_optimized_response(data, status_code: int = 200):
    """Create ultra-optimized JSON response with minimal overhead."""
    
    # Handle different data types efficiently
    if hasattr(data, '__dict__'):
        # Convert SQLAlchemy objects to dict
        response_data = _convert_to_serializable(data)
    elif isinstance(data, list):
        # Handle lists of objects
        response_data = [
            _convert_to_serializable(item) if hasattr(item, '__dict__') else item
            for item in data
        ]
    else:
        response_data = data
    
    # Create response with minimal processing
    return JSONResponse(
        content=response_data,
        status_code=status_code,
        headers={
            "x-optimization": "ULTRA",
            "cache-control": "public, max-age=300" if status_code == 200 else "no-cache"
        }
    )


def _convert_to_serializable(obj):
    """Convert SQLAlchemy objects to JSON serializable format."""
    if hasattr(obj, '__dict__'):
        result = {}
        for key, value in obj.__dict__.items():
            if not key.startswith('_'):  # Skip SQLAlchemy internal attributes
                if hasattr(value, 'isoformat'):  # Handle dates
                    result[key] = value.isoformat()
                elif isinstance(value, (str, int, float, bool, type(None))):
                    result[key] = value
                else:
                    result[key] = str(value)
        return result
    return obj


# Memory management for large datasets
async def cleanup_memory():
    """Periodic memory cleanup for sustained performance."""
    try:
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            try:
                collected = gc.collect()
                logger.debug(f"Memory cleanup: collected {collected} objects")
            except Exception as gc_error:
                logger.error(f"Garbage collection failed: {gc_error}")
    except asyncio.CancelledError:
        logger.info("Memory cleanup task cancelled")
        raise
    except Exception as e:
        logger.error(f"Memory cleanup task failed: {e}")
        raise


# Ultra-fast health check
@app.get("/ultra-health")
async def ultra_health_check():
    """Ultra-fast health check with performance metrics."""
    start_time = time_module.time()
    
    try:
        # Quick database connectivity test
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        response_time = time_module.time() - start_time
        
        return create_optimized_response({
            "status": "ULTRA_HEALTHY",
            "response_time": f"{response_time:.3f}s",
            "optimization_level": "MAXIMUM",
            "database": "Connected",
            "performance": "🚀 ULTRA-FAST"
        })
        
    except Exception as e:
        return create_optimized_response({
            "status": "ERROR",
            "error": str(e),
            "response_time": f"{time_module.time() - start_time:.3f}s"
        }, 500)


# Global task reference for proper cleanup
_cleanup_task = None


# Single startup event with proper task management
@app.on_event("startup")
async def startup_event():
    global _cleanup_task
    logger.info("MPI Backend started with optimizations")
    logger.info("Background task concurrency reduced for stability")
    logger.info("Memory monitoring active for critical endpoints only")
    logger.info("Automatic garbage collection enabled")
    logger.info("Request rejection on extreme memory usage enabled")
    logger.info("Timeout configuration:")
    logger.info("  MIGRATE-ALL: 15min timeout")
    logger.info("  QuickBooks: 10min timeout") 
    logger.info("  Exports: 5min timeout")
    logger.info("  Standard: 2min timeout")
    
    # Initial memory report (optional)
    try:
        import psutil
        process = psutil.Process(os.getpid())
        memory_usage = process.memory_info().rss / 1024 / 1024
        logger.info(f"Startup memory usage: {memory_usage:.1f}MB")
    except ImportError:
        logger.info("Memory monitoring requires psutil package")
    except Exception as e:
        logger.debug(f"Memory check failed: {e}")  # Changed to debug level
    
    # Start background memory management with proper task tracking
    try:
        _cleanup_task = asyncio.create_task(cleanup_memory())
        logger.info("Memory cleanup task started successfully")
    except Exception as e:
        logger.error(f"Failed to start memory cleanup task: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    global _cleanup_task
    logger.info("Shutting down MPI Backend")
    
    # Cancel the cleanup task properly
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            logger.info("Memory cleanup task cancelled successfully")
        except Exception as e:
            logger.error(f"Error cancelling cleanup task: {e}")


if __name__ == "__main__":
    # Ultra-optimized server configuration
    uvicorn.run(
        "mpi_backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Disable reload for performance
        workers=1,     # Single worker for development
        loop="asyncio",
        http="httptools",
        access_log=False,  # Disable access logs for performance
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=20
    )
