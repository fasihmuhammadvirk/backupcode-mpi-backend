from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse as JSONResponse
from contextlib import asynccontextmanager
from fastapi_pagination import add_pagination
from fastapi.middleware.cors import CORSMiddleware
import logging
import time as time_module
from fastapi.middleware.gzip import GZipMiddleware
import uvicorn
import json

# Setup logging first, before any other imports
from mpi_backend.config.logging_config import setup_logging, get_missing_logger
from mpi_backend.config.windows_config import get_uvicorn_config
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
# Note: Scheduler will be imported lazily inside lifespan to avoid startup overhead during tests

UTC_TZ = None  # Not used in this module; scheduler handles timezones


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing background task system")
    logger.info("MPI Backend starting up")
    logger.info("Timeout configuration active")
    logger.info("Background tasks initializing")

    # Initialize centralized scheduler (managed in background/scheduler.py)
    scheduler = None
    try:
        import os as _os
        if _os.getenv("DISABLE_SCHEDULER") == "1" or _os.getenv("PYTEST_CURRENT_TEST"):
            logger.info("Scheduler disabled via environment during tests/maintenance")
        else:
            from mpi_backend.background.scheduler import init_scheduler as _init_scheduler
            scheduler = _init_scheduler()
            scheduler.start()
            logger.info("Background tasks scheduler started successfully")
            logger.info("MPI Backend started successfully with background scheduler")
    except Exception as e:
        logger.error(f"Failed to start background scheduler: {e}")

    yield

    # Shutdown
    logger.info("MPI Backend shutting down")
    try:
        if scheduler is not None:
            scheduler.shutdown()
    except Exception as e:
        logger.error(f"Error shutting down scheduler: {e}")

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

# Windows-specific connection error handling middleware
@app.middleware("http")
async def connection_error_handler(request: Request, call_next):
    try:
        # Check if client is still connected before processing
        if request.client and hasattr(request.client, 'is_connected'):
            if not request.client.is_connected():
                return JSONResponse(
                    status_code=499,  # Client Closed Request
                    content={"detail": "Client disconnected"}
                )
        
        response = await call_next(request)
        return response
        
    except Exception as e:
        # Handle h11 protocol errors specifically
        if "h11" in str(e).lower() or "protocol" in str(e).lower():
            logger.warning(f"Connection protocol error handled: {e}")
            return JSONResponse(
                status_code=499,
                content={"detail": "Connection error - please retry"}
            )
        raise

# Enhanced request logging middleware


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start_time = time_module.time()
    
    # Extract request details
    method = request.method
    path = request.url.path
    query_params = dict(request.query_params)
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    # Log request start
    logger.info(
        "REQUEST START | %s %s | IP: %s | UA: %s",
        method,
        path,
        client_ip,
        user_agent[:100],
    )
    
    # Log query parameters if present
    if query_params:
        logger.debug(
            "Query params: %s",
            json.dumps(query_params, default=str),
        )
    
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
            logger.warning(
                "REQUEST END | %s %s | Status: %s | Time: %.2fs | Size: %sB",
                method,
                path,
                status_code,
                elapsed,
                response_size,
            )
        elif elapsed > 10:
            logger.warning(
                "REQUEST END | %s %s | Status: %s | Time: %.2fs | Size: %sB | SLOW",
                method,
                path,
                status_code,
                elapsed,
                response_size,
            )
        elif elapsed > 5:
            logger.info(
                "REQUEST END | %s %s | Status: %s | Time: %.2fs | Size: %sB",
                method,
                path,
                status_code,
                elapsed,
                response_size,
            )
        else:
            logger.debug(
                "REQUEST END | %s %s | Status: %s | Time: %.2fs | Size: %sB",
                method,
                path,
                status_code,
                elapsed,
                response_size,
            )
            
        return response
        
    except Exception as e:
        elapsed = time_module.time() - start_time
        logger.error(
            "REQUEST ERROR | %s %s | Error: %s | Time: %.2fs",
            method,
            path,
            str(e),
            elapsed,
        )
        
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
    # Get platform-specific configuration
    uvicorn_config = get_uvicorn_config()
    
    # Windows-optimized uvicorn configuration to prevent h11 protocol errors
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
        **uvicorn_config  # Use platform-specific settings
    )
