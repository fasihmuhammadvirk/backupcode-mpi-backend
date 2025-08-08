from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse as JSONResponse
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
import json

# Setup logging first, before any other imports
from mpi_backend.config.logging_config import setup_logging, get_missing_logger
setup_logging()

logger = logging.getLogger(__name__)
missing_logger = get_missing_logger()

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
from mpi_backend.api.routes import monthly_comparison
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

from mpi_backend.utils.failed_invoice_recovery import failed_invoice_recovery_background_task

# Import priority control utilities
from mpi_backend.utils.quickbooks_priority import set_scheduler_instance

# Import missing invoice downloader
from mpi_backend.utils.missing_invoice_downaloder import (
    missing_email_download_background_task
)

UTC_TZ = pytz.utc
PKT_TZ = pytz.timezone('Asia/Karachi')  # Pakistan Standard Time (UTC+5)

# Mapping control variables
MAPPINGS_ENABLED = os.getenv("ENABLE_MAPPINGS", "true").lower() == "true"
MAPPINGS_EXCLUSION_ENABLED = os.getenv("ENABLE_MAPPINGS_EXCLUSION", "true").lower() == "true"

# Thread pool for non-blocking background tasks (only for mapping tasks)
task_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mapping_task")

# Separate thread pool for invoice/email tasks to prevent blocking
# Increased workers to handle more frequent tasks without blocking
email_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="email_task")

