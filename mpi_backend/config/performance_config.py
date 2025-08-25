"""
Performance and Resource Optimization Configuration for MPI Backend
Optimizes CPU, memory, and database usage for multi-user environments.
"""

import os
import multiprocessing as mp
from typing import Dict, Any

# =============================================================================
# SYSTEM RESOURCE LIMITS
# =============================================================================

# CPU Usage Limits (percentage)
MAX_CPU_USAGE = 95.0  # Maximum allowed CPU usage
CPU_WARNING_THRESHOLD = 85.0  # Warning threshold
CPU_CRITICAL_THRESHOLD = 98.0  # Critical threshold


# Memory Usage Limits (percentage)
MAX_MEMORY_USAGE = 95.0  # Maximum allowed memory usage
MEMORY_WARNING_THRESHOLD = 85.0  # Warning threshold
MEMORY_CRITICAL_THRESHOLD = 98.0  # Critical threshold

# Database Connection Limits
MAX_DB_CONNECTIONS = 20  # Total database connections
MAX_DB_CONNECTIONS_PER_USER = 3  # Max connections per user
DB_CONNECTION_TIMEOUT = 30  # Connection timeout in seconds
DB_POOL_RECYCLE = 1800  # Recycle connections every 30 minutes

# =============================================================================
# UVICORN SERVER OPTIMIZATION
# =============================================================================

def get_optimized_uvicorn_config() -> Dict[str, Any]:
    """Get optimized uvicorn configuration for production"""
    # Calculate optimal worker count based on CPU cores
    cpu_count = mp.cpu_count()
    optimal_workers = min(cpu_count, 4)  # Cap at 4 workers for stability
    
    return {
        "workers": optimal_workers,
        "worker_class": "uvicorn.workers.UvicornWorker",
        "limit_concurrency": 1000,  # Max concurrent connections
        "limit_max_requests": 1000,  # Restart workers after N requests
        "limit_max_requests_jitter": 100,  # Add randomness to restarts
        "timeout_keep_alive": 30,  # Keep-alive timeout
        "timeout_graceful_shutdown": 30,  # Graceful shutdown timeout
        "backlog": 2048,  # Connection backlog
        "proxy_headers": True,  # Handle proxy headers
        "forwarded_allow_ips": "*",  # Allow forwarded IPs
        "access_log": False,  # Disable access logs for performance
        "log_level": "info",
        "use_colors": False,  # Disable colors in production
        "loop": "asyncio",
        "http": "httptools",  # Use httptools for better performance
    }

# =============================================================================
# DATABASE OPTIMIZATION
# =============================================================================

def get_optimized_db_config() -> Dict[str, Any]:
    """Get optimized database configuration"""
    return {
        "pool_size": 10,  # Base connection pool size
        "max_overflow": 5,  # Additional connections when pool is full
        "pool_pre_ping": True,  # Validate connections before use
        "pool_timeout": 30,  # Timeout for getting connection from pool
        "pool_recycle": DB_POOL_RECYCLE,  # Recycle connections
        "echo": False,  # Disable SQL logging for performance
        "echo_pool": False,  # Disable pool logging
        "pool_reset_on_return": "commit",  # Reset connections on return
        "isolation_level": "READ_COMMITTED",  # Optimize isolation level
    }

def get_quickbooks_db_config() -> Dict[str, Any]:
    """Get optimized QuickBooks database configuration"""
    return {
        "pool_size": 8,  # Dedicated pool for QB operations
        "max_overflow": 3,  # Limited overflow for QB
        "pool_pre_ping": True,
        "pool_timeout": 15,  # Faster timeout for QB operations
        "pool_recycle": 900,  # Recycle QB connections every 15 minutes
        "echo": False,
        "echo_pool": False,
        "pool_reset_on_return": "commit",
        "isolation_level": "READ_COMMITTED",
    }

# =============================================================================
# BACKGROUND TASK OPTIMIZATION
# =============================================================================

# Task Execution Limits
MAX_CONCURRENT_TASKS = 5  # Maximum concurrent background tasks
MAX_TASK_DURATION = 1800  # Maximum task duration (30 minutes)
TASK_TIMEOUT = 900  # Default task timeout (15 minutes)

# Resource Monitoring
RESOURCE_CHECK_INTERVAL = 5  # Check resources every 5 seconds
RESOURCE_SAMPLE_COUNT = 3  # Number of samples for averaging

# Task Priority Settings
TASK_PRIORITIES = {
    "critical": {"max_concurrent": 2, "timeout": 300},
    "high": {"max_concurrent": 3, "timeout": 600},
    "medium": {"max_concurrent": 4, "timeout": 900},
    "low": {"max_concurrent": 5, "timeout": 1800},
}

# =============================================================================
# CACHING CONFIGURATION
# =============================================================================

# Redis Configuration (if available)
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() == "true"
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# Cache Settings
CACHE_TTL = 300  # Default cache TTL (5 minutes)
CACHE_MAX_SIZE = 1000  # Maximum cache entries
CACHE_CLEANUP_INTERVAL = 600  # Cleanup every 10 minutes

# =============================================================================
# RATE LIMITING
# =============================================================================

