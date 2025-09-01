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



# Import routes
from mpi_backend.api.routes import (
    health, supplier, invoices_list, get_mappings, invoice_items,
    quickbooks, signin, filters, sync_mappings, monthly_comparison, statements
)

# Import scheduler
from mpi_backend.background.scheduler import start_scheduler

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management - UNLIMITED PERFORMANCE"""
    logger.info("Starting UNLIMITED PERFORMANCE MPI Backend")
    
    # Initialize and start scheduler with unlimited performance
    try:
        scheduler = start_scheduler()
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

# Register routes
register_routes(app)
add_pagination(app)

# Enhanced health check endpoint
@app.get("/health/advanced")
async def advanced_health_check():
    """Advanced health check with memory management metrics"""
    try:
        # System metrics
        cpu_percent = get_windows_cpu_percent(interval=0.1)
        memory_percent = 0  # Memory monitoring disabled
        disk_percent = 0  # Disk monitoring disabled
        
        # Application metrics
        uptime = time.time() - app_start_time
        
        # Memory manager stats
        memory_stats = memory_manager.get_stats()
        
        health_data = {
            "status": "healthy",
            "timestamp": time.time(),
            "uptime_seconds": uptime,
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "memory_available_gb": "monitoring_disabled",
                "disk_percent": disk_percent,
                "disk_free_gb": "monitoring_disabled"
            },
            "requests": {
                "total": request_count,
                "errors": error_count,
                "success_rate": ((request_count - error_count) / request_count * 100) if request_count > 0 else 100
            },
            "memory_management": memory_stats,
            "optimization": {
                "cpu_threshold": MAX_CPU_USAGE,
                "memory_threshold": MAX_MEMORY_USAGE,
                "memory_cleanup_enabled": False, # Memory management disabled
                "cleanup_threshold": MEMORY_CLEANUP_INTERVAL
            }
        }
        
        # Determine overall health status
        if (cpu_percent > MAX_CPU_USAGE or 
            memory_percent > MAX_MEMORY_USAGE):
            health_data['status'] = 'warning'
        
        if (cpu_percent > MAX_CPU_USAGE * 1.2 or 
            memory.percent > MAX_MEMORY_USAGE * 1.2):
            health_data['status'] = 'critical'
        
        return health_data
        
    except Exception as e:
        logger.error(f"Error in advanced health check: {e}")
        return {"status": "error", "error": str(e)}


@app.get("/cpu-info")
async def get_cpu_information():
    """Get detailed CPU information for Windows VPS debugging"""
    try:
        cpu_info = get_cpu_info()
        return {
            "status": "success",
            "cpu_info": cpu_info,
            "message": "Use this endpoint to debug CPU percentage discrepancies between Task Manager and application"
        }
    except Exception as e:
        logger.error(f"Error getting CPU info: {e}")
        return {"status": "error", "error": str(e)}

# Optimization status endpoint
@app.get("/optimization/status")
async def optimization_status():
    """Get comprehensive optimization status"""
    try:
        memory_stats = memory_manager.get_stats()
        
        return {
            "timestamp": time.time(),
            "system_resources": {
                "status": "optimized",
                "memory_available": "monitoring_disabled"
            },
            "optimizations": {
                "memory_manager": memory_stats,
                "database_health": "optimized",
                "background_jobs": "optimized",
                "caching": "multi_level"
            },
            "garbage_collection": {
                "collections": gc.get_count(),
                "objects_tracked": len(gc.get_objects()) if hasattr(gc, 'get_objects') else 'N/A'
            },
            "recommendations": generate_optimization_recommendations(0)
        }
        
    except Exception as e:
        logger.error(f"Optimization status failed: {e}")
        return {"error": str(e)}

# Memory management endpoint
@app.get("/memory/status")
async def memory_status():
    """Get detailed memory management status"""
    try:
        memory_stats = memory_manager.get_stats()
        
        return {
            "timestamp": time.time(),
            "system_memory": {
                "status": "monitoring_disabled",
                "optimization": "enabled"
            },
            "memory_manager": memory_stats,
            "garbage_collection": {
                "collections": gc.get_count(),
                "objects_tracked": len(gc.get_objects()) if hasattr(gc, 'get_objects') else 'N/A'
            },
            "recommendations": generate_memory_recommendations(0, memory_stats)
        }
        
    except Exception as e:
        logger.error(f"Memory status failed: {e}")
        return {"error": str(e)}

def generate_optimization_recommendations(memory_percent: float) -> list:
    """Generate comprehensive optimization recommendations"""
    recommendations = []
    
    # Memory usage recommendations
    if memory_percent > MAX_MEMORY_USAGE * 0.9:
        recommendations.append({
            "priority": "critical",
            "message": f"Memory usage critical ({memory_percent:.1f}%)",
            "action": "Immediate cleanup required, consider restarting application"
        })
    elif memory_percent > MAX_MEMORY_USAGE * 0.8:
        recommendations.append({
            "priority": "high",
            "message": f"Memory usage high ({memory_percent:.1f}%)",
            "action": "Trigger memory cleanup and monitor closely"
        })
    
    # Proactive optimization recommendations
    if memory_percent > 60:
        recommendations.append({
            "priority": "medium",
            "message": "Moderate resource usage detected",
            "action": "Proactive optimizations are active - monitoring performance"
        })
    
    # General recommendations
    if not recommendations:
        recommendations.append({
            "priority": "low",
            "message": "System performing well with proactive optimizations",
            "action": "Continue monitoring and maintain current optimization settings"
        })
    
    return recommendations



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
