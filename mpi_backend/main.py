from fastapi import FastAPI, Request
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
import uvicorn
from datetime import datetime, time
from concurrent.futures import ThreadPoolExecutor

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

from mpi_backend.database.controllers.EnhancedGoogleSheetSyncController import (
    EnhancedGoogleSheetSyncController
)
from mpi_backend.database.controllers.ItemsMappingController import (
    ItemsMappingController
)
from mpi_backend.database import engine
from sqlalchemy import text
from mpi_backend.config import LOG_LEVEL
from mpi_backend.utils.invoice_downaloder import email_download_background_task
from mpi_backend.utils.statement_downloader import (
    statement_download_background_task
)

# Import priority control utilities
from mpi_backend.utils.quickbooks_priority import set_scheduler_instance

UTC_TZ = pytz.utc
PKT_TZ = pytz.timezone('Asia/Karachi')  # Pakistan Standard Time (UTC+5)

# Mapping control variables
MAPPINGS_ENABLED = os.getenv("ENABLE_MAPPINGS", "true").lower() == "true"
MAPPINGS_EXCLUSION_ENABLED = os.getenv("ENABLE_MAPPINGS_EXCLUSION", "true").lower() == "true"

# Thread pool for non-blocking background tasks (only for mapping tasks)
_task_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mapping_task")

def is_pakistan_business_hours():
    """
    Check if current time is within Pakistan business hours (12 PM - 6 PM PKT).
    
    Returns:
        bool: True if within business hours, False otherwise
    """
    try:
        pkt_now = datetime.now(PKT_TZ)
        current_hour = pkt_now.hour
        # Business hours: 12 PM (noon) to 6 PM PKT
        return 12 <= current_hour < 18
    except Exception as e:
        logger.error(f"Error checking business hours: {e}")
        return False


def safe_mapping_wrapper(operation_name, operation_func, *args, **kwargs):
    """
    NEW: Enhanced mapping wrapper with proper priority controls and business hours awareness
    
    Args:
        operation_name (str): Name of the operation for logging
        operation_func (callable): Function to execute
        *args, **kwargs: Arguments to pass to the function
        
    Returns:
        Result of the operation or None if skipped/failed
    """
    try:
        # ABSOLUTE PRIORITY: Check if migrate-all operation is active
        try:
            from mpi_backend.utils.quickbooks_priority import is_migrate_all_active
            if is_migrate_all_active():
                logger.info(f"{operation_name} paused - MIGRATE-ALL has absolute priority")
                return None
        except ImportError:
            # If function not available, continue normally
            pass
        
        # Check if mappings are globally disabled
        if not MAPPINGS_ENABLED:
            logger.info(f"{operation_name} skipped - mappings globally disabled")
            return None
        
        # NEW: Business hours exclusion for mapping operations
        if MAPPINGS_EXCLUSION_ENABLED and is_pakistan_business_hours():
            logger.info(f"{operation_name} skipped - within Pakistan business hours (12 PM - 6 PM PKT)")
            return None
        
        # FALLBACK: Check if any QuickBooks export is active
        try:
            from mpi_backend.utils.quickbooks_priority import is_qb_export_active
            if is_qb_export_active():
                logger.info(f"{operation_name} paused - QuickBooks priority export in progress")
                return None
        except ImportError:
            # If function not available, continue normally
            pass
        
        # Execute the operation
        logger.info(f"Starting {operation_name}")
        result = operation_func(*args, **kwargs)
        logger.info(f"Completed {operation_name} successfully")
        return result
        
    except Exception as e:
        logger.error(f"Error in {operation_name}: {str(e)}")
        return None


