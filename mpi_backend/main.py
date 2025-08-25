"""
Memory-Optimized MPI Backend
Implements advanced memory management strategies to reduce memory consumption.
"""

from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse as JSONResponse
from contextlib import asynccontextmanager
from fastapi_pagination import add_pagination
from fastapi.middleware.cors import CORSMiddleware
import logging
import time
import psutil
import uvicorn
import gc
import weakref
import threading
from typing import Dict, Any, Optional

# Setup logging first
from mpi_backend.config.logging_config import setup_logging, get_missing_logger
setup_logging()

logger = logging.getLogger(__name__)
missing_logger = get_missing_logger()

logger.info("Starting Memory-Optimized MPI Backend")

# Import routes
from mpi_backend.api.routes import (
    health, supplier, invoices_list, get_mappings, invoice_items,
    quickbooks, signin, filters, sync_mappings, monthly_comparison, statements
)

# Global variables for monitoring
app_start_time = time.time()
request_count = 0
error_count = 0

# Performance thresholds (updated to 85%)
MAX_CPU_USAGE = 85.0
MAX_MEMORY_USAGE = 85.0

# Memory management settings
MEMORY_CLEANUP_INTERVAL = 300  # 5 minutes
MEMORY_CLEANUP_THRESHOLD = 80.0  # Cleanup when memory > 80%
MAX_OBJECT_CACHE_SIZE = 1000  # Maximum cached objects
MEMORY_MONITORING_ENABLED = True

class MemoryManager:
    """Advanced memory management for the application"""
    
    def __init__(self):
        self.object_cache = weakref.WeakValueDictionary()
        self.cache_stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'last_cleanup': time.time()
        }
        self.cleanup_thread = None
        self.stop_cleanup = threading.Event()
        self._start_cleanup_thread()
    
    def _start_cleanup_thread(self):
        """Start background memory cleanup thread"""
        if self.cleanup_thread is None or not self.cleanup_thread.is_alive():
            self.cleanup_thread = threading.Thread(
                target=self._cleanup_worker,
                daemon=True,
                name="MemoryCleanup"
            )
            self.cleanup_thread.start()
            logger.info("Memory cleanup thread started")
    
    def _cleanup_worker(self):
        """Background worker for memory cleanup"""
        while not self.stop_cleanup.wait(MEMORY_CLEANUP_INTERVAL):
            try:
                self.perform_cleanup()
            except Exception as e:
                logger.error(f"Memory cleanup error: {e}")
    
    def perform_cleanup(self):
        """Perform comprehensive memory cleanup"""
        try:
            # Force garbage collection
            collected = gc.collect()
            
            # Clear object cache if too large
            if len(self.object_cache) > MAX_OBJECT_CACHE_SIZE:
                self.object_cache.clear()
                self.cache_stats['evictions'] += 1
                logger.info(f"Object cache cleared, {collected} objects collected")
            
            # Check memory usage
            memory = psutil.virtual_memory()
            if memory.percent > MEMORY_CLEANUP_THRESHOLD:
                logger.warning(
                    "High memory usage detected (%.1f%%), performing cleanup",
                    memory.percent
                )
                
                # Aggressive cleanup
                gc.collect()
                self.object_cache.clear()
                
                # Log memory status
                memory_after = psutil.virtual_memory()
                logger.info(
                    "Memory cleanup complete - Before: %.1f%%, After: %.1f%%",
                    memory.percent, memory_after.percent
                )
            
            self.cache_stats['last_cleanup'] = time.time()
            
        except Exception as e:
            logger.error(f"Error during memory cleanup: {e}")
    
    def cache_object(self, key: str, obj: Any):
        """Cache an object with weak references"""
        if len(self.object_cache) < MAX_OBJECT_CACHE_SIZE:
            self.object_cache[key] = obj
            return True
        return False
    
    def get_cached_object(self, key: str) -> Optional[Any]:
        """Get a cached object"""
        obj = self.object_cache.get(key)
        if obj is not None:
            self.cache_stats['hits'] += 1
        else:
            self.cache_stats['misses'] += 1
        return obj
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory manager statistics"""
        return {
            'cache_size': len(self.object_cache),
            'cache_stats': self.cache_stats.copy(),
            'memory_usage': psutil.virtual_memory().percent,
            'last_cleanup': self.cache_stats['last_cleanup']
        }
    
    def shutdown(self):
        """Shutdown memory manager"""
        self.stop_cleanup.set()
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=5)
        self.object_cache.clear()
        logger.info("Memory manager shutdown complete")

# Initialize memory manager
memory_manager = MemoryManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager with memory optimization"""
    # Startup
    logger.info("Initializing Memory-Optimized MPI Backend")
    logger.info("Memory management: ENABLED")
    logger.info("Resource monitoring: ENABLED")
    
    yield
    
    # Shutdown
    logger.info("Memory-Optimized MPI Backend shutting down")
    memory_manager.shutdown()
    gc.collect()
    logger.info("Memory-Optimized MPI Backend shutdown complete")

