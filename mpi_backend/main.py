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

from mpi_backend.database.controllers.GoogleSheetSyncController import (
    GoogleSheetSyncController
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

# Thread pool for non-blocking background tasks
_task_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg_task")

def is_pakistan_business_hours():
    """
    Check if current time is within Pakistan business hours (12 PM - 6 PM PKT).
    
    Returns:
        bool: True if within business hours, False otherwise
    """
    try:
        # Get current time in Pakistan timezone
        pkt_now = datetime.now(PKT_TZ)
        
        # Check if it's between 12 PM (noon) and 6 PM PKT
        business_start = time(12, 0)  # 12:00 PM
        business_end = time(18, 0)    # 6:00 PM
        
        current_time = pkt_now.time()
        is_business_hour = business_start <= current_time <= business_end
        
        logger.debug(f"PKT time: {pkt_now.strftime('%H:%M')} | Business hours (12PM-6PM): {is_business_hour}")
        return is_business_hour
        
    except Exception as e:
        logger.error(f"Error checking Pakistan business hours: {e}")
        return False


def should_skip_mapping_task(task_name: str):
    """
    Determine if a mapping task should be skipped based on configuration and business hours.
    
    Args:
        task_name: Name of the task to check
        
    Returns:
        bool: True if task should be skipped
    """
    if not MAPPINGS_ENABLED:
        logger.info(f"Skipping {task_name} - mappings disabled via configuration")
        return True
        
    if MAPPINGS_EXCLUSION_ENABLED and is_pakistan_business_hours():
        logger.info(f"Skipping {task_name} - business hours exclusion active (12PM-6PM PKT)")
        return True
        
    return False


def async_mapping_wrapper(task_func, task_name: str):
    """
    Async wrapper function for mapping tasks with non-blocking execution.
    
    Args:
        task_func: The actual task function to execute
        task_name: Name of the task for logging
    """
    def _execute_task():
        if should_skip_mapping_task(task_name):
            return {"status": "skipped", "message": f"{task_name} skipped due to configuration"}
            
        try:
            logger.info(f"Starting {task_name}")
            result = task_func()
            logger.info(f"{task_name} completed successfully: {result}")
            return result
        except Exception as e:
            logger.error(f"{task_name} failed: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    # Execute in thread pool to avoid blocking the scheduler
    future = _task_executor.submit(_execute_task)
    logger.info(f"{task_name} submitted to background thread pool")
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
                all_result = GoogleSheetSyncController(temp_db).perform_sync_task('update_all')
                logger.info(f"Update all mappings completed: {all_result}")
            
            # Step 2: Update UIDI/No Match (includes Google Sheets sync automatically, only if step 1 succeeded)
            if all_result and all_result.get("success"):
                logger.info("Step 2/2: Starting UIDI/No Match update (with Google Sheets sync)")
                with SessionLocal() as temp_db:
                    uidi_result = GoogleSheetSyncController(temp_db).perform_sync_task('update_no_match_uidi')
                    logger.info(f"UIDI update completed: {uidi_result}")
            else:
                logger.warning("Skipping UIDI update due to failure in update all mappings")
                
            logger.info("Sequential mapping tasks completed successfully")
            
        except Exception as e:
            logger.error(f"Sequential mapping tasks failed: {str(e)}")
    
    # Execute in thread pool to avoid blocking
    future = _task_executor.submit(_execute_sequential)
    logger.info("Sequential mapping tasks submitted to background thread pool")
    return future


def async_email_download_task():
    """
    Async wrapper for email download task.
    """
    def _execute():
        try:
            email_download_background_task()
        except Exception as e:
            logger.error(f"Email download task failed: {str(e)}")
    
    future = _task_executor.submit(_execute)
    logger.info("Email download task submitted to background thread pool")
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
    
    # Email download - every 5 minutes (non-blocking)
    scheduler.add_job(
        async_email_download_task,
        "interval",
        minutes=5,
        max_instances=1,
        id="email_download",
        name="Email Download Task (Async)",
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
