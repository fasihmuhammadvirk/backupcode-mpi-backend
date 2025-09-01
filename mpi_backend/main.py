"""
UNLIMITED PERFORMANCE MPI Backend
All restrictions removed for maximum speed and scalability.
"""

from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse as JSONResponse
from contextlib import asynccontextmanager
from fastapi_pagination import add_pagination
from fastapi.middleware.cors import CORSMiddleware
import logging
import time
import uvicorn
import psutil
import platform

# Import routes
from mpi_backend.api.routes import (
    health, supplier, invoices_list, get_mappings, invoice_items,
    quickbooks, signin, filters, sync_mappings, monthly_comparison, statements, customer_job
)

# Import scheduler
from mpi_backend.background.scheduler import init_scheduler

# Setup logging first
from mpi_backend.config.logging_config import setup_logging, get_missing_logger
setup_logging()

logger = logging.getLogger(__name__)
missing_logger = get_missing_logger()

logger.info("Starting UNLIMITED PERFORMANCE MPI Backend")

# Simple application state
app_start_time = time.time()
request_count = 0
error_count = 0


def get_cpu_info():
    """Get CPU information without restrictions"""
    try:
        cpu_count = psutil.cpu_count(logical=True)
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_freq = psutil.cpu_freq()
        
        return {
            "platform": platform.system(),
            "cpu_count": cpu_count,
            "cpu_percent": cpu_percent,
            "cpu_freq_current": cpu_freq.current if cpu_freq else None,
            "cpu_freq_min": cpu_freq.min if cpu_freq else None,
            "cpu_freq_max": cpu_freq.max if cpu_freq else None,
            "message": "CPU monitoring enabled without restrictions"
        }
    except Exception as e:
        logger.error(f"Error getting CPU info: {e}")
        return {
            "error": str(e),
            "message": "CPU monitoring failed"
        }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management - UNLIMITED PERFORMANCE"""
    logger.info("Starting UNLIMITED PERFORMANCE MPI Backend")
    
    # Initialize and start scheduler with unlimited performance
    try:
        scheduler = init_scheduler()
        if scheduler:
            logger.info("Scheduler started with unlimited performance")
        else:
            logger.error("Failed to start scheduler")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
    
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
        logger.error(f"Request failed: {request.method} {request.url.path} - {e}")
        raise

# Register routes
def register_routes():
    """Register all API routes"""
    logger.info("Registering API routes with memory optimization")
    
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
        ("Customer Job", customer_job.router),
    ]
    
    for name, router in routes:
        app.include_router(router)
        logger.info(f"Registered route: {name}")
    
    logger.info("All API routes registered successfully")

# Register routes
register_routes()

# Add pagination support
add_pagination(app)

# Simple health check
@app.get("/health")
async def health_check():
    """Simple health check without restrictions"""
    return {"status": "healthy", "message": "MPI Backend is running"}

# CPU info endpoint
@app.get("/cpu-info")
async def get_cpu_information():
    """Get detailed CPU information without restrictions"""
    try:
        cpu_info = get_cpu_info()
        return {
            "status": "success",
            "cpu_info": cpu_info,
            "message": "CPU monitoring enabled without restrictions"
        }
    except Exception as e:
        logger.error(f"Error getting CPU info: {e}")
        return {"status": "error", "error": str(e)}

# Simple status endpoint
@app.get("/status")
async def get_status():
    """Get application status without restrictions"""
    uptime = time.time() - app_start_time
    
    return {
        "status": "running",
        "uptime_seconds": int(uptime),
        "requests_processed": request_count,
        "errors_encountered": error_count,
        "performance_mode": "unrestricted",
        "message": "Application running without restrictions"
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "MPI Backend API - UNLIMITED PERFORMANCE",
        "version": "2.0.0",
        "status": "running",
        "performance_mode": "unrestricted"
    }

if __name__ == "__main__":
    uvicorn.run(
        "mpi_backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