def async_sequential_mapping_task():
    """
    Execute mapping tasks sequentially: First update all mappings, then UIDI.
    Both operations automatically include Google Sheets sync as the first step.
    Runs in background thread to avoid blocking the server.
    """
    def _execute_sequential():
        try:
            logger.info("Starting sequential mapping tasks execution at 12 AM PKT")
            
            # Step 1: Update All Mappings (includes Google Sheets sync automatically)
            logger.info("Step 1/2: Starting update all mappings (with Google Sheets sync)")
            from mpi_backend.database import SessionLocal
            with SessionLocal() as temp_db:
                step1_result = safe_mapping_wrapper(
                    "Google Sheets Sync + Update All Mappings",
                    EnhancedGoogleSheetSyncController.execute_sync_task,
                    temp_db, "update_all"
                )
            
            if step1_result is None:
                logger.warning("Step 1 failed or was skipped, aborting Step 2")
                return
                
            logger.info("Step 1 completed successfully")
            
            # Step 2: UIDI Update (includes Google Sheets sync automatically)
            logger.info("Step 2/2: Starting UIDI update (with Google Sheets sync)")
            with SessionLocal() as temp_db:
                step2_result = safe_mapping_wrapper(
                    "Google Sheets Sync + UIDI Update",
                    EnhancedGoogleSheetSyncController.execute_sync_task,
                    temp_db, "update_no_match_uidi"
                )
                
            if step2_result is None:
                logger.warning("Step 2 failed or was skipped")
            else:
                logger.info("Step 2 completed successfully")
                
            logger.info("Sequential mapping tasks execution completed")
            
        except Exception as e:
            logger.error(f"Sequential mapping task failed: {str(e)}")
    
    # Submit to thread pool for non-blocking execution
    future = _task_executor.submit(_execute_sequential)
    logger.info("Sequential mapping task submitted to background thread pool")
    return future


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing background task system")
    logger.info("MPI Backend starting up")
    logger.info("Timeout configuration active")
    logger.info("Background tasks initializing")
    
    # Log mapping configuration
    logger.info(f"Mappings enabled: {MAPPINGS_ENABLED}")
    logger.info(
        f"Mapping exclusion during business hours: {MAPPINGS_EXCLUSION_ENABLED}"
    )
    
    scheduler = BackgroundScheduler()
    
    # Register scheduler for dynamic job control
    set_scheduler_instance(scheduler)
    
    # Email download - every 5 minutes (REVERTED: use original function)
    scheduler.add_job(
        email_download_background_task,  # FIXED: Back to original working function
        "interval",
        minutes=5,
        max_instances=1,
        id="email_download",
        name="Email Download Task",
        misfire_grace_time=600
    )
    
    # Statement download - every 12 hours (keep original)
    scheduler.add_job(
        statement_download_background_task,
        "interval",
        hours=12,
        max_instances=1,
        replace_existing=True,
        id="statement_download",
        name="Statement Download Task",
        misfire_grace_time=1800
    )
    
    # DAILY MAPPING TASKS: Run once daily at 12 AM PKT (7 PM UTC, PKT = UTC+5)
    # Sequential execution: All mappings first (with Google Sheets sync), then UIDI (with Google Sheets sync)
    # Note: Google Sheets sync is automatically included in both operations
    scheduler.add_job(
        async_sequential_mapping_task,
        CronTrigger(hour=19, minute=0, timezone=UTC_TZ),  # 12 AM PKT = 7 PM UTC
        id="daily_mapping_tasks",
        replace_existing=True,
        max_instances=1,
        name="Daily Mapping Tasks (12 AM PKT)",
        misfire_grace_time=3600  # 1 hour grace period
    )

    # Memory cleanup - every 30 minutes
    def memory_cleanup_task():
        try:
            collected = gc.collect()
            logger.info(f"Memory cleanup completed - collected {collected} objects")
        except Exception as e:
            logger.error(f"Memory cleanup failed: {e}")

    scheduler.add_job(
        memory_cleanup_task,
        "interval",
        minutes=30,
        max_instances=1,
        id="memory_cleanup",
        name="Memory Cleanup Task"
    )

    scheduler.start()
    logger.info("Background tasks scheduler started successfully")
    logger.info("MPI Backend started successfully")
    
    yield
    
    # Shutdown
    logger.info("MPI Backend shutting down")
    scheduler.shutdown()
    
    # Shutdown thread pool
    _task_executor.shutdown(wait=True)
    logger.info("Background thread pool shutdown completed")
    
    logger.info("Background scheduler shutdown completed")
    logger.info("MPI Backend shutdown complete")

app = FastAPI(
    title="MPI Backend API",
    description="Backend API for MPI operations",
    version="1.0.0",
    lifespan=lifespan
)

# Add essential middleware only
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS middleware with optimized settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600
)

# Simplified timeout middleware
@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
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
        
        # Log only slow operations
        if elapsed > 10:
            logger.info(f"Request completed in {elapsed:.2f}s - {request.url.path}")
            
        return response
        
    except Exception as e:
        elapsed = time_module.time() - start_time
        logger.error(f"Request failed after {elapsed:.2f}s: {str(e)}")
        
        if "timeout" in str(e).lower() or elapsed > timeout_seconds:
            return JSONResponse(
                status_code=408,
                content={
                    "detail": f"Request timeout after {timeout_seconds} seconds",
                    "timeout": timeout_seconds,
                    "elapsed": elapsed
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

if __name__ == "__main__":
    # Optimized uvicorn configuration for stability
    uvicorn.run(
        "mpi_backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,
        loop="asyncio",
        http="h11",
        access_log=False,
        log_level="info",
        timeout_keep_alive=65,
        timeout_graceful_shutdown=30,
        limit_concurrency=1000,
        limit_max_requests=None
    )
