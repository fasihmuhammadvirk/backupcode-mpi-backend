from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi_pagination import add_pagination
from fastapi.middleware.cors import CORSMiddleware
import pytz
import logging
import asyncio
import time as time_module

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
from mpi_backend.config import LOG_LEVEL
from mpi_backend.utils.invoice_downaloder import email_download_background_task
from mpi_backend.utils.statement_downloader import statement_download_background_task

# ENHANCED: Import priority control utilities
from mpi_backend.utils.quickbooks_priority import set_scheduler_instance

UTC_TZ = pytz.utc  # UTC Time Zone


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing ENTERPRISE background task system")
    logger.info("QuickBooks ABSOLUTE Priority Mode: ENABLED")
    logger.info("Dedicated QB database pool: 15 connections")
    logger.info("Background job pausing: ENABLED")
    logger.info("Dynamic scheduler control: ENABLED")

    scheduler = BackgroundScheduler()
    
    # ENHANCED: Register scheduler for dynamic job control
    set_scheduler_instance(scheduler)
    
    # OPTIMIZED: Email download with migrate-all priority awareness
    scheduler.add_job(
        email_download_background_task, 
        "interval", 
        minutes=3, 
        max_instances=10,  # Reduced further to prioritize migrate-all
        id="email_download",
        name="Email Download (migrate-all aware)"
    )

    # OPTIMIZED: Statement download with migrate-all priority awareness
    scheduler.add_job(
        statement_download_background_task, 
        "interval", 
        hours=10,
        max_instances=1,
        replace_existing=True,
        id="statement_download",
        name="Statement Download (migrate-all aware)"
    )

    # OPTIMIZED: Google Sheets sync with migrate-all priority awareness
    scheduler.add_job(
        GoogleSheetSyncController.execute_sync_task,
        "interval",
        hours=5,
        replace_existing=True,
        max_instances=1,
        id="google_sheets_sync",
        name="Google Sheets Sync (migrate-all aware)"
    )

    # OPTIMIZED: Mapping updates with migrate-all priority awareness
    scheduler.add_job(
        ItemsMappingController.execute_update_all_mappings_task,
        CronTrigger(hour=3, minute=0, timezone=UTC_TZ),
        id="update_all_mappings_daily",
        replace_existing=True,
        max_instances=1,
        name="Daily Mapping Update (migrate-all aware)"
    )

    scheduler.start()
    logger.info("Background tasks scheduler started with priority control")
    yield
    logger.info("Shutting down application")

# CRITICAL FIX: Extended timeout configuration for QuickBooks operations
app = FastAPI(
    lifespan=lifespan,
    title="MPI Backend API",
    description="Enterprise-grade backend with QuickBooks integration",
    version="1.0.0"
)

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ENHANCED TIMEOUT MIDDLEWARE: Priority-aware timeout handling
@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    """
    Enhanced middleware with absolute priority for migrate-all operations
    - migrate-all: 15 minutes timeout (absolute priority)
    - Other QuickBooks: 10 minutes timeout
    - Exports: 5 minutes timeout
    - Standard: 2 minutes timeout
    """
    # Determine timeout and priority based on route
    if "/quickbooks/migrate-all" in str(request.url):
        timeout_seconds = 900  # 15 minutes for migrate-all (ABSOLUTE PRIORITY)
        logger.info(f"MIGRATE-ALL operation started - ABSOLUTE PRIORITY - "
                   f"timeout: {timeout_seconds}s")
    elif "/quickbooks" in str(request.url):
        timeout_seconds = 600  # 10 minutes for other QuickBooks operations
        logger.info(f"QB operation started - timeout: {timeout_seconds}s")
    elif "/export" in str(request.url):
        timeout_seconds = 300  # 5 minutes for export operations
        logger.info(f"Export operation started - timeout: {timeout_seconds}s")
    else:
        timeout_seconds = 120  # 2 minutes for standard operations
    
    start_time = time_module.time()
    
    try:
        # Use asyncio.wait_for to enforce timeout
        response = await asyncio.wait_for(
            call_next(request), 
            timeout=timeout_seconds
        )
        
        elapsed = time_module.time() - start_time
        if "/quickbooks/migrate-all" in str(request.url):
            logger.info(f"MIGRATE-ALL completed in {elapsed:.2f}s")
        elif "/quickbooks" in str(request.url):
            logger.info(f"QuickBooks completed in {elapsed:.2f}s")
        
        return response
        
    except asyncio.TimeoutError:
        elapsed = time_module.time() - start_time
        logger.error(f"Request timeout after {elapsed:.2f}s for {request.url}")
        
        return JSONResponse(
            status_code=408,
            content={
                "detail": f"Request timeout after {timeout_seconds} seconds. "
                         f"Operation may still be processing in background.",
                "timeout": timeout_seconds,
                "elapsed": elapsed,
                "suggestion": "For large QuickBooks exports, consider reducing "
                            "the dataset size or try again later."
            }
        )
    except Exception as e:
        elapsed = time_module.time() - start_time
        logger.error(f"Request failed after {elapsed:.2f}s: {str(e)}")
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

# ENHANCED: Add startup event to log timeout configuration
@app.on_event("startup")
async def startup_event():
    logger.info("MPI Backend started with ENHANCED timeout protections:")
    logger.info("MIGRATE-ALL operations: 15 minutes timeout (ABSOLUTE PRIORITY)")
    logger.info(" Other QuickBooks operations: 10 minutes timeout")
    logger.info("Export operations: 5 minutes timeout")
    logger.info("Standard operations: 2 minutes timeout")
    logger.info("Dynamic job pausing: ACTIVE")
    logger.info("Priority control middleware: ACTIVE")
