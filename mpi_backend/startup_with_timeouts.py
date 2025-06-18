#!/usr/bin/env python3
"""
Enhanced startup script for MPI Backend with QuickBooks timeout protection.

This script ensures that the application starts with proper timeout configurations
to prevent QuickBooks operations from getting stuck or hanging indefinitely.
"""

import uvicorn
import os
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def setup_environment():
    """Setup environment variables for optimal QuickBooks performance"""
    
    # CRITICAL: QuickBooks Timeout Settings
    os.environ.setdefault("QB_OPERATION_TIMEOUT", "600")  # 10 minutes
    os.environ.setdefault("QB_CHUNK_SIZE", "500")  # Process in chunks of 500
    os.environ.setdefault("QB_CHUNK_DELAY", "1.0")  # 1 second between chunks
    os.environ.setdefault("QB_PROGRESS_UPDATE_INTERVAL", "10")  # Every 10%
    
    # HTTP Request Timeouts
    os.environ.setdefault("REQUEST_TIMEOUT_DEFAULT", "120")  # 2 minutes
    os.environ.setdefault("REQUEST_TIMEOUT_QUICKBOOKS", "600")  # 10 minutes
    os.environ.setdefault("REQUEST_TIMEOUT_EXPORT", "300")  # 5 minutes
    
    # Database Timeouts
    os.environ.setdefault("DB_CONNECTION_TIMEOUT", "30")  # 30 seconds
    os.environ.setdefault("DB_QUERY_TIMEOUT", "120")  # 2 minutes
    os.environ.setdefault("DB_BULK_OPERATION_TIMEOUT", "300")  # 5 minutes
    
    # S3 Upload Timeouts
    os.environ.setdefault("S3_UPLOAD_TIMEOUT", "300")  # 5 minutes
    os.environ.setdefault("S3_PRESIGNED_URL_EXPIRY", "3600")  # 1 hour
    
    # Performance Settings
    os.environ.setdefault("PERFORMANCE_LOGGING_ENABLED", "true")
    os.environ.setdefault("PERFORMANCE_LOG_SLOW_QUERIES", "5")  # Log slow queries
    
    # QuickBooks Priority Settings
    os.environ.setdefault("QB_PRIORITY_MODE", "true")
    os.environ.setdefault("QB_DEDICATED_POOL_SIZE", "15")
    os.environ.setdefault("QB_MAX_CONCURRENT_EXPORTS", "3")
    os.environ.setdefault("QB_PAUSE_BACKGROUND_JOBS", "true")
    
    logger.info("🔧 Environment configured for QuickBooks operations")
    logger.info(f"   ⏱️  QB Operation Timeout: {os.environ['QB_OPERATION_TIMEOUT']}s")
    logger.info(f"   📦 QB Chunk Size: {os.environ['QB_CHUNK_SIZE']} invoices")
    logger.info(f"   🔄 QB Chunk Delay: {os.environ['QB_CHUNK_DELAY']}s")
    logger.info(f"   💾 DB Connection Pool: {os.environ['QB_DEDICATED_POOL_SIZE']}")

def get_uvicorn_config():
    """Get optimized uvicorn configuration for QuickBooks operations"""
    
    # Get port from environment or use default
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    
    # Uvicorn configuration optimized for long-running operations
    config = {
        "app": "mpi_backend.main:app",
        "host": host,
        "port": port,
        "reload": False,  # Disable reload in production
        "workers": 1,  # Single worker to prevent conflicts
        "timeout_keep_alive": 65,  # Keep connections alive longer
        "timeout_graceful_shutdown": 30,  # Graceful shutdown timeout
        "limit_concurrency": 1000,  # Allow many concurrent connections
        "limit_max_requests": None,  # No request limit
        "access_log": True,
        "log_level": "info",
        # CRITICAL: Extended timeouts for QuickBooks operations
        "h11_max_incomplete_event_size": 16 * 1024 * 1024,  # 16MB for large requests
    }
    
    logger.info("🚀 Uvicorn configured for QuickBooks operations:")
    logger.info(f"   🌐 Host: {host}:{port}")
    logger.info(f"   ⏰ Keep-alive timeout: {config['timeout_keep_alive']}s")
    logger.info(f"   🔄 Graceful shutdown: {config['timeout_graceful_shutdown']}s")
    logger.info(f"   📊 Max concurrency: {config['limit_concurrency']}")
    
    return config

def main():
    """Main startup function with timeout protection"""
    
    logger.info("🏁 Starting MPI Backend with QuickBooks timeout protection...")
    
    try:
        # Setup environment for optimal performance
        setup_environment()
        
        # Get uvicorn configuration
        config = get_uvicorn_config()
        
        # Add additional safety measures
        logger.info("🛡️  Safety measures activated:")
        logger.info("   ✅ Background job pausing during QB exports")
        logger.info("   ✅ Dedicated database connection pool")
        logger.info("   ✅ Progressive timeout handling")
        logger.info("   ✅ Chunked processing for large datasets")
        logger.info("   ✅ Real-time progress tracking")
        
        # Start the server
        logger.info("🚀 Starting server with enhanced timeout protection...")
        uvicorn.run(**config)
        
    except KeyboardInterrupt:
        logger.info("🛑 Server shutdown requested by user")
    except Exception as e:
        logger.error(f"❌ Server startup failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 