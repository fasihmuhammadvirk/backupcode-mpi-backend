"""
Simple Configuration for MPI Backend
No restrictions, no performance monitoring, no complex configurations.
"""

# Simple database configuration
DB_CONFIG = {
    "connection_timeout": 30,  # Standard timeout
    "pool_recycle": 3600,  # Recycle connections every hour
}

# Simple uvicorn configuration
UVICORN_CONFIG = {
    "workers": 1,  # Single worker for simplicity
    "backlog": 100,  # Standard backlog
    "timeout_keep_alive": 5,  # Standard keep-alive
    "timeout_graceful_shutdown": 30,  # Standard shutdown timeout
}

# Simple database pool configuration
DB_POOL_CONFIG = {
    "main": {
        "pool_size": 20,  # Standard pool size
        "max_overflow": 30,  # Standard overflow
        "pool_timeout": 30,  # Standard timeout
        "pool_recycle": 3600,  # Recycle every hour
        "pool_pre_ping": True,  # Enable health checks
        "echo": False,  # No SQL logging
    },
    "quickbooks": {
        "pool_size": 10,  # Standard pool size
        "max_overflow": 20,  # Standard overflow
        "pool_timeout": 30,  # Standard timeout
        "pool_recycle": 3600,  # Recycle every hour
        "pool_pre_ping": True,  # Enable health checks
        "echo": False,  # No SQL logging
    }
}

# Simple background task configuration
BACKGROUND_TASK_CONFIG = {
    "max_concurrent_tasks": 10,  # Reasonable limit
    "task_timeout": 300,  # 5 minute timeout
}

# Simple file processing configuration
FILE_PROCESSING_CONFIG = {
    "max_file_size": 100 * 1024 * 1024,  # 100MB limit
    "max_concurrent_files": 5,  # Reasonable limit
    "processing_timeout": 600,  # 10 minute timeout
    "chunk_size": 100000,  # Standard chunk size
}

# Simple cache configuration
CACHE_CONFIG = {
    "enabled": False,  # Cache disabled for simplicity
    "max_size": 1000,  # Small cache if enabled
    "ttl": 3600,  # 1 hour default
}

# Simple export configuration
EXPORT_CONFIG = {
    "max_records_per_batch": 10000,  # Reasonable batch size
    "max_concurrent_exports": 3,  # Reasonable limit
    "export_timeout": 1800,  # 30 minute timeout
}