# Create FastAPI application
app = FastAPI(
    title="MPI Backend API (Memory-Optimized)",
    description="Memory-optimized Backend API with advanced resource management",
    version="1.6.0",
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

# Memory-aware resource monitoring middleware
@app.middleware("http")
async def memory_aware_middleware(request: Request, call_next):
    """Memory-aware middleware with automatic cleanup"""
    global request_count, error_count
    
    start_time = time.time()
    request_count += 1
    
    # Check system resources before processing
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        
        # Circuit breaker: reject requests if resources are critically low
        if cpu_percent > MAX_CPU_USAGE or memory_percent > MAX_MEMORY_USAGE:
            error_count += 1
            logger.warning(
                "Resource threshold exceeded - CPU: %.1f%%, Memory: %.1f%% - "
                "Rejecting request",
                cpu_percent, memory_percent
            )
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Service temporarily unavailable due to high resource usage",
                    "retry_after": 30
                }
            )
        
        # Trigger cleanup if memory usage is high
        if memory_percent > MEMORY_CLEANUP_THRESHOLD:
            logger.info("High memory usage detected, triggering cleanup")
            memory_manager.perform_cleanup()
        
        # Log high resource usage
        if cpu_percent > MAX_CPU_USAGE * 0.8 or memory_percent > MAX_MEMORY_USAGE * 0.8:
            logger.warning(
                "High resource usage - CPU: %.1f%%, Memory: %.1f%%",
                cpu_percent, memory_percent
            )
            
    except Exception as e:
        logger.error(f"Error monitoring resources: {e}")
    
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

# Enhanced request logging middleware
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Enhanced request logging with memory metrics"""
    start_time = time.time()
    
    # Extract request details
    method = request.method
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"
    
    # Log request start
    logger.info(
        "REQUEST START | %s %s | IP: %s",
        method, path, client_ip
    )
    
    try:
        response = await call_next(request)
        elapsed = time.time() - start_time
        
        # Log response details
        status_code = response.status_code
        response_size = len(response.body) if hasattr(response, 'body') else 0
        
        # Log all requests with different levels based on performance
        if status_code >= 400:
            logger.warning(
                "REQUEST END | %s %s | Status: %s | Time: %.2fs | Size: %sB",
                method, path, status_code, elapsed, response_size
            )
        elif elapsed > 5:
            logger.info(
                "REQUEST END | %s %s | Status: %s | Time: %.2fs | Size: %sB",
                method, path, status_code, elapsed, response_size
            )
        else:
            logger.debug(
                "REQUEST END | %s %s | Status: %s | Time: %.2fs | Size: %sB",
                method, path, status_code, elapsed, response_size
            )
            
        return response
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "REQUEST ERROR | %s %s | Error: %s | Time: %.2fs",
            method, path, str(e), elapsed
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
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
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
                "memory_percent": memory.percent,
                "memory_available_gb": memory.available / (1024**3),
                "disk_percent": disk.percent,
                "disk_free_gb": disk.free / (1024**3)
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
                "memory_cleanup_enabled": MEMORY_MONITORING_ENABLED,
                "cleanup_threshold": MEMORY_CLEANUP_THRESHOLD
            }
        }
        
        # Determine overall health status
        if (cpu_percent > MAX_CPU_USAGE or 
            memory.percent > MAX_MEMORY_USAGE):
            health_data['status'] = 'warning'
        
        if (cpu_percent > MAX_CPU_USAGE * 1.2 or 
            memory.percent > MAX_MEMORY_USAGE * 1.2):
            health_data['status'] = 'critical'
        
        return health_data
        
    except Exception as e:
        logger.error(f"Advanced health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }

# Memory management endpoint
@app.get("/memory/status")
async def memory_status():
    """Get detailed memory management status"""
    try:
        memory = psutil.virtual_memory()
        memory_stats = memory_manager.get_stats()
        
        return {
            "timestamp": time.time(),
            "system_memory": {
                "total_gb": memory.total / (1024**3),
                "used_gb": memory.used / (1024**3),
                "available_gb": memory.available / (1024**3),
                "percent": memory.percent
            },
            "memory_manager": memory_stats,
            "garbage_collection": {
                "collections": gc.get_count(),
                "objects_tracked": len(gc.get_objects()) if hasattr(gc, 'get_objects') else 'N/A'
            },
            "recommendations": generate_memory_recommendations(memory.percent, memory_stats)
        }
        
    except Exception as e:
        logger.error(f"Memory status failed: {e}")
        return {"error": str(e)}

def generate_memory_recommendations(memory_percent: float, memory_stats: Dict[str, Any]) -> list:
    """Generate memory optimization recommendations"""
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
    
    # Cache recommendations
    cache_size = memory_stats.get('cache_size', 0)
    if cache_size > MAX_OBJECT_CACHE_SIZE * 0.8:
        recommendations.append({
            "priority": "medium",
            "message": f"Object cache large ({cache_size} objects)",
            "action": "Consider reducing cache size or implementing LRU eviction"
        })
    
    # General recommendations
    if not recommendations:
        recommendations.append({
            "priority": "low",
            "message": "Memory usage within acceptable limits",
            "action": "Continue monitoring and maintain current settings"
        })
    
    return recommendations

if __name__ == "__main__":
    logger.info("Starting memory-optimized uvicorn server")
    
    uvicorn.run(
        "mpi_backend.main_memory_optimized:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True
    )