# Task execution locks to prevent duplicates
task_locks = {
    'email_download': False,
    'statement_download': False,
    'failed_invoice_recovery': False,
    'missing_invoice_download': False,
    'uidi_no_match_update': False,
    'all_mappings_update': False
}


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
    Async wrapper for email download task to prevent blocking and duplicates
    """
    def _execute_email_download():
        # Check if task is already running
        if task_locks['email_download']:
            logger.warning("Email download task already running, skipping duplicate")
            return
        
        try:
            # Set lock to prevent duplicates
            task_locks['email_download'] = True
            logger.info("Starting async email download task")
            email_download_background_task()
            logger.info("Email download task completed successfully")
        except Exception as e:
            logger.error(f"Email download task failed: {str(e)}")
        finally:
            # Always release lock
            task_locks['email_download'] = False
    
    # Submit to dedicated email thread pool with low priority
    future = email_executor.submit(_execute_email_download)
    logger.debug("Email download task submitted to background thread pool")
    return future


def async_statement_download_wrapper():
    """
    Async wrapper for statement download task to prevent blocking and duplicates
    """
    def _execute_statement_download():
        # Check if task is already running
        if task_locks['statement_download']:
            logger.warning("Statement download task already running, skipping duplicate")
            return
        
        try:
            # Set lock to prevent duplicates
            task_locks['statement_download'] = True
            logger.info("Starting async statement download task")
            statement_download_background_task()
            logger.info("Statement download task completed successfully")
        except Exception as e:
            logger.error(f"Statement download task failed: {str(e)}")
        finally:
            # Always release lock
            task_locks['statement_download'] = False
    
    # Submit to dedicated email thread pool
    future = email_executor.submit(_execute_statement_download)
    logger.debug("Statement download task submitted to background thread pool")
    return future


def async_failed_invoice_recovery_wrapper():
    """
    Async wrapper for failed invoice recovery task to prevent blocking and duplicates
    """
    def _execute_failed_invoice_recovery():
        # Check if task is already running
        if task_locks['failed_invoice_recovery']:
            logger.warning("Failed invoice recovery task already running, skipping duplicate")
            return
        
        try:
            # Set lock to prevent duplicates
            task_locks['failed_invoice_recovery'] = True
            logger.info("Starting async failed invoice recovery task")
            failed_invoice_recovery_background_task()
            logger.info("Failed invoice recovery task completed successfully")
        except Exception as e:
            logger.error(f"Failed invoice recovery task failed: {str(e)}")
        finally:
            # Always release lock
            task_locks['failed_invoice_recovery'] = False
    
    # Submit to dedicated email thread pool
    future = email_executor.submit(_execute_failed_invoice_recovery)
    logger.debug("Failed invoice recovery task submitted to background thread pool")
    return future


def async_missing_invoice_download_wrapper():
    """
    Async wrapper for missing invoice download task to prevent blocking and duplicates
    """
    def _execute_missing_invoice_download():
        # Check if task is already running
        if task_locks['missing_invoice_download']:
            logger.warning("Missing invoice download task already running, skipping duplicate")
            return
        
        try:
            # Set lock to prevent duplicates
            task_locks['missing_invoice_download'] = True
            logger.info("Starting async missing invoice download task")
            missing_email_download_background_task()
            logger.info("Missing invoice download task completed successfully")
        except Exception as e:
            logger.error(f"Missing invoice download task failed: {str(e)}")
        finally:
            # Always release lock
            task_locks['missing_invoice_download'] = False
    
    # Submit to dedicated email thread pool
    future = email_executor.submit(_execute_missing_invoice_download)
    logger.debug("Missing invoice download task submitted to background thread pool")
    return future


def scheduled_uidi_no_match_update():
    """
    Scheduled task to update UIDI and NO Match items at 6 PM Pakistan time.
    Runs every day at 6 PM PKT.
    """
    def _execute_uidi_update():
        # Check if task is already running
        if task_locks['uidi_no_match_update']:
            logger.warning("UIDI/NO Match update task already running, skipping duplicate")
            return
        
        try:
            # Set lock to prevent duplicates
            task_locks['uidi_no_match_update'] = True
            logger.info("Starting scheduled UIDI/NO Match update at 6 PM PKT")
            
            from mpi_backend.database import SessionLocal
            with SessionLocal() as temp_db:
                result = safe_mapping_wrapper(
                    "Scheduled UIDI/NO Match Update (6 PM PKT)",
                    GoogleSheetSyncController.execute_sync_task,
                    temp_db, "update_no_match_uidi"
                )
                
            if result is None:
                logger.warning("Scheduled UIDI/NO Match update was skipped")
            else:
                logger.info("Scheduled UIDI/NO Match update completed successfully")
                
        except Exception as e:
            logger.error(f"Scheduled UIDI/NO Match update failed: {str(e)}")
        finally:
            # Always release lock
            task_locks['uidi_no_match_update'] = False
    
    # Submit to mapping thread pool for non-blocking execution
    future = task_executor.submit(_execute_uidi_update)
    logger.info("Scheduled UIDI/NO Match update submitted to background thread pool")
    return future


def scheduled_all_mappings_update():
    """
    Scheduled task to update all mappings.
    Runs every Saturday morning at 8 AM PKT.
    """
    def _execute_all_update():
        # Check if task is already running
        if task_locks['all_mappings_update']:
            logger.warning("All mappings update task already running, skipping duplicate")
            return
        
        try:
            # Set lock to prevent duplicates
            task_locks['all_mappings_update'] = True
            logger.info("Starting scheduled All Mappings update at 8 AM PKT (Saturday)")
            
            from mpi_backend.database import SessionLocal
            with SessionLocal() as temp_db:
                result = safe_mapping_wrapper(
                    "Scheduled All Mappings Update (8 AM PKT Saturday)",
                    GoogleSheetSyncController.execute_sync_task,
                    temp_db, "update_all"
                )
                
            if result is None:
                logger.warning("Scheduled All Mappings update was skipped")
            else:
                logger.info("Scheduled All Mappings update completed successfully")
                
        except Exception as e:
            logger.error(f"Scheduled All Mappings update failed: {str(e)}")
        finally:
            # Always release lock
            task_locks['all_mappings_update'] = False
    
    # Submit to mapping thread pool for non-blocking execution
    future = task_executor.submit(_execute_all_update)
    logger.info("Scheduled All Mappings update submitted to background thread pool")
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
    logger.info(f"Mapping exclusion during business hours: {MAPPINGS_EXCLUSION_ENABLED}")
    
    # Configure scheduler with optimized settings to prevent interference and duplicates
    scheduler = BackgroundScheduler(
        job_defaults={
            'coalesce': True,  # Combine missed executions
            'max_instances': 1,  # Prevent multiple instances
            'misfire_grace_time': 300  # 5 minutes grace period
        },
        timezone=UTC_TZ
    )
    
    # Register scheduler for dynamic job control
    set_scheduler_instance(scheduler)
    
    # Email download - every 5 minutes (async wrapper for non-blocking execution)
    scheduler.add_job(
        async_email_download_wrapper,  # Using async wrapper to prevent blocking
        "interval",
        minutes=5,
        max_instances=1,
        id="email_download",
        name="Email Download Task (Every 5 Minutes, Async)",
        misfire_grace_time=600
    )
    
    # Statement download - every 12 hours (async wrapper for non-blocking execution)
    scheduler.add_job(
        async_statement_download_wrapper,  # Using async wrapper to prevent blocking
        "interval",
        hours=12,
        max_instances=1,
        replace_existing=True,
        id="statement_download",
        name="Statement Download Task (Every 12 Hours, Async)",
        misfire_grace_time=1800
    )
    
    # Failed invoice recovery - every 1 hour (async wrapper for non-blocking execution)
    scheduler.add_job(
        async_failed_invoice_recovery_wrapper,  # Using async wrapper to prevent blocking
        "interval",
        hours=1,
        max_instances=1,
        replace_existing=True,
        id="failed_invoice_recovery",
        name="Failed Invoice Recovery Task (Every 1 Hour, Async)",
        misfire_grace_time=1800  # 30 minutes grace period
    )
    
    # Missing invoice download - every 5 hours (async wrapper for non-blocking execution)
    scheduler.add_job(
        async_missing_invoice_download_wrapper,  # Using async wrapper to prevent blocking
        "interval",
        hours=5,
        max_instances=1,
        replace_existing=True,
        id="missing_invoice_download",
        name="Missing Invoice Download Task (Every 5 Hours, Async)",
        misfire_grace_time=1800  # 30 minutes grace period
    )
    
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
    
    # 2. All Mappings Update: Every Saturday at 8 AM PKT (3 AM UTC, PKT = UTC+5)
    scheduler.add_job(
        scheduled_all_mappings_update,
        CronTrigger(hour=3, minute=0, timezone=UTC_TZ, day_of_week=5),  # 8 AM PKT = 3 AM UTC, Saturday = 5
        id="all_mappings_update_saturday_8am",
        replace_existing=True,
        max_instances=1,
        name="All Mappings Update (Every Saturday at 8 AM PKT)",
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
    
    # No startup tasks - all tasks run on their scheduled intervals only
    
    logger.info("Background tasks configured with optimized async execution:")
    logger.info("  • Email Download: Every 5 minutes (async, non-blocking)")
    logger.info("  • Statement Download: Every 12 hours (async, non-blocking)")
    logger.info("  • Failed Invoice Recovery: Every 1 hour (async, non-blocking)")
    logger.info("  • Missing Invoice Download: Every 5 hours (async, non-blocking)")
    logger.info("  • UIDI/NO Match Update: Daily at 6 PM PKT (async, thread pool)")
    logger.info("  • All Mappings Update: Every Saturday at 8 AM PKT (async, thread pool)")
    logger.info("  • Memory Cleanup: Every 30 minutes")
    logger.info("All tasks run in separate thread pools to prevent server slowdown")
    logger.info("Task deduplication enabled - prevents concurrent execution of same task")
    logger.info("MPI Backend started successfully with optimized async background tasks")
    
    yield
    
    # Shutdown
    logger.info("MPI Backend shutting down")
    scheduler.shutdown()
    
    # Reset all task locks to ensure clean shutdown
    for task_name in task_locks:
        task_locks[task_name] = False
    logger.info("Task locks reset for clean shutdown")
    
    # Shutdown thread pools
    task_executor.shutdown(wait=True)
    email_executor.shutdown(wait=True)
    logger.info("Background thread pools shutdown completed")
    
    logger.info("Background scheduler shutdown completed")
    logger.info("MPI Backend shutdown complete")

app = FastAPI(
    title="MPI Backend API",
    description="Backend API for MPI operations",
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=JSONResponse,
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

# Enhanced request logging middleware
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start_time = time_module.time()
    
    # Extract request details
    method = request.method
    url = str(request.url)
    path = request.url.path
    query_params = dict(request.query_params)
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    # Log request start
    logger.info(f"REQUEST START | {method} {path} | IP: {client_ip} | UA: {user_agent[:100]}")
    
    # Log query parameters if present
    if query_params:
        logger.debug(f"Query params: {json.dumps(query_params, default=str)}")
    
    # Determine timeout based on route
    if "/quickbooks/migrate-all" in path:
        timeout_seconds = 900  # 15 minutes for migrate-all
    elif "/quickbooks" in path:
        timeout_seconds = 600  # 10 minutes for other QuickBooks
    elif "/export" in path:
        timeout_seconds = 300  # 5 minutes for exports
    else:
        timeout_seconds = 120  # 2 minutes for standard operations
    
    try:
        response = await call_next(request)
        elapsed = time_module.time() - start_time
        
        # Log response details
        status_code = response.status_code
        response_size = len(response.body) if hasattr(response, 'body') else 0
        
        # Log all requests with different levels based on performance
        if status_code >= 400:
            logger.warning(f"REQUEST END | {method} {path} | Status: {status_code} | Time: {elapsed:.2f}s | Size: {response_size}B")
        elif elapsed > 10:
            logger.warning(f"REQUEST END | {method} {path} | Status: {status_code} | Time: {elapsed:.2f}s | Size: {response_size}B | SLOW")
        elif elapsed > 5:
            logger.info(f"REQUEST END | {method} {path} | Status: {status_code} | Time: {elapsed:.2f}s | Size: {response_size}B")
        else:
            logger.debug(f"REQUEST END | {method} {path} | Status: {status_code} | Time: {elapsed:.2f}s | Size: {response_size}B")
            
        return response
        
    except Exception as e:
        elapsed = time_module.time() - start_time
        logger.error(f"REQUEST ERROR | {method} {path} | Error: {str(e)} | Time: {elapsed:.2f}s")
        
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
    
    # Register all routes with logging
    routes = [
        ("Health", health.router),
        ("Supplier", supplier.router),
        ("Invoices List", invoices_list.router),
        ("Get Mappings", get_mappings.router),
        ("Sign In", signin.router),
        ("Invoice Items", invoice_items.router),
        ("QuickBooks", quickbooks.router),
        ("Filters", filters.router),
        ("Sync Mappings", sync_mappings.router),
        ("Monthly Comparison", monthly_comparison.router),
        ("Statements", statements.router),
    ]
    
    for route_name, router in routes:
        app.include_router(router)
        logger.info(f"Registered route: {route_name}")
    
    logger.info("All API routes registered successfully")

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
        access_log=False,  # We handle our own request logging
        log_level="info",
        timeout_keep_alive=65,
        timeout_graceful_shutdown=30,
        limit_concurrency=1000,
        limit_max_requests=None
    )
