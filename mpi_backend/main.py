"""
UNLIMITED PERFORMANCE MPI Backend
All restrictions removed for maximum speed and scalability.
"""

import warnings
import os

# Suppress common deprecation warnings
warnings.filterwarnings("ignore", message=".*GenericModel.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*ARC4.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*has been moved.*", category=UserWarning)

from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse as JSONResponse
from contextlib import asynccontextmanager
from fastapi_pagination import add_pagination
from fastapi.middleware.cors import CORSMiddleware
import logging
import time
import uvicorn



# Import routes
from mpi_backend.api.routes import (
    health, supplier, invoices_list, mapping_updates, invoice_items,
    quickbooks, signin, filters, google_sheets_sync, monthly_comparison, statements, chatbot,
    users, companies, feature_flags, model_extracted_data, dbt, purchase_orders, supplier_comparison,
    project_estimation, project_estimate_fixed_items, project_estimate_fixed_quick_items, project_estimate_sub_items,
    project_estimate_point_quick_items, project_estimate_point_items, project_estimate_finish_items, project_estimate_finish_quick_items,
    user_overrides, override_logs, mapping_history, invoice_voids, email_vendor, extraction_queue
)

# Import scheduler
from mpi_backend.background.scheduler import start_scheduler

# Setup logging first (before other imports that might log)
from mpi_backend.config.logging_config import setup_logging, get_missing_logger
setup_logging()

logger = logging.getLogger(__name__)
missing_logger = get_missing_logger()

logger.info("Starting UNLIMITED PERFORMANCE MPI Backend")

# Simple application state
app_start_time = time.time()
request_count = 0
error_count = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management - UNLIMITED PERFORMANCE"""
    logger.info("Starting UNLIMITED PERFORMANCE MPI Backend")

    # Initialize and start scheduler with unlimited performance
    try:
        scheduler = start_scheduler()
        if scheduler:
            logger.info("="*30)
            logger.info("Scheduler started")
            logger.info("="*30)
        else:
            logger.error("Failed to start scheduler")
    except Exception:
        logger.exception("Failed to start scheduler")

    yield

    logger.info("Shutting down MPI Backend")
    logger.info("MPI Backend shutdown complete")

# Create FastAPI application
app = FastAPI(
    title="MPI Backend API",
    description="Simple, unrestricted Backend API",
    version="2.0.0",
    lifespan=lifespan,
    default_response_class=JSONResponse,
)

# Add essential middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600
)

# Simple request logging middleware
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Simple middleware for logging requests"""
    global request_count, error_count
    
    start_time = time.time()
    request_count += 1
    
    # Process request
    try:
        response = await call_next(request)
        elapsed = time.time() - start_time
        
        # Log slow requests
        if elapsed > 1.0:
            logger.info(
                "Slow request: %s %s took %.2fs",
                request.method, request.url.path, elapsed
            )
        
        return response
        
    except Exception as e:
        error_count += 1
        elapsed = time.time() - start_time
        logger.error(
            "Request failed: %s %s - Error: %s - Time: %.2fs",
            request.method, request.url.path, str(e), elapsed
        )
        raise



def register_routes(app):
    """Register API routes with logging"""
    logger.info("Registering API routes with memory optimization")
    
    # Register all routes with logging
    routes = [
        ("Health", health.router),
        ("Supplier", supplier.router),
        ("Invoices List", invoices_list.router),
        ("Mapping Updates", mapping_updates.router),
        ("Sign In", signin.router),
        ("Invoice Items", invoice_items.router),
        ("QuickBooks", quickbooks.router),
        ("Filters", filters.router),
        ("Google Sheets Sync", google_sheets_sync.router),
        ("Monthly Comparison", monthly_comparison.router),
        ("Statements", statements.router),
        ("Chatbot", chatbot.router),
        ("Users", users.router),
        ("Companies", companies.router),
        ("Feature Flags", feature_flags.router),
        ("Model Extracted Data", model_extracted_data.router),
        ("DBT Operations", dbt.router),
        ("Purchase Orders", purchase_orders.router),
        ("Supplier Comparison", supplier_comparison.router),
        ("Project Estimation", project_estimation.router),
        ("Project Estimate Fixed Items", project_estimate_fixed_items.router),
        ("Project Estimate Fixed Quick Items", project_estimate_fixed_quick_items.router),
        ("Project Estimate Sub Items", project_estimate_sub_items.router),
        ("Project Estimate Point Items", project_estimate_point_items.router),
        ("Project Estimate Point Quick Items", project_estimate_point_quick_items.router),
        ("Project Estimate Finish Items", project_estimate_finish_items.router),
        ("Project Estimate Finish Quick Items", project_estimate_finish_quick_items.router),
        ("User Overrides", user_overrides.router),
        ("Override Logs", override_logs.router),
        ("Mapping History", mapping_history.router),
        ("Invoice Voids", invoice_voids.router),
        ("Email Vendor", email_vendor.router),
        ("Extraction Queue", extraction_queue.router),
    ]
    
    for route_name, router in routes:
        app.include_router(router)
        logger.info(f"Registered route: {route_name}")
    
    logger.info("All API routes registered successfully")

# Register routes
register_routes(app)
add_pagination(app)



# Keep main focused on app setup and route registration only

if __name__ == "__main__":
    logger.info("Starting memory-optimized uvicorn server")
    
    # Add signal handlers for graceful shutdown
    import signal
    import sys
    
    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        
        # Stop scheduler if running
        if 'scheduler' in globals() and scheduler and scheduler.running:
            try:
                logger.info("Stopping scheduler...")
                scheduler.shutdown(wait=False)
                logger.info("Scheduler stopped")
            except Exception as e:
                logger.error(f"Error stopping scheduler: {e}")
        

        
        # Exit gracefully
        sys.exit(0)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal
    
    try:
        uvicorn.run(
            "mpi_backend.main:app",  # Fixed: use main.py, not main_memory_optimized
            host="0.0.0.0",
            port=8000,
            log_level="info",
            access_log=True
        )
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down...")
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        logger.error(f"Uvicorn error: {e}")
        signal_handler(signal.SIGTERM, None)
