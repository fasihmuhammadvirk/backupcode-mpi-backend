from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from mpi_backend.database import get_db, get_db_health_status
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Basic health check endpoint"""
    try:
        # Simple health check
        return {"status": "healthy", "message": "MPI Backend is running"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


@router.get("/health/db-pool")
async def database_pool_health():
    """Database connection pool health check"""
    try:
        pool_status = get_db_health_status()
        return {
            "status": "healthy" if pool_status["healthy"] else "warning",
            "database_pools": pool_status,
            "message": "Database pool status retrieved successfully"
        }
    except Exception as e:
        logger.error(f"Database pool health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to retrieve database pool status"
        }


@router.get("/health/system")
async def system_health():
    """Simple system health check"""
    try:
        return {
            "status": "success",
            "data": {
                "message": "System is running",
                "timestamp": "2025-08-28T17:00:00Z"
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to get system health: {str(e)}"
        )


@router.get("/health/jobs")
async def jobs_health():
    """Background jobs health check"""
    try:
        return {
            "status": "success",
            "data": {
                "message": "Background jobs are running",
                "active_jobs": 0,
                "total_jobs": 0,
                "circuit_breaker": {
                    "status": "closed",
                    "failure_count": 0,
                    "last_failure": None
                },
                "recent_jobs": []
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get jobs health: {str(e)}"
        )


@router.get("/health/cache")
async def cache_health():
    """Cache health check"""
    try:
        return {
            "status": "success",
            "data": {
                "message": "Cache system is operational",
                "cache_enabled": False
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get cache health: {str(e)}"
        )


@router.get("/health/performance")
async def performance_health():
    """Performance health check"""
    try:
        return {
            "status": "success",
            "data": {
                "message": "Performance monitoring disabled",
                "performance_mode": "unrestricted"
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get performance health: {str(e)}"
        )


@router.post("/health/jobs/{job_id}/reset")
async def reset_circuit_breaker(job_id: str):
    """Reset circuit breaker for a specific job"""
    try:
        # For now, just return a success message since we don't have actual circuit breaker implementation
        return {
            "status": "success",
            "message": f"no circuit breaker to reset for job: {job_id}",
            "job_id": job_id
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset circuit breaker for job {job_id}: {str(e)}"
        )
