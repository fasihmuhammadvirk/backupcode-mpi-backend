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
MAPPINGS_EXCLUSION_ENABLED = os.getenv(
    "ENABLE_MAPPING_EXCLUSION", "true"
).lower() == "true"


def is_pakistan_business_hours():
    """
    Check if current time is during Pakistan business hours (12 PM - 6 PM PKT).
    
    Returns:
        bool: True if during business hours (12 PM - 6 PM PKT)
    """
    if not MAPPINGS_EXCLUSION_ENABLED:
        return False
        
    pkt_now = datetime.now(PKT_TZ)
    current_time = pkt_now.time()
    
    # Business hours: 12:00 PM to 6:00 PM (12:00 - 18:00)
    business_start = time(12, 0)  # 12:00 PM
    business_end = time(18, 0)    # 6:00 PM
    
    return business_start <= current_time <= business_end


def should_skip_mapping_task(task_name: str):
    """
    Determine if a mapping task should be skipped based on current conditions.
    
    Args:
        task_name: Name of the task for logging
        
    Returns:
        bool: True if task should be skipped
    """
    if not MAPPINGS_ENABLED:
        logger.info(f"{task_name} skipped - mappings are disabled globally")
        return True
        
    if is_pakistan_business_hours():
        logger.info(
            f"{task_name} skipped - Pakistan business hours (12 PM - 6 PM PKT)"
        )
        return True
        
    return False


def safe_mapping_wrapper(task_func, task_name: str):
    """
    Wrapper function for mapping tasks with business hours checking.
    
    Args:
        task_func: The actual task function to execute
        task_name: Name of the task for logging
    """
    if should_skip_mapping_task(task_name):
        return
        
    try:
        logger.info(f"Starting {task_name}")
        result = task_func()
        logger.info(f"{task_name} completed: {result}")
    except Exception as e:
        logger.error(f"{task_name} failed: {str(e)}")


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
    
    # Optimized email download with reduced concurrency
    scheduler.add_job(
        email_download_background_task,
        "interval",
        minutes=5,
        max_instances=1,
        id="email_download",
        name="Email Download Task",
        misfire_grace_time=600
    )
    
    # Optimized statement download
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
    
    # Google Sheets sync - keep original schedule (8 hours)
    scheduler.add_job(
        GoogleSheetSyncController.execute_sync_task,
        "interval",
        hours=8,
        replace_existing=True,
        max_instances=1,
        id="google_sheets_sync",
        name="Google Sheets Sync Task",
        misfire_grace_time=1800
    )
    
    # NEW: All mappings update - once daily between 5-10 AM PKT
    # Schedule at 5 AM, 6 AM, 7 AM, 8 AM, 9 AM PKT
    # (converted to UTC: 12 AM, 1 AM, 2 AM, 3 AM, 4 AM UTC)
    for hour_pkt in [5, 6, 7, 8, 9]:  # 5 AM to 9 AM PKT
        hour_utc = (hour_pkt - 5) % 24  # Convert PKT to UTC (PKT = UTC+5)
        scheduler.add_job(
            lambda: safe_mapping_wrapper(
                ItemsMappingController.execute_update_all_mappings_task,
                "All Mappings Update"
            ),
            CronTrigger(hour=hour_utc, minute=0, timezone=UTC_TZ),
            id=f"update_all_mappings_{hour_pkt}am_pkt",
            replace_existing=True,
            max_instances=1,
            name=f"All Mappings Update Task ({hour_pkt} AM PKT)",
            misfire_grace_time=3600
        )
    
    # NEW: UIDI/No Match mappings update - every 8 hours with business hours exclusion
    # Schedule at 12 AM, 8 AM, 4 PM UTC (which is 5 AM, 1 PM, 9 PM PKT)
    # This avoids the 12 PM - 6 PM PKT business hours
    for hour_utc, hour_pkt_desc in [(0, "5 AM"), (8, "1 PM"), (16, "9 PM")]:
        scheduler.add_job(
            lambda: safe_mapping_wrapper(
                lambda: GoogleSheetSyncController.execute_sync_task(operation='update_no_match_uidi'),
                "UIDI Mappings Update"
            ),
            CronTrigger(hour=hour_utc, minute=0, timezone=UTC_TZ),
            id=f"update_uidi_mappings_{hour_utc}h_utc",
            replace_existing=True,
            max_instances=1,
            name=f"UIDI Mappings Update Task ({hour_pkt_desc} PKT)",
            misfire_grace_time=1800
        )

    # Simplified memory cleanup
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