# Rate Limiting Configuration
RATE_LIMIT_ENABLED = True
RATE_LIMIT_DEFAULT = "100/minute"  # Default rate limit
RATE_LIMIT_STRICT = "50/minute"    # Strict rate limit for heavy operations

# Endpoint-specific rate limits
ENDPOINT_RATE_LIMITS = {
    "/health": "1000/minute",
    "/supplier": "200/minute",
    "/invoice": "100/minute",
    "/invoice-items/all": "50/minute",
    "/filter": "100/minute",
    "/quickbooks/export": "10/minute",
    "/quickbooks/migrate-all": "1/hour",
}

# =============================================================================
# MEMORY OPTIMIZATION
# =============================================================================

# Memory Management
MEMORY_CLEANUP_INTERVAL = 300  # Cleanup every 5 minutes
MEMORY_LEAK_THRESHOLD = 100  # MB threshold for memory leak detection
GC_THRESHOLD = (700, 10, 10)  # Garbage collection thresholds

# File Processing Limits
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB max file size
MAX_CONCURRENT_FILES = 3  # Max concurrent file processing
FILE_PROCESSING_TIMEOUT = 300  # File processing timeout

# =============================================================================
# LOGGING OPTIMIZATION
# =============================================================================

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_MAX_SIZE = 100 * 1024 * 1024  # 100MB max log file size
LOG_BACKUP_COUNT = 5  # Number of log backups to keep

# Performance Logging
PERFORMANCE_LOGGING_ENABLED = True
SLOW_QUERY_THRESHOLD = 1.0  # Log queries slower than 1 second
SLOW_REQUEST_THRESHOLD = 5.0  # Log requests slower than 5 seconds

# =============================================================================
# MONITORING AND METRICS
# =============================================================================

# Metrics Collection
METRICS_ENABLED = True
METRICS_INTERVAL = 60  # Collect metrics every minute
METRICS_RETENTION_DAYS = 7  # Keep metrics for 7 days

# Health Check Configuration
HEALTH_CHECK_INTERVAL = 30  # Health check every 30 seconds
HEALTH_CHECK_TIMEOUT = 10  # Health check timeout
HEALTH_CHECK_RETRIES = 3  # Number of health check retries

# =============================================================================
# ENVIRONMENT-SPECIFIC OVERRIDES
# =============================================================================

def get_environment_config() -> Dict[str, Any]:
    """Get configuration based on environment"""
    env = os.getenv("ENVIRONMENT", "development").lower()
    
    if env == "production":
        return {
            "workers": 4,
            "max_concurrent_tasks": 3,
            "rate_limit_enabled": True,
            "performance_logging_enabled": True,
            "metrics_enabled": True,
        }
    elif env == "staging":
        return {
            "workers": 2,
            "max_concurrent_tasks": 4,
            "rate_limit_enabled": True,
            "performance_logging_enabled": True,
            "metrics_enabled": True,
        }
    else:  # development
        return {
            "workers": 1,
            "max_concurrent_tasks": 5,
            "rate_limit_enabled": False,
            "performance_logging_enabled": False,
            "metrics_enabled": False,
        }

# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_config() -> bool:
    """Validate configuration values"""
    try:
        # Validate numeric values
        assert 0 < MAX_CPU_USAGE <= 100
        assert 0 < MAX_MEMORY_USAGE <= 100
        assert MAX_DB_CONNECTIONS > 0
        assert MAX_CONCURRENT_TASKS > 0
        
        # Validate timeouts
        assert DB_CONNECTION_TIMEOUT > 0
        assert TASK_TIMEOUT > 0
        
        # Validate cache settings
        assert CACHE_TTL > 0
        assert CACHE_MAX_SIZE > 0
        
        return True
        
    except AssertionError as e:
        print(f"Configuration validation failed: {e}")
        return False

def get_optimization_summary() -> Dict[str, Any]:
    """Get summary of optimization settings"""
    return {
        "cpu_limits": {
            "max_usage": f"{MAX_CPU_USAGE}%",
            "warning_threshold": f"{CPU_WARNING_THRESHOLD}%",
            "critical_threshold": f"{CPU_CRITICAL_THRESHOLD}%",
        },
        "memory_limits": {
            "max_usage": f"{MAX_MEMORY_USAGE}%",
            "warning_threshold": f"{MEMORY_WARNING_THRESHOLD}%",
            "critical_threshold": f"{MEMORY_CRITICAL_THRESHOLD}%",
        },
        "database": {
            "max_connections": MAX_DB_CONNECTIONS,
            "connection_timeout": f"{DB_CONNECTION_TIMEOUT}s",
            "pool_recycle": f"{DB_POOL_RECYCLE}s",
        },
        "background_tasks": {
            "max_concurrent": MAX_CONCURRENT_TASKS,
            "max_duration": f"{MAX_TASK_DURATION}s",
            "default_timeout": f"{TASK_TIMEOUT}s",
        },
        "caching": {
            "enabled": REDIS_ENABLED,
            "ttl": f"{CACHE_TTL}s",
            "max_size": CACHE_MAX_SIZE,
        },
        "rate_limiting": {
            "enabled": RATE_LIMIT_ENABLED,
            "default_limit": RATE_LIMIT_DEFAULT,
        },
    }

# Validate configuration on import
if not validate_config():
    raise ValueError("Invalid configuration values detected")
