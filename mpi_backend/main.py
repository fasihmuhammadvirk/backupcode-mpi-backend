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
from mpi_backend.utils.missing_invoice_downaloder import (
    missing_email_download_background_task
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

# NEW: Separate thread pool for invoice/email tasks to prevent blocking
_email_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="email_task")

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
    Enhanced mapping wrapper with business hours awareness - runs independently of QuickBooks
    
    Args:
        operation_name (str): Name of the operation for logging
        operation_func (callable): Function to execute
        *args, **kwargs: Arguments to pass to the function
        
    Returns:
        Result of the operation or None if skipped/failed
    """
    try:
        # Check if mappings are globally disabled
        if not MAPPINGS_ENABLED:
            logger.info(f"{operation_name} skipped - mappings globally disabled")
            return None
        
        # Business hours exclusion for mapping operations
        if MAPPINGS_EXCLUSION_ENABLED and is_pakistan_business_hours():
            logger.info(f"{operation_name} skipped - within Pakistan business hours (12 PM - 6 PM PKT)")
            return None
        
        # Execute the operation
        logger.info(f"Starting {operation_name}")
        result = operation_func(*args, **kwargs)
        logger.info(f"Completed {operation_name} successfully")
        return result
        
    except Exception as e:
        logger.error(f"Error in {operation_name}: {str(e)}")
        return None


def async_email_download_wrapper():
    """
    Async wrapper for email download task to prevent blocking
    """
    def _execute_email_download():
        try:
            logger.info("Starting async email download task")
            email_download_background_task()
            logger.info("Email download task completed successfully")
        except Exception as e:
            logger.error(f"Email download task failed: {str(e)}")
    
    # Submit to dedicated email thread pool
    future = _email_executor.submit(_execute_email_download)
    logger.debug("Email download task submitted to background thread pool")
    return future


def async_missing_email_download_wrapper():
    """
    Async wrapper for missing email download task to prevent blocking
    """
    def _execute_missing_download():
        try:
            logger.info("Starting async missing email download task")
            missing_email_download_background_task()
            logger.info("Missing email download task completed successfully")
        except Exception as e:
            logger.error(f"Missing email download task failed: {str(e)}")
    
    # Submit to dedicated email thread pool
    future = _email_executor.submit(_execute_missing_download)
    logger.debug("Missing email download task submitted to background thread pool")
    return future


def async_statement_download_wrapper():
    """
    Async wrapper for statement download task to prevent blocking
    """
    def _execute_statement_download():
        try:
            logger.info("Starting async statement download task")
            statement_download_background_task()
            logger.info("Statement download task completed successfully")
        except Exception as e:
            logger.error(f"Statement download task failed: {str(e)}")
    
    # Submit to dedicated email thread pool
    future = _email_executor.submit(_execute_statement_download)
    logger.debug("Statement download task submitted to background thread pool")
    return future


def scheduled_uidi_no_match_update():
    """
    Scheduled task to update UIDI and NO Match items at 6 PM Pakistan time.
    Runs every day at 6 PM PKT.
    """
    def _execute_uidi_update():
        try:
            logger.info("Starting scheduled UIDI/NO Match update at 6 PM PKT")
            
            from mpi_backend.database import SessionLocal
            with SessionLocal() as temp_db:
                result = safe_mapping_wrapper(
                    "Scheduled UIDI/NO Match Update (6 PM PKT)",
                    EnhancedGoogleSheetSyncController.execute_sync_task,
                    temp_db, "update_no_match_uidi"
                )
                
            if result is None:
                logger.warning("Scheduled UIDI/NO Match update was skipped")
            else:
                logger.info("Scheduled UIDI/NO Match update completed successfully")
                
        except Exception as e:
            logger.error(f"Scheduled UIDI/NO Match update failed: {str(e)}")
    
    # Submit to mapping thread pool for non-blocking execution
    future = _task_executor.submit(_execute_uidi_update)
    logger.info("Scheduled UIDI/NO Match update submitted to background thread pool")
    return future


def scheduled_all_mappings_update():
    """
    Scheduled task to update all mappings.
    Runs every 48 hours at 1 AM PKT (every other day).
    """
    def _execute_all_update():
        try:
            logger.info("Starting scheduled All Mappings update at 1 AM PKT (48-hour interval)")
            
            from mpi_backend.database import SessionLocal
            with SessionLocal() as temp_db:
                result = safe_mapping_wrapper(
                    "Scheduled All Mappings Update (1 AM PKT)",
                    EnhancedGoogleSheetSyncController.execute_sync_task,
                    temp_db, "update_all"
                )
                
            if result is None:
                logger.warning("Scheduled All Mappings update was skipped")
            else:
                logger.info("Scheduled All Mappings update completed successfully")
                
        except Exception as e:
            logger.error(f"Scheduled All Mappings update failed: {str(e)}")
    
    # Submit to mapping thread pool for non-blocking execution
    future = _task_executor.submit(_execute_all_update)
    logger.info("Scheduled All Mappings update submitted to background thread pool")
    return future


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
    
    # Email download - every 5 minutes (async wrapper for non-blocking execution)
    scheduler.add_job(
        async_email_download_wrapper,  # NEW: Using async wrapper to prevent blocking
        "interval",
        minutes=5,
        max_instances=1,
        id="email_download",
        name="Email Download Task (Async)",
        misfire_grace_time=600
    )
    
    # Statement download - every 12 hours (async wrapper for non-blocking execution)
    scheduler.add_job(
        async_statement_download_wrapper,  # NEW: Using async wrapper to prevent blocking
        "interval",
        hours=12,
        max_instances=1,
        replace_existing=True,
        id="statement_download",
        name="Statement Download Task (Async)",
        misfire_grace_time=1800
    )
    
    # # Missing invoice download - daily (async wrapper for non-blocking execution)
    # scheduler.add_job(
    #     async_missing_email_download_wrapper,  # NEW: Using async wrapper to prevent blocking
    #     "interval",
    #     days=1,
    #     max_instances=1,
    #     replace_existing=True,
    #     id="missing_invoice_download",
    #     name="Missing Invoice Download Task (Daily, Async)",
    #     misfire_grace_time=3600  # 1 hour grace period
    # )
    
    # SCHEDULED MAPPING TASKS: Daily at specific times
    
    # 1. UIDI and NO Match Update: Every day at 6 PM PKT (1 PM UTC, PKT = UTC+5)
    scheduler.add_job(
        scheduled_uidi_no_match_update,
        CronTrigger(hour=13, minute=0, timezone=UTC_TZ),  # 6 PM PKT = 1 PM UTC
        id="daily_uidi_no_match_update",
        replace_existing=True,
        max_instances=1,
        name="Daily UIDI/NO Match Update (6 PM PKT)",
        misfire_grace_time=3600  # 1 hour grace period
    )
    
    # 2. All Mappings Update: Every 48 hours at 1 AM PKT (8 PM UTC previous day, PKT = UTC+5)
    scheduler.add_job(
        scheduled_all_mappings_update,
        CronTrigger(hour=20, minute=0, timezone=UTC_TZ, day="*/2"),  # 1 AM PKT = 8 PM UTC (previous day), every 2 days
        id="all_mappings_update_48h_1am",
        replace_existing=True,
        max_instances=1,
        name="All Mappings Update (Every 48 Hours at 1 AM PKT)",
        misfire_grace_time=3600  # 1 hour grace period
    )
    
    # LEGACY: DAILY MAPPING TASKS: Run once daily at 12 AM PKT (7 PM UTC, PKT = UTC+5)
    # Sequential execution: All mappings first (with Google Sheets sync), then UIDI (with Google Sheets sync)
    # Note: Google Sheets sync is automatically included in both operations
    # DISABLED: Replaced by individual scheduled tasks above
    # scheduler.add_job(
    #     async_sequential_mapping_task,
    #     CronTrigger(hour=19, minute=0, timezone=UTC_TZ),  # 12 AM PKT = 7 PM UTC
    #     id="daily_mapping_tasks",
    #     replace_existing=True,
    #     max_instances=1,
    #     name="Daily Mapping Tasks (12 AM PKT)",
    #     misfire_grace_time=3600  # 1 hour grace period
    # )

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
    
    # # Run missing invoice downloader on startup (async)
    # logger.info("Running missing invoice downloader on startup...")
    # try:
    #     async_missing_email_download_wrapper()
    #     logger.info("Startup missing invoice download submitted successfully")
    # except Exception as e:
    #     logger.error(f"Startup missing invoice download failed: {str(e)}")
    
    logger.info("Background tasks configured with async execution:")
    logger.info("  • Email Download: Every 5 minutes (async, non-blocking)")
    logger.info("  • Statement Download: Every 12 hours (async, non-blocking)")
    logger.info("  • Missing Invoice Download: Daily (async, non-blocking, and on startup)")
    logger.info("  • UIDI/NO Match Update: Daily at 6 PM PKT (async, thread pool)")
    logger.info("  • All Mappings Update: Every 48 hours at 1 AM PKT (async, thread pool)")
    logger.info("  • Memory Cleanup: Every 30 minutes")
    logger.info("MPI Backend started successfully with optimized async background tasks")
    
    yield
    
    # Shutdown
    logger.info("MPI Backend shutting down")
    scheduler.shutdown()
    
    # Shutdown thread pools
    _task_executor.shutdown(wait=True)
    _email_executor.shutdown(wait=True)
    logger.info("Background thread pools shutdown completed")
    
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
